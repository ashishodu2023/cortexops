import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  CortexTracer,
  EvalSuite,
  cortexopsMiddleware,
  detectFramework,
  parseDataset,
  traceToolCalls,
  wrapGenerateText,
  wrapLangGraph,
  wrapMastraAgent,
  wrapOpenAIAgent,
  wrapOpenAIAgentsRun,
  wrapStreamText,
} from "../src/index.js";
import { isolateEnv, sleep } from "./helpers.js";

beforeEach(() => {
  isolateEnv();
});

// ── Vercel AI SDK ────────────────────────────────────────────────────────────

/** Shaped like AI SDK v5 `DefaultGenerateTextResult` (class with getters). */
class V5Result {
  constructor(private readonly s: any[]) {}
  get steps() {
    return this.s;
  }
  get text() {
    return this.s[this.s.length - 1].text;
  }
  get finishReason() {
    return "stop";
  }
  get totalUsage() {
    return { inputTokens: 30, outputTokens: 12, totalTokens: 42 };
  }
  get response() {
    return { modelId: "gpt-4o-mini-2024", id: "resp_1" };
  }
}

const v5Steps = [
  {
    text: "",
    finishReason: "tool-calls",
    usage: { inputTokens: 10, outputTokens: 5, totalTokens: 15 },
    toolCalls: [{ type: "tool-call", toolCallId: "c1", toolName: "lookup_refund", input: { refund_id: "REF-8821" } }],
    toolResults: [{ type: "tool-result", toolCallId: "c1", toolName: "lookup_refund", input: {}, output: { status: "approved" } }],
    content: [],
  },
  {
    text: "Refund REF-8821 is approved.",
    finishReason: "stop",
    usage: { inputTokens: 20, outputTokens: 7, totalTokens: 27 },
    toolCalls: [{ type: "tool-call", toolCallId: "c2", toolName: "notify", input: { to: "x" } }],
    toolResults: [],
    content: [{ type: "tool-error", toolCallId: "c2", toolName: "notify", error: new Error("smtp down") }],
  },
];

describe("Vercel AI SDK", () => {
  it("wrapGenerateText records steps, tool calls with results/errors, usage and model (v5 shape)", async () => {
    const tracer = new CortexTracer();
    const generateText = vi.fn(async function generateText(_opts: any) {
      await sleep(2);
      return new V5Result(v5Steps);
    });
    const traced = wrapGenerateText(tracer, generateText);
    const result = await traced({ model: { modelId: "gpt-4o-mini", provider: "openai" }, prompt: "Refund REF-8821?", tools: { lookup_refund: {}, notify: {} } });
    expect(result).toBeInstanceOf(V5Result);
    expect(generateText).toHaveBeenCalledOnce();

    const trace = tracer.lastTrace()!;
    expect(trace.input).toEqual({ prompt: "Refund REF-8821?", model: "gpt-4o-mini", tools: ["lookup_refund", "notify"] });
    expect(trace.output).toEqual({ output: "Refund REF-8821 is approved.", finish_reason: "stop" });
    expect(trace.metadata).toMatchObject({ framework: "vercel_ai", model: "gpt-4o-mini-2024", usage: { input_tokens: 30, output_tokens: 12, total_tokens: 42 } });
    expect(trace.nodes.map((n) => n.node_name)).toEqual(["step_1", "step_2"]);
    expect(trace.nodes[1]!.llm_response).toBe("Refund REF-8821 is approved.");
    expect(trace.nodes[0]!.output).toEqual({ finish_reason: "tool-calls", usage: { input_tokens: 10, output_tokens: 5, total_tokens: 15 } });
    expect(traceToolCalls(trace)).toMatchObject([
      { name: "lookup_refund", args: { refund_id: "REF-8821" }, result: { status: "approved" }, status: "success" },
      { name: "notify", args: { to: "x" }, status: "error", error: "smtp down" },
    ]);
  });

  it("handles the v4 shape (args/result, promptTokens) and failures", async () => {
    const tracer = new CortexTracer();
    const v4 = {
      text: "done",
      finishReason: "stop",
      usage: { promptTokens: 8, completionTokens: 2, totalTokens: 10 },
      response: { modelId: "claude-x" },
      steps: [
        {
          text: "done",
          toolCalls: [{ toolCallId: "a", toolName: "search", args: { q: "refund" } }],
          toolResults: [{ toolCallId: "a", toolName: "search", args: { q: "refund" }, result: ["r1"] }],
          usage: { promptTokens: 8, completionTokens: 2, totalTokens: 10 },
        },
      ],
    };
    const traced = wrapGenerateText(tracer, async (_options: any) => v4);
    await traced({ model: "anthropic/claude-x", messages: [{ role: "user", content: "hi" }] });
    const trace = tracer.lastTrace()!;
    expect(trace.metadata.usage).toEqual({ input_tokens: 8, output_tokens: 2, total_tokens: 10 });
    expect(trace.input.model).toBe("anthropic/claude-x");
    expect(traceToolCalls(trace)[0]).toMatchObject({ name: "search", args: { q: "refund" }, result: ["r1"] });

    const failing = wrapGenerateText(tracer, async (_options: any) => {
      throw new Error("rate limited");
    });
    await expect(failing({ prompt: "x" })).rejects.toThrow("rate limited");
    expect(tracer.lastTrace()).toMatchObject({ status: "failed", failure_detail: "rate limited" });
  });

  it("wrapStreamText finalizes from onFinish and keeps user callbacks", async () => {
    const tracer = new CortexTracer();
    const userFinish = vi.fn();
    const streamText = vi.fn(function streamText(opts: any) {
      setTimeout(() => void opts.onFinish({ ...new V5Result(v5Steps), steps: v5Steps, text: "streamed", totalUsage: { inputTokens: 1, outputTokens: 2, totalTokens: 3 }, finishReason: "stop" }), 5);
      return { textStream: "fake", consumed: true };
    });
    const traced = wrapStreamText(tracer, streamText);
    const result = traced({ model: { modelId: "m" }, prompt: "p", onFinish: userFinish });
    expect(result).toEqual({ textStream: "fake", consumed: true });
    expect(tracer.lastTrace()).toBeUndefined();
    await sleep(20);
    expect(userFinish).toHaveBeenCalledOnce();
    const trace = tracer.lastTrace()!;
    expect(trace.output).toEqual({ output: "streamed", finish_reason: "stop" });
    expect(trace.metadata.usage).toEqual({ input_tokens: 1, output_tokens: 2, total_tokens: 3 });
    expect(traceToolCalls(trace).map((t) => t.name)).toEqual(["lookup_refund", "notify"]);
  });

  it("wrapStreamText records stream errors and preserves the default error logging", async () => {
    const tracer = new CortexTracer();
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => undefined);
    const traced = wrapStreamText(tracer, (opts: any) => {
      setTimeout(() => void opts.onError({ error: new Error("stream broke") }), 1);
      return {};
    });
    traced({ prompt: "p" });
    await sleep(10);
    expect(tracer.lastTrace()).toMatchObject({ status: "failed", failure_detail: "stream broke" });
    expect(consoleError).toHaveBeenCalled();

    const userError = vi.fn();
    const traced2 = wrapStreamText(tracer, (opts: any) => {
      setTimeout(() => void opts.onError({ error: new Error("again") }), 1);
      return {};
    });
    traced2({ prompt: "p", onError: userError });
    await sleep(10);
    expect(userError).toHaveBeenCalledWith({ error: expect.any(Error) });
    expect(consoleError).toHaveBeenCalledTimes(1);
  });

  it("middleware: wrapGenerate attaches llm nodes to the active trace", async () => {
    const tracer = new CortexTracer();
    const mw = cortexopsMiddleware(tracer);
    const model = { modelId: "gpt-test" };
    const doGenerate = async () => ({
      content: [
        { type: "text", text: "calling tool" },
        { type: "tool-call", toolCallId: "t1", toolName: "lookup_refund", input: '{"refund_id":"REF-1"}' },
      ],
      finishReason: "tool-calls",
      usage: { inputTokens: 5, outputTokens: 3, totalTokens: 8 },
    });
    const agent = tracer.wrap(async () => {
      await mw.wrapGenerate({ doGenerate, params: { prompt: [{ role: "user", content: [{ type: "text", text: "hi" }] }] }, model });
      return { output: "ok" };
    });
    await agent();
    const trace = tracer.lastTrace()!;
    expect(trace.nodes).toHaveLength(1);
    const node = trace.nodes[0]!;
    expect(node.node_name).toBe("llm:gpt-test");
    expect(node.llm_prompt).toContain('"role":"user"');
    expect(node.llm_response).toBe("calling tool");
    expect(node.tool_calls[0]).toMatchObject({ name: "lookup_refund", args: { refund_id: "REF-1" } });
    expect(node.output).toEqual({ finish_reason: "tool-calls", usage: { input_tokens: 5, output_tokens: 3, total_tokens: 8 } });
    expect(trace.metadata.usage).toBeUndefined();
  });

  it("middleware: standalone calls get their own trace (generate + stream)", async () => {
    const tracer = new CortexTracer();
    const mw = cortexopsMiddleware(tracer);
    await mw.wrapGenerate({ doGenerate: async () => ({ text: "v1 text", usage: { promptTokens: 1, completionTokens: 1 } }), model: { modelId: "m1" } });
    expect(tracer.lastTrace()).toMatchObject({ output: { output: "v1 text" }, metadata: { model: "m1", usage: { input_tokens: 1, output_tokens: 1, total_tokens: 2 } } });

    const parts = [
      { type: "text-delta", id: "1", delta: "Hel" },
      { type: "text-delta", textDelta: "lo" },
      { type: "tool-call", toolCallId: "x", toolName: "search", input: "{}" },
      { type: "finish", finishReason: { unified: "stop", raw: "end_turn" }, usage: { inputTokens: { total: 2 }, outputTokens: { total: 2 } } },
    ];
    const { stream } = await mw.wrapStream({
      doStream: async () => ({ stream: new ReadableStream({ start(c) { parts.forEach((p) => c.enqueue(p)); c.close(); } }), request: {} }),
      model: { modelId: "m2" },
    });
    expect(tracer.traces()).toHaveLength(1);
    const seen: any[] = [];
    const reader = stream.getReader();
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      seen.push(value);
    }
    expect(seen).toEqual(parts);
    const trace = tracer.lastTrace()!;
    expect(trace.output).toEqual({ output: "Hello" });
    expect(trace.metadata.usage).toEqual({ input_tokens: 2, output_tokens: 2, total_tokens: 4 });
    expect(trace.nodes[0]!.output.finish_reason).toBe("stop");
    expect(traceToolCalls(trace).map((t) => t.name)).toEqual(["search"]);
  });

  it("tool calls from wrapped generateText count toward eval tool_accuracy", async () => {
    const tracer = new CortexTracer({ sampleRate: 0 });
    const traced = wrapGenerateText(tracer, async (_options: any) => new V5Result(v5Steps));
    const ds = parseDataset({ project: "p", cases: [{ id: "c", input: "x", expected_tool_calls: ["lookup_refund"], expected_output_contains: ["approved"] }] });
    const summary = await EvalSuite.run(ds, async (inp: any) => traced({ prompt: inp.input }), { verbose: false });
    expect(summary.case_results[0]).toMatchObject({ passed: true, tool_accuracy: 100 });
    expect(tracer.traces()).toEqual([]);
  });
});

// ── LangGraph.js ─────────────────────────────────────────────────────────────

class CompiledStateGraph {
  nodes = { agent: {}, tools: {} };
  builder = {};
  calls: any[] = [];
  async invoke(input: any, config?: any) {
    this.calls.push(config);
    const cbs: any[] = Array.isArray(config?.callbacks) ? config.callbacks : [];
    const emit = (method: string, ...args: any[]) => cbs.forEach((cb) => cb[method]?.(...args));
    emit("handleChainStart", {}, input, "run-start", "root", [], { langgraph_node: "__start__" }, undefined, "__start__");
    emit("handleChainEnd", input, "run-start");
    emit("handleChainStart", {}, input, "run-agent", "root", [], { langgraph_node: "agent" }, undefined, "agent");
    emit("handleChainStart", {}, input, "inner", "run-agent", [], { langgraph_node: "agent" }, undefined, "RunnableSequence");
    emit("handleChainEnd", {}, "inner");
    emit("handleChainEnd", { messages: ["ai: call lookup_refund"] }, "run-agent");
    emit("handleChainStart", {}, {}, "run-tools", "root", [], { langgraph_node: "tools" }, undefined, "tools");
    emit("handleToolStart", { name: "ignored" }, '{"refund_id":"REF-8821"}', "tool-1", "run-tools", [], { langgraph_node: "tools" }, "lookup_refund");
    await sleep(2);
    emit("handleToolEnd", { content: "approved", tool_call_id: "x" }, "tool-1");
    emit("handleToolStart", { id: ["langchain", "tools", "send_email"] }, "plain text", "tool-2", "run-tools", [], { langgraph_node: "tools" });
    emit("handleToolError", new Error("smtp down"), "tool-2");
    emit("handleChainEnd", { messages: ["tool: approved"] }, "run-tools");
    if (input.fail) throw new Error("graph failed");
    return { messages: ["done"], output: "Refund approved" };
  }
  async stream(input: any, config?: any) {
    this.calls.push(config);
    async function* gen(graph: CompiledStateGraph) {
      await graph.invoke(input, config);
      yield { agent: { messages: ["a"] } };
      yield { tools: { messages: ["b"] } };
    }
    const iterable = gen(this);
    return Object.assign(iterable, { cancel: () => "cancelled" });
  }
  getGraph() {
    return {};
  }
}

describe("LangGraph.js", () => {
  it("is detected and traced via tracer.wrap(): nodes and tool calls from callbacks", async () => {
    const tracer = new CortexTracer();
    const graph = new CompiledStateGraph();
    expect(detectFramework(graph)).toBe("langgraph");
    const wrapped = tracer.wrap(graph);
    const userCb = { handleChainStart: vi.fn() };
    const out = await wrapped.invoke({ input: "Refund REF-8821?" }, { callbacks: [userCb], configurable: { thread_id: "1" } });
    expect(out).toEqual({ messages: ["done"], output: "Refund approved" });
    expect(userCb.handleChainStart).toHaveBeenCalled();
    expect(graph.calls[0].configurable).toEqual({ thread_id: "1" });
    expect(graph.calls[0].callbacks).toHaveLength(2);

    const trace = tracer.lastTrace()!;
    expect(trace.metadata.framework).toBe("langgraph");
    expect(trace.input).toEqual({ input: "Refund REF-8821?" });
    expect(trace.output).toEqual({ messages: ["done"], output: "Refund approved" });
    expect(trace.nodes.map((n) => n.node_name)).toEqual(["agent", "tools"]);
    expect(trace.nodes[0]!.output).toEqual({ messages: ["ai: call lookup_refund"] });
    expect(trace.nodes[1]!.tool_calls).toMatchObject([
      { name: "lookup_refund", args: { refund_id: "REF-8821" }, result: "approved", status: "success" },
      { name: "send_email", args: { input: "plain text" }, status: "error", error: "smtp down" },
    ]);
    expect(trace.nodes[1]!.tool_calls[0]!.latency_ms).toBeGreaterThan(0);
    expect(wrapped.getGraph()).toEqual({});
  });

  it("records graph failures", async () => {
    const tracer = new CortexTracer();
    const wrapped = wrapLangGraph(tracer, new CompiledStateGraph());
    await expect(wrapped.invoke({ fail: true })).rejects.toThrow("graph failed");
    expect(tracer.lastTrace()).toMatchObject({ status: "failed", failure_detail: "graph failed" });
    expect(tracer.lastTrace()!.nodes).toHaveLength(2);
  });

  it("traces stream() until the iterator completes and keeps stream methods", async () => {
    const tracer = new CortexTracer();
    const wrapped = wrapLangGraph(tracer, new CompiledStateGraph());
    const stream: any = await wrapped.stream({ input: "x" }, { streamMode: "updates" });
    expect(stream.cancel()).toBe("cancelled");
    const chunks = [];
    for await (const chunk of stream) chunks.push(chunk);
    expect(chunks).toHaveLength(2);
    const trace = tracer.lastTrace()!;
    expect(trace.status).toBe("completed");
    expect(trace.output).toEqual({ tools: { messages: ["b"] } });
    expect(traceToolCalls(trace).map((t) => t.name)).toEqual(["lookup_refund", "send_email"]);
  });

  it("finalizes when the consumer stops early", async () => {
    const tracer = new CortexTracer();
    const stream: any = await wrapLangGraph(tracer, new CompiledStateGraph()).stream({ input: "x" });
    for await (const _chunk of stream) break;
    expect(tracer.lastTrace()).toMatchObject({ status: "completed", output: { agent: { messages: ["a"] } } });
  });

  it("leaves CallbackManager configs untouched", async () => {
    const tracer = new CortexTracer();
    const graph = new CompiledStateGraph();
    const manager = { handlers: [] };
    await wrapLangGraph(tracer, graph).invoke({}, { callbacks: manager });
    expect(graph.calls[0].callbacks).toBe(manager);
    expect(tracer.lastTrace()!.status).toBe("completed");
  });
});

// ── OpenAI Agents SDK ────────────────────────────────────────────────────────

class Agent {
  handoffs: unknown[] = [];
  tools: unknown[] = [];
  constructor(public name: string) {}
  asTool() {
    return {};
  }
}

function runResult(agent: Agent) {
  return {
    finalOutput: "Refund REF-8821 approved",
    lastAgent: agent,
    newItems: [
      { type: "message_output_item", rawItem: {} },
      { type: "tool_call_item", rawItem: { type: "function_call", name: "lookup_refund", callId: "call_1", arguments: '{"refund_id":"REF-8821"}' } },
      { type: "tool_call_output_item", rawItem: { type: "function_call_result", callId: "call_1" }, output: "approved" },
      { type: "handoff_call_item", rawItem: { type: "function_call", name: "transfer_to_billing", callId: "call_2", arguments: "{}" } },
    ],
    rawResponses: [{ usage: { inputTokens: 10, outputTokens: 4, totalTokens: 14 } }, { usage: { inputTokens: 5, outputTokens: 1, totalTokens: 6 } }],
  };
}

describe("OpenAI Agents SDK", () => {
  it("wrapOpenAIAgentsRun traces tool calls, handoffs, usage and output", async () => {
    const tracer = new CortexTracer();
    const agent = new Agent("refund-agent");
    const run = vi.fn(async (a: Agent, _input: string, _options?: any) => runResult(a));
    const tracedRun = wrapOpenAIAgentsRun(tracer, run);
    const result = await tracedRun(agent, "Refund REF-8821", { maxTurns: 3 });
    expect(result.finalOutput).toBe("Refund REF-8821 approved");
    expect(run).toHaveBeenCalledWith(agent, "Refund REF-8821", { maxTurns: 3 });
    const trace = tracer.lastTrace()!;
    expect(trace.input).toEqual({ input: "Refund REF-8821", agent: "refund-agent" });
    expect(trace.output).toEqual({ output: "Refund REF-8821 approved", last_agent: "refund-agent" });
    expect(trace.metadata).toMatchObject({ framework: "openai_agents", agent: "refund-agent", usage: { input_tokens: 15, output_tokens: 5, total_tokens: 20 } });
    expect(traceToolCalls(trace)).toMatchObject([
      { name: "lookup_refund", args: { refund_id: "REF-8821" }, result: "approved" },
      { name: "transfer_to_billing", args: {}, result: null },
    ]);
  });

  it("streaming runs finalize when result.completed resolves", async () => {
    const tracer = new CortexTracer();
    const agent = new Agent("streamer");
    let finish!: () => void;
    const completed = new Promise<void>((r) => (finish = r));
    const tracedRun = wrapOpenAIAgentsRun(tracer, async (a: Agent, _input: string, _options?: any) => ({ ...runResult(a), completed }));
    const result = await tracedRun(agent, "hi", { stream: true });
    expect(result.completed).toBe(completed);
    expect(tracer.lastTrace()).toBeUndefined();
    finish();
    await sleep(1);
    expect(tracer.lastTrace()).toMatchObject({ status: "completed", output: { output: "Refund REF-8821 approved" } });
  });

  it("records run failures", async () => {
    const tracer = new CortexTracer();
    const tracedRun = wrapOpenAIAgentsRun(tracer, async (_agent: Agent, _input: string) => {
      throw new Error("MaxTurnsExceeded");
    });
    await expect(tracedRun(new Agent("a"), "x")).rejects.toThrow("MaxTurnsExceeded");
    expect(tracer.lastTrace()).toMatchObject({ status: "failed", failure_detail: "MaxTurnsExceeded" });
  });

  it("wrapOpenAIAgent / tracer.wrap(agent) expose .run() and keep agent fields", async () => {
    const tracer = new CortexTracer();
    const agent = new Agent("refund-agent");
    expect(detectFramework(agent)).toBe("openai_agents");
    const wrapped = wrapOpenAIAgent(tracer, agent, { run: async (a: Agent) => runResult(a) });
    expect(wrapped.name).toBe("refund-agent");
    expect((await wrapped.run("x")).finalOutput).toContain("approved");
    expect(tracer.lastTrace()!.metadata.framework).toBe("openai_agents");

    const auto = tracer.wrap(agent) as Agent & { run(input: string): Promise<unknown> };
    await expect(auto.run("x")).rejects.toThrow(/@openai\/agents/);
  });
});

// ── Mastra ───────────────────────────────────────────────────────────────────

class MastraAgent {
  name = "support-agent";
  model = { modelId: "gpt-4o" };
  getInstructions() {
    return "be helpful";
  }
  async generate(_messages: unknown, _options?: unknown) {
    return {
      text: "Your refund is approved",
      finishReason: "stop",
      usage: { promptTokens: 9, completionTokens: 3, totalTokens: 12 },
      toolCalls: [{ type: "tool-call", payload: { toolCallId: "t1", toolName: "lookup_refund", args: { id: "REF-1" } } }],
      toolResults: [{ type: "tool-result", payload: { toolCallId: "t1", toolName: "lookup_refund", result: { status: "approved" } } }],
    };
  }
  async stream(_messages: unknown, options?: any) {
    setTimeout(() => void options?.onFinish?.({ text: "streamed answer", steps: [], usage: { inputTokens: 1, outputTokens: 1, totalTokens: 2 } }), 2);
    return { textStream: "..." };
  }
}

describe("Mastra", () => {
  it("is detected and traces generate() (vNext payload tool calls)", async () => {
    const tracer = new CortexTracer();
    const agent = new MastraAgent();
    expect(detectFramework(agent)).toBe("mastra");
    const wrapped = tracer.wrap(agent);
    const res = await wrapped.generate("Refund REF-1?");
    expect(res.text).toBe("Your refund is approved");
    expect(wrapped.getInstructions()).toBe("be helpful");
    const trace = tracer.lastTrace()!;
    expect(trace.input).toEqual({ input: "Refund REF-1?", agent: "support-agent" });
    expect(trace.output).toEqual({ output: "Your refund is approved", finish_reason: "stop" });
    expect(trace.metadata).toMatchObject({ framework: "mastra", model: "gpt-4o", usage: { total_tokens: 12 } });
    expect(traceToolCalls(trace)).toMatchObject([{ name: "lookup_refund", args: { id: "REF-1" }, result: { status: "approved" } }]);
  });

  it("traces stream() via onFinish", async () => {
    const tracer = new CortexTracer();
    const userFinish = vi.fn();
    const wrapped = wrapMastraAgent(tracer, new MastraAgent());
    await wrapped.stream!([{ role: "user", content: "hi" }], { onFinish: userFinish });
    await sleep(10);
    expect(userFinish).toHaveBeenCalledOnce();
    expect(tracer.lastTrace()).toMatchObject({ output: { output: "streamed answer" }, metadata: { framework: "mastra" } });
  });
});

describe("detectFramework", () => {
  it("classifies common shapes", () => {
    expect(detectFramework(function generateText() {})).toBe("vercel_ai_generate");
    expect(detectFramework(function streamText() {})).toBe("vercel_ai_stream");
    expect(detectFramework(() => 1)).toBe("generic");
    expect(detectFramework({ invoke() {} })).toBe("invoke");
    expect(detectFramework({})).toBe("generic");
    expect(detectFramework(null)).toBe("generic");
  });

  it("tracer.wrap dispatches Vercel AI functions by name", async () => {
    const tracer = new CortexTracer();
    const fn = async () => new V5Result(v5Steps);
    Object.defineProperty(fn, "name", { value: "generateText2" });
    const wrapped = tracer.wrap(fn);
    await wrapped();
    expect(tracer.lastTrace()!.metadata.framework).toBe("vercel_ai");
  });
});
