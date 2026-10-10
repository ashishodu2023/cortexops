import { isPromiseLike, parseArgs, toJsonSafe, toRecord, errorMessage } from "../json.js";
import type { CortexTracer, TraceRun, UsageInfo } from "../tracer.js";

export type AnyFn = (...args: any[]) => any;

export function asArray(value: unknown): any[] {
  return Array.isArray(value) ? value : [];
}

function tokenCount(value: unknown): number | undefined {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (value && typeof value === "object") {
    const total = (value as { total?: unknown }).total;
    if (typeof total === "number" && Number.isFinite(total)) return total;
  }
  return undefined;
}

/** Normalize token usage from Vercel AI SDK v4/v5/v6, Mastra and OpenAI Agents shapes. */
export function normalizeUsage(usage: unknown): UsageInfo | undefined {
  if (!usage || typeof usage !== "object") return undefined;
  const u = usage as Record<string, unknown>;
  const input = tokenCount(u.inputTokens) ?? tokenCount(u.promptTokens) ?? tokenCount(u.input_tokens);
  const output = tokenCount(u.outputTokens) ?? tokenCount(u.completionTokens) ?? tokenCount(u.output_tokens);
  let total = tokenCount(u.totalTokens) ?? tokenCount(u.total_tokens);
  if (input === undefined && output === undefined && total === undefined) return undefined;
  if (total === undefined) total = (input ?? 0) + (output ?? 0);
  const out: UsageInfo = { total_tokens: total };
  if (input !== undefined) out.input_tokens = input;
  if (output !== undefined) out.output_tokens = output;
  return out;
}

export function modelIdOf(model: unknown): string | undefined {
  if (typeof model === "string") return model;
  if (model && typeof model === "object") {
    const id = (model as { modelId?: unknown }).modelId;
    if (typeof id === "string") return id;
  }
  return undefined;
}

interface NormalizedToolCall {
  name: string;
  args: unknown;
  result: unknown;
  error: string | null;
}

const idOf = (x: any): string | undefined => x?.toolCallId ?? x?.payload?.toolCallId;
const nameOf = (x: any): string | undefined => x?.toolName ?? x?.payload?.toolName ?? x?.name;
const argsOf = (x: any): unknown => x?.input ?? x?.args ?? x?.payload?.args ?? x?.payload?.input;
function resultOf(x: any): unknown {
  if (x && typeof x === "object") {
    if ("output" in x) return x.output;
    if ("result" in x) return x.result;
    if (x.payload && typeof x.payload === "object") return x.payload.result ?? x.payload.output;
  }
  return undefined;
}

/** Executed tool calls in a Vercel AI SDK / Mastra step (or result), matched with their results. */
export function toolCallsOf(step: any): NormalizedToolCall[] {
  const results = new Map<string, any>();
  for (const r of asArray(step?.toolResults)) {
    const id = idOf(r);
    if (id) results.set(id, r);
  }
  const errors = new Map<string, any>();
  for (const part of asArray(step?.content)) {
    if (part?.type === "tool-error" && idOf(part)) errors.set(idOf(part)!, part);
  }
  const out: NormalizedToolCall[] = [];
  for (const call of asArray(step?.toolCalls)) {
    const name = nameOf(call);
    if (!name) continue;
    const id = idOf(call);
    const res = id ? results.get(id) : undefined;
    const err = id ? errors.get(id) : undefined;
    out.push({
      name,
      args: argsOf(call),
      result: res === undefined ? null : resultOf(res),
      error: err ? errorMessage(err.error) : null,
    });
  }
  return out;
}

/** Text of a generation result (`text` for AI SDK / Mastra, `finalOutput` for OpenAI Agents). */
export function outputTextOf(result: any): unknown {
  if (result == null) return null;
  if (typeof result === "string") return result;
  if (typeof result.text === "string") return result.text;
  if (result.object !== undefined) return toJsonSafe(result.object);
  if (result.finalOutput !== undefined) return toJsonSafe(result.finalOutput);
  return null;
}

/** Attach steps, tool calls, usage and model from an AI-SDK-shaped result to `run`. */
export function recordGenerationResult(run: TraceRun, result: any, modelId?: string): void {
  if (!result || typeof result !== "object") return;
  const steps = asArray(result.steps);
  const sources = steps.length ? steps : [result];
  sources.forEach((step, i) => {
    const usage = normalizeUsage(step?.usage);
    const node = run.addNode(steps.length ? `step_${i + 1}` : "generate", {
      llm_response: typeof step?.text === "string" ? step.text : null,
      output: toRecord({ finish_reason: finishReasonOf(step?.finishReason), usage }),
    });
    for (const tc of toolCallsOf(step)) {
      run.recordToolCall(tc.name, { args: parseArgs(tc.args), result: tc.result, error: tc.error, node });
    }
  });
  run.addUsage(normalizeUsage(result.totalUsage ?? result.usage));
  const model = modelIdOf(result.response?.modelId) ?? modelId;
  if (model) run.setMetadata("model", model);
}

/** Finish reason as a string: language model spec v3+ reports `{ unified, raw }`. */
export function finishReasonOf(value: unknown): unknown {
  if (value && typeof value === "object" && typeof (value as any).unified === "string") return (value as any).unified;
  return toJsonSafe(value);
}

export function generationOutput(result: any): Record<string, unknown> {
  const out: Record<string, unknown> = { output: outputTextOf(result) };
  if (result && typeof result === "object" && result.finishReason !== undefined) {
    out.finish_reason = finishReasonOf(result.finishReason);
  }
  return out;
}

export function safely(fn: () => void): void {
  try {
    fn();
  } catch {
    // instrumentation must never break the agent
  }
}

/**
 * Trace a streaming call whose completion is reported through `onFinish` / `onError` /
 * `onAbort` callbacks in its options object (Vercel AI SDK `streamText`, Mastra `stream`).
 * User callbacks are preserved and still called.
 */
export function traceCallbackStream(
  tracer: CortexTracer,
  call: (patchedOptions: Record<string, any>) => any,
  options: Record<string, any> | undefined,
  input: Record<string, unknown>,
  framework: string,
  modelId: string | undefined,
): any {
  const run = tracer.startTrace(input, { framework });
  const user = options ?? {};
  const patched: Record<string, any> = {
    ...user,
    onFinish: async (event: any) => {
      safely(() => {
        recordGenerationResult(run, event, modelId);
        run.end(generationOutput(event));
      });
      if (typeof user.onFinish === "function") return user.onFinish(event);
    },
    onError: async (event: any) => {
      const error = event && typeof event === "object" && "error" in event ? event.error : event;
      safely(() => run.fail(error));
      if (typeof user.onError === "function") return user.onError(event);
      console.error(error);
    },
    onAbort: async (event: any) => {
      safely(() => run.fail(new Error("stream aborted")));
      if (typeof user.onAbort === "function") return user.onAbort(event);
    },
  };
  let result: any;
  try {
    result = run.run(() => call(patched));
  } catch (err) {
    run.fail(err);
    throw err;
  }
  if (isPromiseLike(result)) {
    return Promise.resolve(result).catch((err: unknown) => {
      run.fail(err);
      throw err;
    });
  }
  return result;
}

/** Proxy `target`, overriding some members; other methods stay bound to the original object. */
export function proxyWith<T extends object>(target: T, overrides: Record<PropertyKey, unknown>): T {
  const bound = new Map<PropertyKey, unknown>();
  return new Proxy(target, {
    get(obj, prop) {
      if (Object.prototype.hasOwnProperty.call(overrides, prop)) return overrides[prop];
      const value = Reflect.get(obj, prop, obj);
      if (typeof value !== "function") return value;
      if (!bound.has(prop)) bound.set(prop, (value as AnyFn).bind(obj));
      return bound.get(prop);
    },
  });
}
