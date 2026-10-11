import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { CortexTracer, RunStatus, traceToolCalls } from "../src/index.js";
import { isolateEnv, loadParity, mockFetch, jsonResponse, sleep } from "./helpers.js";

let home: string;
beforeEach(() => {
  home = isolateEnv();
});

const ok = (inp: Record<string, unknown>) => ({ output: "ok", echo: inp });
const boom = (_input?: unknown) => {
  throw new Error("agent exploded");
};

describe("configuration (mirrors sdk/tests/test_config.py, test_sampling.py)", () => {
  it("uses Python defaults", () => {
    const t = new CortexTracer();
    expect(t.project).toBe("default");
    expect(t.environment).toBe("development");
    expect(t.apiUrl).toBe("https://api.getcortexops.com");
    expect(t.sampleRate).toBe(1.0);
    expect(t.sampleErrors).toBe(true);
    expect(t.isHosted).toBe(false);
  });

  it("resolves argument > env", () => {
    vi.stubEnv("CORTEXOPS_PROJECT", "env-proj");
    vi.stubEnv("CORTEXOPS_ENVIRONMENT", "staging");
    vi.stubEnv("CORTEXOPS_API_URL", "http://localhost:8000/");
    vi.stubEnv("CORTEXOPS_API_KEY", "cxo-env");
    vi.stubEnv("CORTEXOPS_SAMPLE_RATE", "0.1");
    const fromEnv = new CortexTracer();
    expect([fromEnv.project, fromEnv.environment, fromEnv.apiUrl, fromEnv.apiKey, fromEnv.sampleRate]).toEqual([
      "env-proj",
      "staging",
      "http://localhost:8000",
      "cxo-env",
      0.1,
    ]);
    const explicit = new CortexTracer({
      project: "p",
      environment: "production",
      apiUrl: "https://example.test",
      apiKey: "cxo-arg",
      sampleRate: 0.5,
    });
    expect([explicit.project, explicit.environment, explicit.apiUrl, explicit.apiKey, explicit.sampleRate]).toEqual([
      "p",
      "production",
      "https://example.test",
      "cxo-arg",
      0.5,
    ]);
  });

  it("reads the API key from ~/.cortexops/credentials as a last resort", () => {
    mkdirSync(join(home, ".cortexops"));
    writeFileSync(join(home, ".cortexops", "credentials"), JSON.stringify({ api_key: "cxo-file", project: "x" }));
    expect(new CortexTracer().apiKey).toBe("cxo-file");
    vi.stubEnv("CORTEXOPS_API_KEY", "cxo-env");
    expect(new CortexTracer().apiKey).toBe("cxo-env");
  });

  it.each(["abc", "1.5", "-0.1", "nan", "0x1"])("rejects invalid CORTEXOPS_SAMPLE_RATE=%s", (value) => {
    vi.stubEnv("CORTEXOPS_SAMPLE_RATE", value);
    expect(() => new CortexTracer({ project: "p" })).toThrow(RangeError);
  });

  it("rejects out-of-range explicit sample rates", () => {
    expect(() => new CortexTracer({ sampleRate: 2 })).toThrow(RangeError);
    expect(() => new CortexTracer({ sampleRate: -1 })).toThrow(RangeError);
  });
});

describe("wrap()", () => {
  it("traces sync functions and returns their value unchanged", () => {
    const t = new CortexTracer({ project: "p" });
    const result = t.wrap(ok)({ q: 1 });
    expect(result).toEqual({ output: "ok", echo: { q: 1 } });
    const trace = t.lastTrace()!;
    expect(trace.status).toBe(RunStatus.COMPLETED);
    expect(trace.input).toEqual({ q: 1 });
    expect(trace.output).toEqual({ output: "ok", echo: { q: 1 } });
    expect(trace.project).toBe("p");
    expect(trace.metadata).toEqual({ sample_rate: 1.0, sampled: true, framework: "generic" });
    expect(trace.total_latency_ms).toBeGreaterThanOrEqual(0);
  });

  it("traces async functions and measures latency", async () => {
    const t = new CortexTracer({ project: "p" });
    const agent = t.wrap(async (inp: { input: string }) => {
      await sleep(30);
      return `echo ${inp.input}`;
    });
    expect(await agent({ input: "hi" })).toBe("echo hi");
    const trace = t.lastTrace()!;
    expect(trace.output).toEqual({ result: "echo hi" });
    expect(trace.total_latency_ms).toBeGreaterThanOrEqual(25);
  });

  it("records failures and re-throws (sync and async)", async () => {
    const t = new CortexTracer({ project: "p" });
    expect(() => t.wrap(boom)()).toThrow("agent exploded");
    expect(t.lastTrace()).toMatchObject({ status: "failed", failure_kind: "unknown", failure_detail: "agent exploded" });
    await expect(
      t.wrap(async () => {
        throw new TypeError("async boom");
      })(),
    ).rejects.toThrow("async boom");
    expect(t.lastTrace()).toMatchObject({ status: "failed", failure_detail: "async boom" });
    expect(t.traces()).toHaveLength(2);
  });

  it("normalizes inputs: single object, primitive, multiple args", () => {
    const t = new CortexTracer();
    t.wrap((s: string) => s)("hello");
    expect(t.lastTrace()!.input).toEqual({ input: "hello" });
    t.wrap((a: number, b: number) => a + b)(1, 2);
    expect(t.lastTrace()!.input).toEqual({ args: [1, 2] });
    expect(t.lastTrace()!.output).toEqual({ result: 3 });
  });

  it("preserves `this` for methods", () => {
    const t = new CortexTracer();
    const obj = { base: 10, add(n: number) { return this.base + n; } };
    obj.add = t.wrap(obj.add);
    expect(obj.add(5)).toBe(15);
  });

  it("wraps objects with .invoke() and keeps other members", async () => {
    const t = new CortexTracer();
    const agent = { name: "a", invoke: async (inp: { input: string }) => ({ output: inp.input.toUpperCase() }), other: () => 42 };
    const wrapped = t.wrap(agent);
    expect(await wrapped.invoke({ input: "x" })).toEqual({ output: "X" });
    expect(wrapped.other()).toBe(42);
    expect(wrapped.name).toBe("a");
    expect(t.lastTrace()!.output).toEqual({ output: "X" });
  });

  it("serializes circular / exotic outputs safely", () => {
    const t = new CortexTracer();
    const out: any = { big: 10n, when: new Date(0), fn: () => 1 };
    out.self = out;
    t.wrap(() => out)();
    expect(t.lastTrace()!.output).toEqual({ big: "10", when: "1970-01-01T00:00:00.000Z", self: "[Circular]" });
  });

  it("rejects values it cannot wrap", () => {
    expect(() => new CortexTracer().wrap(42 as any)).toThrow(TypeError);
  });

  it("bounds the in-memory store", () => {
    const t = new CortexTracer({ maxLocalTraces: 3 });
    const f = t.wrap((n: number) => n);
    for (let i = 0; i < 5; i++) f(i);
    expect(t.traces().map((tr) => tr.output.result)).toEqual([2, 3, 4]);
    t.clear();
    expect(t.lastTrace()).toBeUndefined();
    const noStore = new CortexTracer({ localStore: false });
    noStore.wrap(() => 1)();
    expect(noStore.traces()).toEqual([]);
  });
});

describe("sampling (port of sdk/tests/test_sampling.py)", () => {
  it("drops unsampled successes", () => {
    const t = new CortexTracer({ project: "p", sampleRate: 0.0 });
    expect(t.wrap(ok)({ q: 1 })).toEqual({ output: "ok", echo: { q: 1 } });
    expect(t.traces()).toEqual([]);
  });

  it("captures unsampled errors with captured_reason", () => {
    const t = new CortexTracer({ project: "p", sampleRate: 0.0 });
    t.setPrompt("refund-system", "v2");
    expect(() => t.wrap(boom)({ q: 1 })).toThrow("agent exploded");
    const trace = t.lastTrace()!;
    expect(trace.status).toBe(RunStatus.FAILED);
    expect(trace.failure_detail).toBe("agent exploded");
    expect(trace.metadata).toEqual({ sample_rate: 0.0, sampled: false, captured_reason: "error", framework: "generic" });
    expect(trace.prompt_version).toBe("v2");
    expect(trace.input).toEqual({ q: 1 });
  });

  it("captures unsampled async errors", async () => {
    const t = new CortexTracer({ sampleRate: 0.0 });
    await expect(t.wrap(async () => Promise.reject(new Error("late")))()).rejects.toThrow("late");
    expect(t.lastTrace()!.metadata.captured_reason).toBe("error");
  });

  it("flushes unsampled errors when hosted", async () => {
    const { fetch, requests } = mockFetch();
    const t = new CortexTracer({ project: "p", apiKey: "cxo-test", sampleRate: 0.0, fetch });
    expect(() => t.wrap(boom)()).toThrow();
    await t.flush();
    expect(requests).toHaveLength(1);
    expect(requests[0]!.body.status).toBe("failed");
  });

  it("drops errors when sampleErrors is false", () => {
    const t = new CortexTracer({ project: "p", sampleRate: 0.0, sampleErrors: false });
    expect(() => t.wrap(boom)()).toThrow();
    expect(t.traces()).toEqual([]);
  });

  it("samples roughly at the configured rate", () => {
    const t = new CortexTracer({ sampleRate: 0.25 });
    const values = [0.1, 0.3, 0.2, 0.9];
    let i = 0;
    vi.spyOn(Math, "random").mockImplementation(() => values[i++ % values.length]!);
    const f = t.wrap(() => "x");
    for (let k = 0; k < 4; k++) f();
    expect(t.traces()).toHaveLength(2);
  });
});

describe("traceNode / recordToolCall", () => {
  it("attaches nodes and tool calls to the active trace", async () => {
    const t = new CortexTracer();
    const agent = t.wrap(async () => {
      await t.traceNode("plan", async (node) => {
        node.llm_prompt = "think";
        await sleep(5);
        t.recordToolCall("lookup_refund", { args: { refund_id: "REF-1" }, result: { status: "approved" }, latencyMs: 3 });
      });
      t.traceNode("act", () => {
        t.recordToolCall("send_email", { error: "smtp down" });
      });
      return { output: "done" };
    });
    await agent();
    const trace = t.lastTrace()!;
    expect(trace.nodes.map((n) => n.node_name)).toEqual(["plan", "act"]);
    expect(trace.nodes[0]!.llm_prompt).toBe("think");
    expect(trace.nodes[0]!.latency_ms).toBeGreaterThan(0);
    expect(trace.nodes[0]!.tool_calls[0]).toMatchObject({
      name: "lookup_refund",
      args: { refund_id: "REF-1" },
      result: { status: "approved" },
      status: "success",
      latency_ms: 3,
      error: null,
    });
    expect(trace.nodes[1]!.tool_calls[0]).toMatchObject({ name: "send_email", status: "error", error: "smtp down" });
    expect(traceToolCalls(trace).map((tc) => tc.name)).toEqual(["lookup_refund", "send_email"]);
  });

  it("creates an implicit node for tool calls recorded outside any node", () => {
    const t = new CortexTracer();
    t.wrap(() => t.recordToolCall("x"))();
    expect(t.lastTrace()!.nodes).toHaveLength(1);
    expect(t.lastTrace()!.nodes[0]!.node_name).toBe("agent");
  });

  it("is a no-op outside a trace", async () => {
    const t = new CortexTracer();
    expect(t.traceNode("n", () => 7)).toBe(7);
    expect(await t.traceNode("n", async () => 8)).toBe(8);
    expect(t.recordToolCall("x").name).toBe("x");
    expect(t.traces()).toEqual([]);
    expect(t.currentTrace()).toBeUndefined();
  });

  it("keeps concurrent runs isolated", async () => {
    const t = new CortexTracer();
    const agent = t.wrap(async (inp: { id: number }) => {
      for (let i = 0; i < 3; i++) {
        await sleep(Math.random() * 10);
        t.recordToolCall(`tool_${inp.id}`);
      }
      return { output: inp.id };
    });
    await Promise.all([1, 2, 3, 4, 5].map((id) => agent({ id })));
    for (const trace of t.traces()) {
      const id = trace.input.id;
      expect(traceToolCalls(trace).map((tc) => tc.name)).toEqual([`tool_${id}`, `tool_${id}`, `tool_${id}`]);
    }
  });

  it("supports manual runs via startTrace()", () => {
    const t = new CortexTracer();
    const run = t.startTrace({ q: 1 }, { framework: "custom", caseId: "c1" });
    run.run(() => t.traceNode("n", () => t.recordToolCall("tool")));
    run.addUsage({ input_tokens: 3, output_tokens: 4, total_tokens: 7 });
    run.addUsage({ input_tokens: 1, output_tokens: 1, total_tokens: 2 });
    run.end({ output: "x" });
    run.end({ output: "ignored" });
    const trace = t.lastTrace()!;
    expect(trace.case_id).toBe("c1");
    expect(trace.metadata).toMatchObject({ framework: "custom", usage: { input_tokens: 4, output_tokens: 5, total_tokens: 9 } });
    expect(trace.output).toEqual({ output: "x" });
    expect(t.traces()).toHaveLength(1);
  });
});

describe("prompt tracking (port of sdk/tests/test_prompt_tracking.py)", () => {
  it("leaves traces untagged by default", () => {
    const t = new CortexTracer();
    t.wrap(ok)({});
    expect(t.lastTrace()).toMatchObject({ prompt_name: null, prompt_version: null });
    expect(t.prompt).toBeNull();
  });

  it("tags subsequent traces, stringifies numeric versions, and clears", () => {
    const t = new CortexTracer();
    t.setPrompt("  refund-system ", 3);
    expect(t.prompt).toEqual({ name: "refund-system", version: "3" });
    t.wrap(ok)({});
    expect(t.lastTrace()).toMatchObject({ prompt_name: "refund-system", prompt_version: "3" });
    t.clearPrompt();
    t.wrap(ok)({});
    expect(t.lastTrace()).toMatchObject({ prompt_name: null, prompt_version: null });
  });

  it("usePrompt restores the previous prompt", () => {
    const t = new CortexTracer();
    t.setPrompt("base", "v1");
    t.usePrompt("refund-system", "v4", () => {
      expect(t.prompt).toEqual({ name: "refund-system", version: "v4" });
      t.wrap(ok)({});
    });
    expect(t.lastTrace()!.prompt_version).toBe("v4");
    expect(t.prompt).toEqual({ name: "base", version: "v1" });
  });

  it.each([
    ["", "v1"],
    ["   ", "v1"],
    ["name", ""],
    ["name", "  "],
  ])("rejects blank labels (%j, %j)", (name, version) => {
    expect(() => new CortexTracer().setPrompt(name, version)).toThrow();
  });

  it("enforces API length limits (255 / 64)", () => {
    const t = new CortexTracer();
    expect(() => t.setPrompt("n".repeat(256), "v")).toThrow();
    expect(() => t.setPrompt("n", "v".repeat(65))).toThrow();
    t.setPrompt("n".repeat(255), "v".repeat(64));
    expect(t.prompt!.version).toHaveLength(64);
  });

  it("isolates prompts across concurrent async contexts", async () => {
    const t = new CortexTracer();
    t.setPrompt("default-prompt", "v0");
    const agent = t.wrap(async (inp: { v: string }) => {
      await sleep(Math.random() * 15);
      return { output: inp.v };
    });
    const versions = ["v1", "v2", "v3", "v4", "v5", "v6"];
    await Promise.all(
      versions.map((v) =>
        t.usePrompt("refund-system", v, async () => {
          await sleep(Math.random() * 10);
          expect(t.prompt!.version).toBe(v);
          await agent({ v });
          t.setPrompt("refund-system", `${v}-b`);
          await sleep(Math.random() * 10);
          await agent({ v: `${v}-b` });
        }),
      ),
    );
    await agent({ v: "outside" });
    for (const trace of t.traces()) {
      const expected = trace.output.output === "outside" ? "v0" : trace.output.output;
      expect(trace.prompt_version).toBe(expected);
    }
    expect(t.traces()).toHaveLength(13);
    expect(t.prompt).toEqual({ name: "default-prompt", version: "v0" });
  });
});

describe("upload", () => {
  it("sends a TraceIngest-compatible payload with X-API-Key", async () => {
    const parity = loadParity();
    const { fetch, requests } = mockFetch();
    const t = new CortexTracer({ project: "payments-agent", apiKey: "cxo-test", apiUrl: "http://api.test/", environment: "ci", fetch });
    t.setPrompt("refund-system", "v3");
    await t.wrap(async (_input: unknown) => {
      t.traceNode("router", () => t.recordToolCall("lookup_refund", { args: { refund_id: "REF-8821" }, result: { ok: true } }));
      return { output: "approved" };
    })({ input: "Refund REF-8821" });
    await t.flush();

    expect(requests).toHaveLength(1);
    const req = requests[0]!;
    expect(req.url).toBe("http://api.test/v1/traces");
    expect(req.method).toBe("POST");
    expect(req.headers["x-api-key"]).toBe("cxo-test");
    expect(req.headers["content-type"]).toBe("application/json");
    expect(req.headers["idempotency-key"]).toBe(t.lastTrace()!.trace_id);

    const body = req.body;
    // Same fields as the Python SDK's Trace.model_dump(), a superset of the backend TraceIngest
    expect(Object.keys(body).sort()).toEqual([...parity.schemas.sdk_trace].sort());
    for (const [field, spec] of Object.entries<any>(parity.schemas.TraceIngest)) {
      if (spec.required) expect(body).toHaveProperty(field);
      expect(field in body).toBe(true);
    }
    expect(Object.keys(body.nodes[0]).sort()).toEqual([...parity.schemas.sdk_node].sort());
    expect(Object.keys(body.nodes[0].tool_calls[0]).sort()).toEqual([...parity.schemas.sdk_tool_call].sort());
    expect(body).toMatchObject({
      project: "payments-agent",
      status: "completed",
      environment: "ci",
      prompt_name: "refund-system",
      prompt_version: "v3",
      input: { input: "Refund REF-8821" },
      output: { output: "approved" },
      metadata: { sample_rate: 1, sampled: true },
      failure_kind: null,
      case_id: null,
    });
    expect(typeof body.total_latency_ms).toBe("number");
  });

  it("does not upload without an API key", async () => {
    const { fetch, requests } = mockFetch();
    const t = new CortexTracer({ fetch });
    t.wrap(ok)({});
    await t.flush();
    expect(requests).toHaveLength(0);
  });

  it("never blocks the agent and never throws into user code", async () => {
    let release!: () => void;
    const gate = new Promise<void>((r) => (release = r));
    const { fetch } = mockFetch(async () => {
      await gate;
      return jsonResponse({}, 201);
    });
    const t = new CortexTracer({ apiKey: "cxo", fetch });
    const t0 = performance.now();
    expect(t.wrap(ok)({})).toBeTruthy();
    expect(performance.now() - t0).toBeLessThan(50);
    expect(t.pendingUploads).toBe(1);
    release();
    await t.flush();
    expect(t.pendingUploads).toBe(0);
  });

  it("swallows network errors, HTTP errors and timeouts, reporting via onFlushError", async () => {
    const errors: string[] = [];
    const onFlushError = (err: unknown) => errors.push(String((err as Error).message ?? err));
    const failing = new CortexTracer({ apiKey: "cxo", fetch: async () => Promise.reject(new Error("ECONNREFUSED")), onFlushError });
    failing.wrap(ok)({});
    const rejected = new CortexTracer({ apiKey: "cxo", fetch: async () => jsonResponse({ detail: "quota" }, 429), onFlushError });
    rejected.wrap(ok)({});
    const hanging = new CortexTracer({
      apiKey: "cxo",
      flushTimeoutMs: 50,
      onFlushError,
      fetch: (_url, init) =>
        new Promise((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () => reject(init.signal!.reason));
        }),
    });
    hanging.wrap(ok)({});
    const throwingHook = new CortexTracer({
      apiKey: "cxo",
      fetch: async () => Promise.reject(new Error("x")),
      onFlushError: () => {
        throw new Error("hook bug");
      },
    });
    throwingHook.wrap(ok)({});
    const t0 = performance.now();
    await Promise.all([failing.flush(), rejected.flush(), hanging.flush(), throwingHook.flush()]);
    expect(performance.now() - t0).toBeLessThan(2000);
    expect(errors).toHaveLength(3);
    expect(errors.join(" ")).toContain("ECONNREFUSED");
    expect(errors.join(" ")).toContain("HTTP 429");
  });

  it("shutdown() flushes and stops further uploads", async () => {
    const { fetch, requests } = mockFetch();
    const t = new CortexTracer({ apiKey: "cxo", fetch });
    t.wrap(ok)({});
    await t.shutdown();
    expect(requests).toHaveLength(1);
    t.wrap(ok)({});
    await t.flush();
    expect(requests).toHaveLength(1);
  });
});
