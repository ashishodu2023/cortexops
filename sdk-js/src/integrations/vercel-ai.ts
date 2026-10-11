import { parseArgs, toJsonSafe, toRecord } from "../json.js";
import type { TraceNode } from "../models.js";
import type { CortexTracer, TraceRun } from "../tracer.js";
import {
  asArray,
  finishReasonOf,
  generationOutput,
  modelIdOf,
  normalizeUsage,
  recordGenerationResult,
  safely,
  traceCallbackStream,
  type AnyFn,
} from "./shared.js";

const MAX_PROMPT_CHARS = 8000;

function callInput(options: any): Record<string, unknown> {
  const o = options ?? {};
  const input: Record<string, unknown> = {};
  if (o.system !== undefined) input.system = o.system;
  if (o.prompt !== undefined) input.prompt = o.prompt;
  if (o.messages !== undefined) input.messages = o.messages;
  const model = modelIdOf(o.model);
  if (model) input.model = model;
  if (o.tools && typeof o.tools === "object") input.tools = Object.keys(o.tools);
  return toRecord(input);
}

/**
 * Trace Vercel AI SDK `generateText` (or `generateObject`) calls: model, every step,
 * executed tool calls with their results, and token usage.
 *
 * ```ts
 * import { generateText } from "ai";
 * const tracedGenerateText = wrapGenerateText(tracer, generateText);
 * ```
 */
export function wrapGenerateText<F extends AnyFn>(tracer: CortexTracer, generateText: F): F {
  const wrapped = function (this: unknown, options: any) {
    return tracer.runTraced(() => generateText.call(this, options), {
      input: callInput(options),
      framework: "vercel_ai",
      onResult: (result, run) => recordGenerationResult(run, result, modelIdOf(options?.model)),
      toOutput: (result) => generationOutput(result),
    });
  };
  Object.defineProperty(wrapped, "name", { value: generateText.name });
  return wrapped as F;
}

/**
 * Trace Vercel AI SDK `streamText` calls. The result is returned untouched; the trace is
 * finalized from `onFinish` / `onError` (your own callbacks are still invoked).
 */
export function wrapStreamText<F extends AnyFn>(tracer: CortexTracer, streamText: F): F {
  const wrapped = function (this: unknown, options: any) {
    return traceCallbackStream(
      tracer,
      (patched) => streamText.call(this, patched),
      options,
      callInput(options),
      "vercel_ai",
      modelIdOf(options?.model),
    );
  };
  Object.defineProperty(wrapped, "name", { value: streamText.name });
  return wrapped as F;
}

// ── Language model middleware ───────────────────────────────────────────────

function promptText(prompt: unknown): string | null {
  if (prompt === undefined) return null;
  const text = typeof prompt === "string" ? prompt : JSON.stringify(toJsonSafe(prompt));
  return text.length > MAX_PROMPT_CHARS ? `${text.slice(0, MAX_PROMPT_CHARS)}...` : text;
}

function modelResultText(result: any): string | null {
  if (Array.isArray(result?.content)) {
    return result.content
      .filter((p: any) => p?.type === "text" && typeof p.text === "string")
      .map((p: any) => p.text)
      .join("");
  }
  return typeof result?.text === "string" ? result.text : null;
}

function modelToolCalls(result: any): Array<{ name: string; args: unknown }> {
  const parts = Array.isArray(result?.content)
    ? result.content.filter((p: any) => p?.type === "tool-call")
    : asArray(result?.toolCalls);
  return parts
    .filter((p: any) => typeof p?.toolName === "string")
    .map((p: any) => ({ name: p.toolName, args: p.input ?? p.args }));
}

function finishModelNode(
  run: TraceRun,
  node: TraceNode,
  t0: number,
  text: string | null,
  toolCalls: Array<{ name: string; args: unknown }>,
  usage: unknown,
  finishReason: unknown,
  owning: boolean,
): void {
  node.latency_ms = performance.now() - t0;
  node.llm_response = text;
  const normalized = normalizeUsage(usage);
  node.output = toRecord({ finish_reason: finishReasonOf(finishReason), usage: normalized });
  for (const tc of toolCalls) run.recordToolCall(tc.name, { args: parseArgs(tc.args), node });
  if (owning) run.addUsage(normalized);
}

/**
 * Language-model middleware for `wrapLanguageModel({ model, middleware })`. Each model call
 * becomes an `llm:<modelId>` node (prompt, response, requested tool calls, usage) on the
 * active trace; outside a trace every call gets its own trace.
 */
export function cortexopsMiddleware(tracer: CortexTracer) {
  async function withRun<T>(model: any, params: any, exec: (run: TraceRun, owning: boolean) => Promise<T>, streaming: boolean): Promise<T> {
    const active = tracer.currentRun();
    if (active && !active.isFinished) return exec(active, false);
    const modelId = modelIdOf(model);
    const run = tracer.startTrace(toRecord({ model: modelId, prompt: promptText(params?.prompt) }), {
      framework: "vercel_ai",
    });
    if (modelId) run.setMetadata("model", modelId);
    try {
      const result = await run.run(() => exec(run, true));
      if (!streaming) run.end({ output: modelResultText(result) });
      return result;
    } catch (err) {
      run.fail(err);
      throw err;
    }
  }

  return {
    // `any` so the same object satisfies the AI SDK 5, 6 and 7 middleware types.
    specificationVersion: "v4" as any,
    wrapGenerate: async ({ doGenerate, params, model }: { doGenerate: () => PromiseLike<any>; params?: any; model?: any }) =>
      withRun(
        model,
        params,
        async (run, owning) => {
          const node = run.addNode(`llm:${modelIdOf(model) ?? "model"}`, { llm_prompt: promptText(params?.prompt) });
          const t0 = performance.now();
          try {
            const result = await doGenerate();
            safely(() =>
              finishModelNode(run, node, t0, modelResultText(result), modelToolCalls(result), result?.usage, result?.finishReason, owning),
            );
            return result;
          } catch (err) {
            node.latency_ms = performance.now() - t0;
            throw err;
          }
        },
        false,
      ),

    wrapStream: async ({ doStream, params, model }: { doStream: () => PromiseLike<any>; params?: any; model?: any }) =>
      withRun(
        model,
        params,
        async (run, owning) => {
          const node = run.addNode(`llm:${modelIdOf(model) ?? "model"}`, { llm_prompt: promptText(params?.prompt) });
          const t0 = performance.now();
          const result = await doStream();
          let text = "";
          const toolCalls: Array<{ name: string; args: unknown }> = [];
          let usage: unknown;
          let finishReason: unknown;
          let failed: unknown;
          const observer = new TransformStream<any, any>({
            transform(part, controller) {
              safely(() => {
                switch (part?.type) {
                  case "text-delta":
                    text += part.delta ?? part.textDelta ?? "";
                    break;
                  case "tool-call":
                    if (typeof part.toolName === "string") toolCalls.push({ name: part.toolName, args: part.input ?? part.args });
                    break;
                  case "finish":
                    usage = part.usage;
                    finishReason = part.finishReason;
                    break;
                  case "error":
                    failed = part.error ?? new Error("stream error");
                    break;
                }
              });
              controller.enqueue(part);
            },
            flush() {
              safely(() => {
                finishModelNode(run, node, t0, text, toolCalls, usage, finishReason, owning);
                if (!owning) return;
                if (failed !== undefined) run.fail(failed);
                else run.end({ output: text });
              });
            },
          });
          return { ...result, stream: result.stream.pipeThrough(observer) };
        },
        true,
      ),
  };
}
