import { argsToInput } from "../json.js";
import type { CortexTracer } from "../tracer.js";
import { wrapLangGraph, type LangGraphLike } from "./langgraph.js";
import { wrapMastraAgent, type MastraAgentLike } from "./mastra.js";
import { wrapOpenAIAgent } from "./openai-agents.js";
import { proxyWith, type AnyFn } from "./shared.js";
import { wrapGenerateText, wrapStreamText } from "./vercel-ai.js";

export { cortexopsMiddleware, wrapGenerateText, wrapStreamText } from "./vercel-ai.js";
export { langChainHandler, wrapLangGraph, type LangGraphLike } from "./langgraph.js";
export {
  recordAgentsResult,
  wrapOpenAIAgent,
  wrapOpenAIAgentsRun,
  type OpenAIAgentsRunFn,
} from "./openai-agents.js";
export { wrapMastraAgent, type MastraAgentLike } from "./mastra.js";
export { normalizeUsage, recordGenerationResult } from "./shared.js";

export type Framework =
  | "langgraph"
  | "mastra"
  | "openai_agents"
  | "vercel_ai_generate"
  | "vercel_ai_stream"
  | "invoke"
  | "generic";

const isFn = (value: unknown): value is AnyFn => typeof value === "function";

/** Identify the agent framework from the object's shape (no framework imports needed). */
export function detectFramework(agent: unknown): Framework {
  if (typeof agent === "function") {
    // bundlers may suffix renamed functions (generateText2)
    if (/^(generateText|generateObject)\d*$/.test(agent.name)) return "vercel_ai_generate";
    if (/^(streamText|streamObject)\d*$/.test(agent.name)) return "vercel_ai_stream";
    return "generic";
  }
  if (!agent || typeof agent !== "object") return "generic";
  const a = agent as Record<string, unknown>;
  const ctor = (a.constructor as { name?: string } | undefined)?.name ?? "";
  if (
    isFn(a.invoke) &&
    isFn(a.stream) &&
    (ctor === "CompiledStateGraph" || ctor === "CompiledGraph" || ctor === "Pregel" || (isFn(a.getGraph) && "nodes" in a))
  ) {
    return "langgraph";
  }
  if (isFn(a.generate) && (isFn(a.getInstructions) || isFn(a.__registerMastra) || isFn(a.getModel))) return "mastra";
  if (isFn(a.asTool) && Array.isArray(a.handoffs)) return "openai_agents";
  if (isFn(a.invoke)) return "invoke";
  return "generic";
}

function wrapCallable<F extends AnyFn>(tracer: CortexTracer, fn: F): F {
  const wrapped = function (this: unknown, ...args: unknown[]) {
    return tracer.runTraced(() => fn.apply(this, args), { input: argsToInput(args), framework: "generic" });
  };
  Object.defineProperty(wrapped, "name", { value: fn.name });
  return wrapped as F;
}

function wrapInvoke<T extends { invoke: AnyFn }>(tracer: CortexTracer, agent: T): T {
  return proxyWith(agent, {
    invoke: (...args: unknown[]) =>
      tracer.runTraced(() => agent.invoke(...args), { input: argsToInput(args.slice(0, 1)), framework: "generic" }),
  });
}

/** Dispatch used by `CortexTracer.wrap()`. */
export function wrapAgent<T>(tracer: CortexTracer, agent: T): T {
  switch (detectFramework(agent)) {
    case "langgraph":
      return wrapLangGraph(tracer, agent as unknown as LangGraphLike) as T;
    case "mastra":
      return wrapMastraAgent(tracer, agent as unknown as MastraAgentLike) as T;
    case "openai_agents":
      return wrapOpenAIAgent(tracer, agent as unknown as object) as T;
    case "vercel_ai_generate":
      return wrapGenerateText(tracer, agent as unknown as AnyFn) as T;
    case "vercel_ai_stream":
      return wrapStreamText(tracer, agent as unknown as AnyFn) as T;
    case "invoke":
      return wrapInvoke(tracer, agent as unknown as { invoke: AnyFn }) as T;
    default:
      if (typeof agent === "function") return wrapCallable(tracer, agent as unknown as AnyFn) as T;
      throw new TypeError("CortexTracer.wrap() expects a function or an agent object (LangGraph, Mastra, OpenAI Agents, or .invoke())");
  }
}
