import { argsToInput, errorMessage, parseArgs, toJsonSafe, toRecord } from "../json.js";
import type { TraceNode } from "../models.js";
import type { CortexTracer, TraceRun } from "../tracer.js";
import { proxyWith, safely } from "./shared.js";

/** Structural type of a compiled LangGraph.js graph (`StateGraph#compile()`). */
export interface LangGraphLike {
  invoke(input: any, config?: any): Promise<any>;
  stream(input: any, config?: any): Promise<AsyncIterable<any>> | AsyncIterable<any>;
}

/** LangGraph's own `__start__` / `__end__` pseudo-nodes. */
const INTERNAL_NODE = /^__.*__$/;

/**
 * A LangChain callback handler (plain-object form) that records graph nodes and tool
 * executions onto `run`. LangChain accepts plain handler objects in `config.callbacks`.
 */
export function langChainHandler(run: TraceRun) {
  const nodes = new Map<string, { node: TraceNode; t0: number }>();
  const latestByName = new Map<string, TraceNode>();
  const tools = new Map<string, { name: string; input: unknown; t0: number; nodeName?: string }>();

  const toolName = (tool: any, runName?: string): string => {
    if (typeof runName === "string" && runName) return runName;
    if (typeof tool?.name === "string") return tool.name;
    const id = Array.isArray(tool?.id) ? tool.id[tool.id.length - 1] : undefined;
    return typeof id === "string" ? id : "tool";
  };

  const finishTool = (runId: string, result: unknown, error: string | null) => {
    const t = tools.get(runId);
    if (!t) return;
    tools.delete(runId);
    const node = t.nodeName ? latestByName.get(t.nodeName) : undefined;
    const content = result && typeof result === "object" && "content" in result ? (result as any).content : result;
    run.recordToolCall(t.name, {
      args: parseArgs(t.input),
      result: content,
      error,
      latencyMs: performance.now() - t.t0,
      ...(node ? { node } : {}),
    });
  };

  return {
    handleChainStart(
      _chain: unknown,
      inputs: unknown,
      runId: string,
      _parentRunId?: string,
      _tags?: string[],
      metadata?: Record<string, unknown>,
      _runType?: string,
      runName?: string,
    ) {
      safely(() => {
        const nodeName = metadata?.langgraph_node;
        if (typeof nodeName !== "string" || runName !== nodeName || INTERNAL_NODE.test(nodeName)) return;
        const node = run.addNode(nodeName, { input: toRecord(inputs, "input") });
        nodes.set(runId, { node, t0: performance.now() });
        latestByName.set(nodeName, node);
      });
    },
    handleChainEnd(outputs: unknown, runId: string) {
      safely(() => {
        const entry = nodes.get(runId);
        if (!entry) return;
        nodes.delete(runId);
        entry.node.output = toRecord(outputs, "output");
        entry.node.latency_ms = performance.now() - entry.t0;
      });
    },
    handleChainError(err: unknown, runId: string) {
      safely(() => {
        const entry = nodes.get(runId);
        if (!entry) return;
        nodes.delete(runId);
        entry.node.output = { error: errorMessage(err) };
        entry.node.latency_ms = performance.now() - entry.t0;
      });
    },
    handleToolStart(
      tool: unknown,
      input: unknown,
      runId: string,
      _parentRunId?: string,
      _tags?: string[],
      metadata?: Record<string, unknown>,
      runName?: string,
    ) {
      safely(() => {
        const nodeName = typeof metadata?.langgraph_node === "string" ? metadata.langgraph_node : undefined;
        tools.set(runId, { name: toolName(tool, runName), input, t0: performance.now(), ...(nodeName ? { nodeName } : {}) });
      });
    },
    handleToolEnd(output: unknown, runId: string) {
      safely(() => finishTool(runId, output, null));
    },
    handleToolError(err: unknown, runId: string) {
      safely(() => finishTool(runId, null, errorMessage(err)));
    },
  };
}

function withHandler(config: any, run: TraceRun): any {
  const handler = langChainHandler(run);
  if (config === undefined || config === null) return { callbacks: [handler] };
  if (typeof config !== "object") return config;
  const callbacks = config.callbacks;
  if (callbacks === undefined || callbacks === null) return { ...config, callbacks: [handler] };
  if (Array.isArray(callbacks)) return { ...config, callbacks: [...callbacks, handler] };
  // A CallbackManager instance: leave it alone, the run is still traced at graph level.
  return config;
}

function graphInput(input: unknown): Record<string, unknown> {
  return argsToInput([input]);
}

function wrapIterable<T>(source: AsyncIterable<T>, run: TraceRun): AsyncIterable<T> {
  let last: unknown;
  const finish = () => run.end(last === undefined ? undefined : toJsonSafe(last));
  const iterate = (): AsyncIterator<T> => {
    const it = source[Symbol.asyncIterator]();
    return {
      async next(...args: [] | [any]) {
        try {
          const step = await run.run(() => it.next(...args));
          if (step.done) finish();
          else last = step.value;
          return step;
        } catch (err) {
          run.fail(err);
          throw err;
        }
      },
      async return(value?: any) {
        finish();
        return it.return ? it.return(value) : { done: true as const, value };
      },
      async throw(err?: any) {
        run.fail(err);
        if (it.throw) return it.throw(err);
        throw err;
      },
    };
  };
  return proxyWith(source as AsyncIterable<T> & object, { [Symbol.asyncIterator]: iterate });
}

/**
 * Trace a compiled LangGraph.js graph. `invoke` and `stream` produce one trace per call with
 * one node per graph step and every tool execution (captured via a LangChain callback).
 */
export function wrapLangGraph<G extends LangGraphLike>(tracer: CortexTracer, graph: G): G {
  return proxyWith(graph, {
    invoke: (input: unknown, config?: unknown) =>
      tracer.runTraced((run) => graph.invoke(input, withHandler(config, run)), {
        input: graphInput(input),
        framework: "langgraph",
      }),
    stream: async (input: unknown, config?: unknown) => {
      const run = tracer.startTrace(graphInput(input), { framework: "langgraph" });
      try {
        const stream = await run.run(() => graph.stream(input, withHandler(config, run)));
        return wrapIterable(stream, run);
      } catch (err) {
        run.fail(err);
        throw err;
      }
    },
  });
}
