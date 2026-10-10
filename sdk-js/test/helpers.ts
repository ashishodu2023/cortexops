import { mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { vi } from "vitest";
import { createNode, createToolCall, createTrace, type Trace } from "../src/models.js";

export const FIXTURES = fileURLToPath(new URL("./fixtures", import.meta.url));
export const REPO_ROOT = join(FIXTURES, "..", "..", "..");
export const GOLDEN_YAML = join(REPO_ROOT, "examples", "langgraph_payments", "golden_v1.yaml");
export const PAYMENTS_AGENT = join(REPO_ROOT, "sdk-js", "examples", "payments-agent.mjs");

export function loadParity(): any {
  return JSON.parse(readFileSync(join(FIXTURES, "python-parity.json"), "utf8"));
}

/** Port of sdk/tests/helpers.py `make_trace`. */
export function makeTrace(output: Record<string, unknown> = {}, toolCalls: string[] = [], latencyMs = 100): Trace {
  return createTrace({
    project: "test",
    total_latency_ms: latencyMs,
    output,
    nodes: [
      createNode({
        node_id: "n1",
        node_name: "agent",
        output,
        tool_calls: toolCalls.map((name) => createToolCall({ name })),
        latency_ms: latencyMs,
      }),
    ],
  });
}

export interface RecordedRequest {
  url: string;
  method: string;
  headers: Record<string, string>;
  body: any;
}

/** A fetch mock that records requests and answers with `respond` (default 201 + {}). */
export function mockFetch(respond: (req: RecordedRequest) => Response | Promise<Response> = () => jsonResponse({}, 201)) {
  const requests: RecordedRequest[] = [];
  const fn = vi.fn(async (url: string, init: RequestInit = {}) => {
    const headers = Object.fromEntries(new Headers(init.headers).entries());
    const req: RecordedRequest = {
      url: String(url),
      method: init.method ?? "GET",
      headers,
      body: typeof init.body === "string" ? JSON.parse(init.body) : init.body,
    };
    requests.push(req);
    return respond(req);
  });
  return { fetch: fn, requests };
}

export function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}

/** Isolated HOME so ~/.cortexops/credentials on the dev machine never leaks into tests. */
export function isolateEnv(): string {
  const home = mkdtempSync(join(tmpdir(), "cortexops-js-home-"));
  vi.stubEnv("HOME", home);
  vi.stubEnv("USERPROFILE", home);
  for (const name of [
    "CORTEXOPS_API_KEY",
    "CORTEXOPS_API_URL",
    "CORTEXOPS_PROJECT",
    "CORTEXOPS_ENVIRONMENT",
    "CORTEXOPS_SAMPLE_RATE",
    "GITHUB_STEP_SUMMARY",
    "OPENAI_API_KEY",
  ]) {
    vi.stubEnv(name, "");
  }
  return home;
}

export const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));
