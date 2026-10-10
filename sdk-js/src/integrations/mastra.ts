import { argsToInput } from "../json.js";
import type { CortexTracer } from "../tracer.js";
import {
  generationOutput,
  modelIdOf,
  proxyWith,
  recordGenerationResult,
  traceCallbackStream,
} from "./shared.js";

/** Structural type of a Mastra `Agent`. */
export interface MastraAgentLike {
  name?: string;
  generate(messages: any, options?: any): Promise<any>;
  stream?(messages: any, options?: any): any;
}

function agentModelId(agent: any): string | undefined {
  return modelIdOf(agent?.model);
}

function mastraInput(agent: any, messages: unknown): Record<string, unknown> {
  const input = argsToInput([messages]);
  if (typeof agent?.name === "string") input.agent = agent.name;
  return input;
}

/**
 * Trace a Mastra agent: `generate()` records steps, tool calls (with results) and usage;
 * `stream()` is finalized from its `onFinish` callback.
 */
export function wrapMastraAgent<A extends MastraAgentLike>(tracer: CortexTracer, agent: A): A {
  const overrides: Record<string, unknown> = {
    generate: (messages: unknown, options?: any) =>
      tracer.runTraced(() => agent.generate(messages, options), {
        input: mastraInput(agent, messages),
        framework: "mastra",
        onResult: (result, run) => recordGenerationResult(run, result, agentModelId(agent)),
        toOutput: (result) => generationOutput(result),
      }),
  };
  if (typeof agent.stream === "function") {
    const stream = agent.stream;
    overrides.stream = (messages: unknown, options?: any) =>
      traceCallbackStream(
        tracer,
        (patched) => stream.call(agent, messages, patched),
        options,
        mastraInput(agent, messages),
        "mastra",
        agentModelId(agent),
      );
  }
  return proxyWith(agent, overrides);
}
