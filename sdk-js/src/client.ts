import { resolveApiKey, resolveApiUrl } from "./config.js";
import { toJsonSafe } from "./json.js";
import { judgeUsage, type EvalSummary, type Trace } from "./models.js";
import type { FetchLike } from "./tracer.js";
import { USER_AGENT } from "./version.js";

export interface CortexClientOptions {
  /** Falls back to CORTEXOPS_API_KEY, then ~/.cortexops/credentials. Required. */
  apiKey?: string;
  /** Falls back to CORTEXOPS_API_URL, then https://api.getcortexops.com. */
  baseUrl?: string;
  /** Request timeout in milliseconds. Default 10000. */
  timeoutMs?: number;
  fetch?: FetchLike;
}

/** `TraceResponse` from the API. */
export interface TraceRecord {
  trace_id: string;
  project: string;
  case_id: string | null;
  status: string;
  total_latency_ms: number;
  failure_kind: string | null;
  failure_detail: string | null;
  environment: string;
  prompt_name: string | null;
  prompt_version: string | null;
  sampled: boolean | null;
  created_at: string;
}

/** `TraceDetailResponse` from the API. */
export interface TraceDetail extends TraceRecord {
  raw_trace: Record<string, unknown>;
}

/** `EvalSummaryResponse` from the API. */
export interface EvalRunRecord {
  run_id: string;
  project: string;
  status: string;
  dataset_version: number;
  total_cases: number;
  passed: number;
  failed: number;
  warnings: number;
  task_completion_rate: number;
  tool_accuracy: number;
  latency_p50_ms: number;
  latency_p95_ms: number;
  regressions: number;
  baseline_run_id: string | null;
  case_results: Array<Record<string, unknown>>;
  created_at: string;
  completed_at: string | null;
  /** LLM-as-judge spend; null when no judge ran or its model has no known price. */
  judge_cost_usd?: number | null;
  judge_tokens_in?: number | null;
  judge_tokens_out?: number | null;
}

export interface ListTracesOptions {
  limit?: number;
  status?: string;
  environment?: string;
  promptName?: string;
  promptVersion?: string;
  /** ISO 8601 lower bound. */
  from?: string;
  /** ISO 8601 upper bound. */
  to?: string;
}

export interface DatasetSnapshot {
  name: string;
  description?: string;
  cases?: Array<Record<string, unknown>>;
}

export interface PromptSnapshot {
  prompt_name: string;
  content: string;
  model?: string;
  temperature?: number;
  commit_message?: string;
  author?: string;
}

export class CortexApiError extends Error {
  override name = "CortexApiError";
  constructor(
    message: string,
    readonly status: number,
    readonly body: unknown,
  ) {
    super(message);
  }
}

/** Serialize an eval summary for `POST /v1/evals/ingest` (per-case traces are dropped). */
export function evalIngestPayload(
  summary: EvalSummary,
  extras: { dataset?: DatasetSnapshot; prompt?: PromptSnapshot } = {},
): Record<string, unknown> {
  const data = toJsonSafe({ ...summary, ...judgeUsage(summary) }) as Record<string, unknown>;
  data.case_results = summary.case_results.map((cr) => {
    const { trace: _trace, ...rest } = cr;
    return toJsonSafe({ ...rest, ...judgeUsage(rest) });
  });
  if (extras.dataset) data.dataset = toJsonSafe(extras.dataset);
  if (extras.prompt) data.prompt = toJsonSafe(extras.prompt);
  return data;
}

/** HTTP client for the CortexOps REST API (`X-API-Key` auth). */
export class CortexClient {
  static readonly DEFAULT_BASE_URL = "https://api.getcortexops.com";

  readonly apiKey: string;
  readonly baseUrl: string;
  readonly timeoutMs: number;
  private readonly fetchImpl: FetchLike;

  constructor(options: CortexClientOptions = {}) {
    const apiKey = resolveApiKey(options.apiKey);
    if (!apiKey) {
      throw new Error("CortexClient needs an API key: pass apiKey, set CORTEXOPS_API_KEY, or run `cortexops login`");
    }
    this.apiKey = apiKey;
    this.baseUrl = resolveApiUrl(options.baseUrl);
    this.timeoutMs = options.timeoutMs ?? 10_000;
    const f = options.fetch ?? (typeof fetch === "function" ? (fetch as FetchLike) : undefined);
    if (!f) throw new Error("No fetch implementation available (Node >= 18 required)");
    this.fetchImpl = f;
  }

  private async request<T>(method: "GET" | "POST", path: string, options: { query?: Record<string, unknown>; body?: unknown } = {}): Promise<T> {
    const url = new URL(path.replace(/^\/+/, ""), `${this.baseUrl}/`);
    for (const [key, value] of Object.entries(options.query ?? {})) {
      if (value !== undefined && value !== null) url.searchParams.set(key, String(value));
    }
    const headers: Record<string, string> = {
      "X-API-Key": this.apiKey,
      Accept: "application/json",
      "User-Agent": USER_AGENT,
    };
    if (options.body !== undefined) headers["Content-Type"] = "application/json";
    const res = await this.fetchImpl(url.toString(), {
      method,
      headers,
      body: options.body === undefined ? undefined : JSON.stringify(toJsonSafe(options.body)),
      signal: AbortSignal.timeout(this.timeoutMs),
    });
    const text = await res.text();
    let parsed: unknown = text;
    try {
      parsed = text ? JSON.parse(text) : null;
    } catch {
      // keep raw text
    }
    if (!res.ok) {
      const detail =
        parsed && typeof parsed === "object" && "detail" in parsed ? JSON.stringify((parsed as { detail: unknown }).detail) : text.slice(0, 300);
      throw new CortexApiError(`CortexOps API ${method} ${url.pathname} failed: HTTP ${res.status} ${detail}`, res.status, parsed);
    }
    return parsed as T;
  }

  /** `POST /v1/traces`. The API assigns its own `trace_id`, returned in the response. */
  pushTrace(trace: Trace): Promise<TraceRecord> {
    return this.request("POST", "/v1/traces", { body: trace });
  }

  /** `GET /v1/traces/{id}` including the stored `raw_trace`. */
  getTrace(traceId: string): Promise<TraceDetail> {
    return this.request("GET", `/v1/traces/${encodeURIComponent(traceId)}`);
  }

  /** `GET /v1/traces?project=...` */
  listTraces(project: string, options: ListTracesOptions = {}): Promise<TraceRecord[]> {
    return this.request("GET", "/v1/traces", {
      query: {
        project,
        limit: options.limit ?? 50,
        status: options.status,
        environment: options.environment,
        prompt_name: options.promptName,
        prompt_version: options.promptVersion,
        from: options.from,
        to: options.to,
      },
    });
  }

  /** `POST /v1/evals/ingest`: store a locally computed eval summary for the dashboard. */
  pushEval(summary: EvalSummary, extras: { dataset?: DatasetSnapshot; prompt?: PromptSnapshot } = {}): Promise<EvalRunRecord> {
    return this.request("POST", "/v1/evals/ingest", { body: evalIngestPayload(summary, extras) });
  }

  /** `GET /v1/evals/{run_id}` */
  getEval(runId: string): Promise<EvalRunRecord> {
    return this.request("GET", `/v1/evals/${encodeURIComponent(runId)}`);
  }

  /** `GET /v1/evals?project=...` */
  listRuns(project: string, limit = 10): Promise<EvalRunRecord[]> {
    return this.request("GET", "/v1/evals", { query: { project, limit } });
  }

  /** `GET /v1/evals/diff?a=...&b=...` */
  diff(runIdA: string, runIdB: string): Promise<Record<string, unknown>> {
    return this.request("GET", "/v1/evals/diff", { query: { a: runIdA, b: runIdB } });
  }

  /** `GET /v1/traces/quota`: usage, limits and the project bound to the key. */
  quota(): Promise<Record<string, unknown> & { project: string }> {
    return this.request("GET", "/v1/traces/quota");
  }

  /** The project bound to the current API key. */
  async projectForKey(): Promise<string> {
    return (await this.quota()).project;
  }
}
