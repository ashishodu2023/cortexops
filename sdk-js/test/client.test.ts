import { beforeEach, describe, expect, it, vi } from "vitest";
import { CortexApiError, CortexClient, EvalSuite, createTrace, evalIngestPayload } from "../src/index.js";
import { GOLDEN_YAML, isolateEnv, jsonResponse, loadParity, mockFetch } from "./helpers.js";
// @ts-expect-error -- plain ESM example without type declarations
import paymentsAgent from "../examples/payments-agent.mjs";

const parity = loadParity();

beforeEach(() => {
  isolateEnv();
});

describe("CortexClient", () => {
  it("requires an API key and resolves env defaults", () => {
    expect(() => new CortexClient()).toThrow(/API key/);
    vi.stubEnv("CORTEXOPS_API_KEY", "cxo-env");
    vi.stubEnv("CORTEXOPS_API_URL", "http://localhost:8000/");
    const c = new CortexClient();
    expect([c.apiKey, c.baseUrl]).toEqual(["cxo-env", "http://localhost:8000"]);
    expect(new CortexClient({ apiKey: "k" }).baseUrl).toBe("http://localhost:8000");
    vi.stubEnv("CORTEXOPS_API_URL", "");
    expect(new CortexClient({ apiKey: "k" }).baseUrl).toBe("https://api.getcortexops.com");
  });

  it("pushTrace / getTrace / listTraces use the documented endpoints", async () => {
    const { fetch, requests } = mockFetch((req) =>
      req.method === "POST" ? jsonResponse({ trace_id: "srv-1" }, 201) : jsonResponse(req.url.includes("/v1/traces/") ? { trace_id: "srv-1", raw_trace: {} } : []),
    );
    const client = new CortexClient({ apiKey: "cxo-k", baseUrl: "http://api.test", fetch });
    const trace = createTrace({ project: "p", output: { output: "x" } });
    expect((await client.pushTrace(trace)).trace_id).toBe("srv-1");
    await client.getTrace("srv-1");
    await client.listTraces("p", { limit: 5, promptName: "refund", status: "failed" });
    expect(requests.map((r) => `${r.method} ${r.url}`)).toEqual([
      "POST http://api.test/v1/traces",
      "GET http://api.test/v1/traces/srv-1",
      "GET http://api.test/v1/traces?project=p&limit=5&status=failed&prompt_name=refund",
    ]);
    expect(requests.every((r) => r.headers["x-api-key"] === "cxo-k")).toBe(true);
    expect(requests[0]!.body.project).toBe("p");
  });

  it("pushEval sends an EvalSummaryIngest payload without per-case traces", async () => {
    const summary = await EvalSuite.run(GOLDEN_YAML, paymentsAgent, { verbose: false });
    const payload = evalIngestPayload(summary, { dataset: { name: "golden_v1", cases: [{ id: "a" }] } });
    for (const [field, spec] of Object.entries<any>(parity.schemas.EvalSummaryIngest)) {
      if (spec.required) expect(payload).toHaveProperty(field);
    }
    const caseFields = Object.keys(parity.schemas.CaseResultIngest);
    for (const cr of payload.case_results as Array<Record<string, unknown>>) {
      expect(cr).not.toHaveProperty("trace");
      for (const f of caseFields) expect(cr).toHaveProperty(f);
    }
    expect(payload.dataset).toEqual({ name: "golden_v1", cases: [{ id: "a" }] });
    expect(Number.isInteger(payload.dataset_version)).toBe(true);
    expect(summary.case_results[0]!.trace).not.toBeNull();

    const { fetch, requests } = mockFetch(() => jsonResponse({ run_id: summary.run_id, project: "payments-agent" }, 201));
    const stored = await new CortexClient({ apiKey: "k", baseUrl: "http://api.test", fetch }).pushEval(summary);
    expect(stored.run_id).toBe(summary.run_id);
    expect(requests[0]!.url).toBe("http://api.test/v1/evals/ingest");
  });

  it("raises CortexApiError with status and detail", async () => {
    const { fetch } = mockFetch(() => jsonResponse({ detail: "Invalid API key" }, 401));
    const client = new CortexClient({ apiKey: "bad", baseUrl: "http://api.test", fetch });
    const err = await client.projectForKey().catch((e) => e);
    expect(err).toBeInstanceOf(CortexApiError);
    expect(err.status).toBe(401);
    expect(err.message).toContain("Invalid API key");
  });

  it("projectForKey, listRuns, getEval and diff", async () => {
    const { fetch, requests } = mockFetch((req) => jsonResponse(req.url.includes("quota") ? { project: "proj-a" } : {}));
    const client = new CortexClient({ apiKey: "k", baseUrl: "http://api.test", fetch });
    expect(await client.projectForKey()).toBe("proj-a");
    await client.listRuns("proj-a", 3);
    await client.getEval("r1");
    await client.diff("r1", "r2");
    expect(requests.map((r) => r.url)).toEqual([
      "http://api.test/v1/traces/quota",
      "http://api.test/v1/evals?project=proj-a&limit=3",
      "http://api.test/v1/evals/r1",
      "http://api.test/v1/evals/diff?a=r1&b=r2",
    ]);
  });
});
