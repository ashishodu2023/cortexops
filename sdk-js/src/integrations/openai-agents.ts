import { parseArgs, toJsonSafe } from "../json.js";
import type { CortexTracer, TraceRun } from "../tracer.js";
import { asArray, normalizeUsage, proxyWith, safely, type AnyFn } from "./shared.js";

/** `run(agent, input, options)` from `@openai/agents`. */
export type OpenAIAgentsRunFn = (agent: any, input: any, options?: any) => any;

function agentName(agent: any): string | undefined {
  return typeof agent?.name === "string" ? agent.name : undefined;
}

/** Record tool calls, handoffs, usage and the final output of an OpenAI Agents `RunResult`. */
export function recordAgentsResult(run: TraceRun, result: any, agent: any): void {
  const lastAgent = agentName(result?.lastAgent) ?? agentName(agent) ?? "agent";
  const node = run.addNode(lastAgent);
  const outputs = new Map<string, unknown>();
  for (const item of asArray(result?.newItems)) {
    if (item?.type === "tool_call_output_item") {
      const id = item.rawItem?.callId ?? item.rawItem?.id;
      if (id) outputs.set(id, item.output ?? item.rawItem?.output);
    }
  }
  for (const item of asArray(result?.newItems)) {
    if (item?.type !== "tool_call_item" && item?.type !== "handoff_call_item") continue;
    const raw = item.rawItem ?? {};
    const name = raw.name ?? raw.type;
    if (typeof name !== "string") continue;
    const id = raw.callId ?? raw.id;
    run.recordToolCall(name, {
      args: parseArgs(raw.arguments),
      result: id !== undefined ? outputs.get(id) ?? null : null,
      node,
    });
  }
  for (const response of asArray(result?.rawResponses)) run.addUsage(normalizeUsage(response?.usage));
  run.setMetadata("agent", lastAgent);
}

function agentsOutput(result: any): Record<string, unknown> {
  const out: Record<string, unknown> = { output: toJsonSafe(result?.finalOutput) ?? null };
  const last = agentName(result?.lastAgent);
  if (last) out.last_agent = last;
  return out;
}

function agentsInput(agent: any, input: unknown): Record<string, unknown> {
  const out: Record<string, unknown> = { input: toJsonSafe(input) ?? null };
  const name = agentName(agent);
  if (name) out.agent = name;
  return out;
}

/**
 * Wrap the `run` function from `@openai/agents` so every agent run is traced
 * (tool calls, handoffs, usage, final output). Streaming runs are finalized when
 * `result.completed` settles.
 *
 * ```ts
 * import { run } from "@openai/agents";
 * const tracedRun = wrapOpenAIAgentsRun(tracer, run);
 * const result = await tracedRun(agent, "Refund REF-8821");
 * ```
 */
export function wrapOpenAIAgentsRun<F extends OpenAIAgentsRunFn>(tracer: CortexTracer, runFn: F): F {
  const wrapped = function (this: unknown, agent: any, input: any, options?: any) {
    const run = tracer.startTrace(agentsInput(agent, input), { framework: "openai_agents" });
    const finish = (result: any) =>
      safely(() => {
        recordAgentsResult(run, result, agent);
        run.end(agentsOutput(result));
      });
    let pending: any;
    try {
      pending = run.run(() => runFn.call(this, agent, input, options));
    } catch (err) {
      run.fail(err);
      throw err;
    }
    return Promise.resolve(pending).then(
      (result: any) => {
        if (options?.stream && result?.completed && typeof result.completed.then === "function") {
          result.completed.then(
            () => (result.error ? run.fail(result.error) : finish(result)),
            (err: unknown) => run.fail(err),
          );
        } else {
          finish(result);
        }
        return result;
      },
      (err: unknown) => {
        run.fail(err);
        throw err;
      },
    );
  };
  return wrapped as unknown as F;
}

async function importAgentsRun(): Promise<OpenAIAgentsRunFn> {
  const specifier = "@openai/agents";
  let mod: any;
  try {
    mod = await import(specifier);
  } catch (err) {
    throw new Error("Install @openai/agents, or pass { run } to wrapOpenAIAgent()", { cause: err });
  }
  if (typeof mod.run !== "function") throw new Error("@openai/agents does not export run()");
  return mod.run;
}

/**
 * Wrap an OpenAI Agents SDK `Agent` so that `wrapped.run(input, options)` executes it with
 * `run()` from `@openai/agents` (or the `run` you pass) under a trace.
 */
export function wrapOpenAIAgent<A extends object>(
  tracer: CortexTracer,
  agent: A,
  options: { run?: OpenAIAgentsRunFn } = {},
): A & { run(input: any, options?: any): Promise<any> } {
  let traced: OpenAIAgentsRunFn | undefined = options.run ? wrapOpenAIAgentsRun(tracer, options.run) : undefined;
  const runAgent: AnyFn = async (input: any, runOptions?: any) => {
    if (!traced) traced = wrapOpenAIAgentsRun(tracer, await importAgentsRun());
    return traced(agent, input, runOptions);
  };
  return proxyWith(agent, { run: runAgent }) as A & { run(input: any, options?: any): Promise<any> };
}
