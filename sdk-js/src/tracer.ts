import { AsyncLocalStorage } from "node:async_hooks";
import { captureToolCall } from "./capture.js";
import {
  resolveApiKey,
  resolveApiUrl,
  resolveEnvironment,
  resolveProject,
  resolveSampleRate,
} from "./config.js";
import { isPromiseLike, toJsonSafe, toRecord, errorMessage } from "./json.js";
import {
  FailureKind,
  RunStatus,
  ToolCallStatus,
  createNode,
  createToolCall,
  createTrace,
  type ToolCall,
  type Trace,
  type TraceNode,
} from "./models.js";
import { USER_AGENT } from "./version.js";
import { wrapAgent } from "./integrations/index.js";

// Hosted API limits on TraceIngest.prompt_name / prompt_version; longer labels get the trace rejected.
const MAX_PROMPT_NAME = 255;
const MAX_PROMPT_VERSION = 64;

export type FetchLike = (input: string, init?: RequestInit) => Promise<Response>;

export interface CortexTracerOptions {
  /** Project name. Falls back to CORTEXOPS_PROJECT, then "default". */
  project?: string;
  /** API key. Falls back to CORTEXOPS_API_KEY, then ~/.cortexops/credentials. Without a key, traces stay local. */
  apiKey?: string;
  /** API base URL. Falls back to CORTEXOPS_API_URL, then https://api.getcortexops.com. */
  apiUrl?: string;
  /** Environment label. Falls back to CORTEXOPS_ENVIRONMENT, then "development". */
  environment?: string;
  /** Head-sampling rate in [0, 1]. Falls back to CORTEXOPS_SAMPLE_RATE, then 1.0. */
  sampleRate?: number;
  /** Capture failed runs even when they were not sampled. Default true. */
  sampleErrors?: boolean;
  /** Keep finished traces in memory for `lastTrace()` / `traces()`. Default true. */
  localStore?: boolean;
  /** Maximum traces kept in memory (oldest dropped first). Default 1000. */
  maxLocalTraces?: number;
  /** Per-upload timeout in milliseconds. Default 2000. */
  flushTimeoutMs?: number;
  /** Custom fetch implementation (defaults to global fetch). */
  fetch?: FetchLike;
  /** Called when an upload fails or is rejected. Never affects the traced code. */
  onFlushError?: (error: unknown, trace: Trace) => void;
}

export interface PromptRef {
  name: string;
  version: string;
}

export interface StartTraceOptions {
  /** Framework label stored in `metadata.framework`. */
  framework?: string;
  caseId?: string;
}

export interface RunTracedOptions<T> extends StartTraceOptions {
  input?: Record<string, unknown>;
  /** Map the traced function's result to the trace output. Defaults to the result itself. */
  toOutput?: (result: Awaited<T>) => unknown;
  /** Hook to enrich the trace (nodes, tool calls, usage) once the result is available. */
  onResult?: (result: Awaited<T>, run: TraceRun) => void;
}

export interface RecordToolCallOptions {
  args?: Record<string, unknown> | unknown;
  result?: unknown;
  error?: string | null;
  latencyMs?: number;
  status?: ToolCallStatus;
  /** Attach to this node instead of the active one. */
  node?: TraceNode;
}

export interface UsageInfo {
  input_tokens?: number;
  output_tokens?: number;
  total_tokens?: number;
}

type RunMode = "full" | "errors" | "off";

interface RunContext {
  run: TraceRun;
  node?: TraceNode;
}

interface PromptBox {
  prompt: PromptRef | null;
}

function now(): number {
  return performance.now();
}

function validatePrompt(name: unknown, version: unknown): PromptRef {
  const n = String(name ?? "").trim();
  const v = String(version ?? "").trim();
  if (!n) throw new Error("prompt name must be a non-empty string");
  if (!v) throw new Error("prompt version must be non-empty");
  if (n.length > MAX_PROMPT_NAME) throw new Error(`prompt name must be at most ${MAX_PROMPT_NAME} characters`);
  if (v.length > MAX_PROMPT_VERSION) throw new Error(`prompt version must be at most ${MAX_PROMPT_VERSION} characters`);
  return { name: n, version: v };
}

/**
 * A single traced run. Created by `tracer.startTrace()`; integrations use it to attach
 * nodes and tool calls to the right trace even when many runs execute concurrently.
 */
export class TraceRun {
  /** The trace being built, or null when this run was not sampled. */
  readonly trace: Trace | null;
  private readonly t0 = now();
  private finished = false;
  private readonly pendingInput: Record<string, unknown>;

  /** @internal */
  constructor(
    private readonly tracer: CortexTracer,
    private readonly mode: RunMode,
    input: Record<string, unknown>,
    private readonly prompt: PromptRef | null,
    private readonly options: StartTraceOptions,
  ) {
    this.pendingInput = input;
    this.trace = mode === "full" ? tracer._newTrace(input, prompt, true, options) : null;
  }

  get sampled(): boolean {
    return this.mode === "full";
  }

  get isFinished(): boolean {
    return this.finished;
  }

  /** Run `fn` with this run as the active trace (so `traceNode` / `recordToolCall` attach to it). */
  run<T>(fn: () => T): T {
    if (this.mode !== "full") return fn();
    return this.tracer._runStorage.run({ run: this }, fn);
  }

  /** Append a node to this trace. Returns the node (a detached node when unsampled). */
  addNode(name: string, init: Partial<TraceNode> = {}): TraceNode {
    const node = createNode({ ...init, node_name: name });
    this.trace?.nodes.push(node);
    return node;
  }

  /** Record a tool call on `options.node`, the active node, or the latest node of this trace. */
  recordToolCall(name: string, options: RecordToolCallOptions = {}): ToolCall {
    const toolCall = createToolCall({
      name,
      args: options.args === undefined ? {} : toRecord(options.args, "input"),
      result: toJsonSafe(options.result) ?? null,
      status: options.status ?? (options.error ? ToolCallStatus.ERROR : ToolCallStatus.SUCCESS),
      latency_ms: options.latencyMs ?? 0,
      error: options.error ?? null,
    });
    captureToolCall(toolCall);
    if (this.trace && !this.finished) {
      const ctx = this.tracer._runStorage.getStore();
      const target =
        options.node ??
        (ctx?.run === this ? ctx.node : undefined) ??
        this.trace.nodes[this.trace.nodes.length - 1] ??
        this.addNode("agent");
      target.tool_calls.push(toolCall);
    }
    return toolCall;
  }

  /** Merge a key into `trace.metadata`. */
  setMetadata(key: string, value: unknown): void {
    if (this.trace) this.trace.metadata[key] = toJsonSafe(value);
  }

  /** Accumulate token usage into `trace.metadata.usage`. */
  addUsage(usage: UsageInfo | undefined): void {
    if (!this.trace || !usage) return;
    const current = (this.trace.metadata.usage ?? {}) as UsageInfo;
    const add = (a: number | undefined, b: number | undefined) =>
      a === undefined && b === undefined ? undefined : (a ?? 0) + (b ?? 0);
    const merged: UsageInfo = {
      input_tokens: add(current.input_tokens, usage.input_tokens),
      output_tokens: add(current.output_tokens, usage.output_tokens),
      total_tokens: add(current.total_tokens, usage.total_tokens),
    };
    this.trace.metadata.usage = Object.fromEntries(Object.entries(merged).filter(([, v]) => v !== undefined));
  }

  /** Mark the run completed with `result` as output. Idempotent. */
  end(result?: unknown): void {
    if (this.finished) return;
    this.finished = true;
    if (this.mode !== "full" || !this.trace) return;
    this.trace.total_latency_ms = now() - this.t0;
    this.trace.status = RunStatus.COMPLETED;
    this.trace.output = result === undefined ? {} : toRecord(result);
    this.tracer._record(this.trace);
  }

  /** Mark the run failed. Unsampled runs are still captured when `sampleErrors` is on. Idempotent. */
  fail(error: unknown): void {
    if (this.finished) return;
    this.finished = true;
    if (this.mode === "off") return;
    const latency = now() - this.t0;
    let trace = this.trace;
    if (!trace) {
      trace = this.tracer._newTrace(this.pendingInput, this.prompt, false, this.options);
      trace.metadata.captured_reason = "error";
    }
    trace.total_latency_ms = latency;
    trace.status = RunStatus.FAILED;
    trace.failure_kind = FailureKind.UNKNOWN;
    trace.failure_detail = errorMessage(error);
    this.tracer._record(trace);
  }
}

/**
 * Instruments AI agents with zero-refactor tracing.
 *
 * ```ts
 * const tracer = new CortexTracer({ project: "payments-agent" });
 * const agent = tracer.wrap(myAgentFn);
 * await agent({ input: "Refund REF-8821" });
 * tracer.lastTrace();
 * await tracer.flush();
 * ```
 */
export class CortexTracer {
  readonly project: string;
  readonly apiKey: string | undefined;
  readonly apiUrl: string;
  readonly environment: string;
  readonly sampleRate: number;
  readonly sampleErrors: boolean;
  readonly localStore: boolean;
  readonly maxLocalTraces: number;
  readonly flushTimeoutMs: number;

  /** @internal */
  readonly _runStorage = new AsyncLocalStorage<RunContext>();
  private readonly promptStorage = new AsyncLocalStorage<PromptBox>();
  private defaultPrompt: PromptRef | null = null;
  private readonly store: Trace[] = [];
  private readonly pending = new Set<Promise<void>>();
  private readonly fetchImpl: FetchLike | undefined;
  private readonly onFlushError: CortexTracerOptions["onFlushError"];
  private closed = false;

  constructor(options: CortexTracerOptions = {}) {
    this.project = resolveProject(options.project);
    this.apiKey = resolveApiKey(options.apiKey);
    this.apiUrl = resolveApiUrl(options.apiUrl);
    this.environment = resolveEnvironment(options.environment);
    this.sampleRate = resolveSampleRate(options.sampleRate);
    this.sampleErrors = options.sampleErrors ?? true;
    this.localStore = options.localStore ?? true;
    this.maxLocalTraces = Math.max(1, options.maxLocalTraces ?? 1000);
    this.flushTimeoutMs = options.flushTimeoutMs ?? 2000;
    this.fetchImpl = options.fetch ?? (typeof fetch === "function" ? (fetch as FetchLike) : undefined);
    this.onFlushError = options.onFlushError;
  }

  /** True if traces will be shipped to the hosted API. */
  get isHosted(): boolean {
    return Boolean(this.apiKey);
  }

  // ── Prompt version tracking ────────────────────────────────────────────

  /**
   * Tag subsequent traces with a prompt name and version. Inside a `usePrompt()` scope
   * this only affects that scope; outside it sets the tracer-wide default.
   */
  setPrompt(name: string, version: string | number): void {
    const prompt = validatePrompt(name, version);
    const box = this.promptStorage.getStore();
    if (box) box.prompt = prompt;
    else this.defaultPrompt = prompt;
  }

  /** Stop tagging traces with a prompt version (scoped like `setPrompt`). */
  clearPrompt(): void {
    const box = this.promptStorage.getStore();
    if (box) box.prompt = null;
    else this.defaultPrompt = null;
  }

  /** The active prompt for the current async context, or null. */
  get prompt(): PromptRef | null {
    const box = this.promptStorage.getStore();
    return box ? box.prompt : this.defaultPrompt;
  }

  /**
   * Run `fn` with traces tagged by this prompt version. Uses AsyncLocalStorage, so
   * concurrent async calls with different prompts never see each other's tag.
   */
  usePrompt<T>(name: string, version: string | number, fn: () => T): T {
    const prompt = validatePrompt(name, version);
    return this.promptStorage.run({ prompt }, fn);
  }

  // ── Tracing primitives ────────────────────────────────────────────────

  /** @internal */
  _newTrace(input: Record<string, unknown>, prompt: PromptRef | null, sampled: boolean, options: StartTraceOptions): Trace {
    const metadata: Record<string, unknown> = { sample_rate: this.sampleRate, sampled };
    if (options.framework) metadata.framework = options.framework;
    return createTrace({
      project: this.project,
      input,
      environment: this.environment,
      case_id: options.caseId ?? null,
      prompt_name: prompt?.name ?? null,
      prompt_version: prompt?.version ?? null,
      metadata,
    });
  }

  /**
   * Start a run manually (head sampling is decided here). Use `run.run(fn)` to make it the
   * active trace, then `run.end(output)` or `run.fail(error)`.
   */
  startTrace(input: Record<string, unknown> = {}, options: StartTraceOptions = {}): TraceRun {
    const sampled = this.sampleRate >= 1.0 || Math.random() < this.sampleRate;
    const mode: RunMode = sampled ? "full" : this.sampleErrors ? "errors" : "off";
    return new TraceRun(this, mode, toRecord(input), this.prompt, options);
  }

  /**
   * Trace a single call of `fn` (sync or async). Errors are recorded and re-thrown;
   * instrumentation problems never surface in the caller.
   */
  runTraced<T>(fn: (run: TraceRun) => T, options: RunTracedOptions<T> = {}): T {
    const run = this.startTrace(options.input ?? {}, options);
    const finish = (value: Awaited<T>) => {
      try {
        options.onResult?.(value, run);
      } catch {
        // instrumentation must never break the agent
      }
      let output: unknown = value;
      try {
        if (options.toOutput) output = options.toOutput(value);
      } catch {
        output = undefined;
      }
      run.end(output);
    };
    let result: T;
    try {
      result = run.run(() => fn(run));
    } catch (err) {
      run.fail(err);
      throw err;
    }
    if (isPromiseLike(result)) {
      return Promise.resolve(result).then(
        (value) => {
          finish(value as Awaited<T>);
          return value;
        },
        (err: unknown) => {
          run.fail(err);
          throw err;
        },
      ) as T;
    }
    finish(result as Awaited<T>);
    return result;
  }

  /**
   * Instrument an agent. Framework is auto-detected: LangGraph.js compiled graphs, Mastra
   * agents, OpenAI Agents SDK agents, Vercel AI SDK `generateText` / `streamText`, objects
   * with `.invoke()`, or any plain (sync or async) function.
   */
  wrap<T>(agent: T): T {
    return wrapAgent(this, agent);
  }

  /** Instrument a single node / step. Nodes attach to the active trace; outside a trace `fn` just runs. */
  traceNode<T>(name: string, fn: (node: TraceNode) => T): T {
    const ctx = this._runStorage.getStore();
    const node = ctx?.run.trace && !ctx.run.isFinished ? ctx.run.addNode(name) : createNode({ node_name: name });
    const t0 = now();
    const done = () => {
      node.latency_ms = now() - t0;
    };
    let result: T;
    try {
      result = ctx ? this._runStorage.run({ run: ctx.run, node }, () => fn(node)) : fn(node);
    } catch (err) {
      done();
      throw err;
    }
    if (isPromiseLike(result)) {
      return Promise.resolve(result).then(
        (value) => {
          done();
          return value;
        },
        (err: unknown) => {
          done();
          throw err;
        },
      ) as T;
    }
    done();
    return result;
  }

  /**
   * Record a tool call on the active node (or the latest node of the active trace).
   * Outside a trace the call is returned but not attached.
   */
  recordToolCall(name: string, options: Omit<RecordToolCallOptions, "node"> = {}): ToolCall {
    const ctx = this._runStorage.getStore();
    if (ctx) return ctx.run.recordToolCall(name, options);
    const toolCall = createToolCall({
      name,
      args: options.args === undefined ? {} : toRecord(options.args, "input"),
      result: toJsonSafe(options.result) ?? null,
      status: options.status ?? (options.error ? ToolCallStatus.ERROR : ToolCallStatus.SUCCESS),
      latency_ms: options.latencyMs ?? 0,
      error: options.error ?? null,
    });
    captureToolCall(toolCall);
    return toolCall;
  }

  /** The run active in the current async context, if any. */
  currentRun(): TraceRun | undefined {
    return this._runStorage.getStore()?.run;
  }

  /** The trace active in the current async context, if any. */
  currentTrace(): Trace | undefined {
    return this._runStorage.getStore()?.run.trace ?? undefined;
  }

  // ── Local store ───────────────────────────────────────────────────────

  lastTrace(): Trace | undefined {
    return this.store[this.store.length - 1];
  }

  traces(): Trace[] {
    return [...this.store];
  }

  clear(): void {
    this.store.length = 0;
  }

  // ── Upload ────────────────────────────────────────────────────────────

  /** @internal */
  _record(trace: Trace): void {
    if (this.localStore) {
      this.store.push(trace);
      if (this.store.length > this.maxLocalTraces) this.store.splice(0, this.store.length - this.maxLocalTraces);
    }
    if (this.apiKey && !this.closed) this.flushTrace(trace);
  }

  private flushTrace(trace: Trace): void {
    const task = this.send(trace)
      .catch((err: unknown) => this.reportFlushError(err, trace))
      .finally(() => {
        this.pending.delete(task);
      });
    this.pending.add(task);
  }

  private async send(trace: Trace): Promise<void> {
    if (!this.fetchImpl || !this.apiKey) return;
    const res = await this.fetchImpl(`${this.apiUrl}/v1/traces`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-API-Key": this.apiKey,
        "Idempotency-Key": trace.trace_id,
        "User-Agent": USER_AGENT,
      },
      body: JSON.stringify(toJsonSafe(trace)),
      signal: AbortSignal.timeout(this.flushTimeoutMs),
    });
    if (!res.ok) {
      const detail = await res.text().catch(() => "");
      throw new Error(`CortexOps trace upload failed: HTTP ${res.status} ${detail.slice(0, 200)}`);
    }
    await res.arrayBuffer().catch(() => undefined);
  }

  private reportFlushError(err: unknown, trace: Trace): void {
    try {
      this.onFlushError?.(err, trace);
    } catch {
      // never propagate
    }
  }

  /** Number of uploads still in flight. */
  get pendingUploads(): number {
    return this.pending.size;
  }

  /** Wait for all in-flight uploads (each bounded by `flushTimeoutMs`). Never throws. */
  async flush(): Promise<void> {
    while (this.pending.size) {
      await Promise.allSettled([...this.pending]);
    }
  }

  /** Flush pending uploads and stop uploading further traces. */
  async shutdown(): Promise<void> {
    await this.flush();
    this.closed = true;
  }
}
