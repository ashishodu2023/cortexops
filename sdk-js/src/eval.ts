import { readFile } from "node:fs/promises";
import { randomUUID } from "node:crypto";
import { fileURLToPath } from "node:url";
import { withCapture, type CaptureSink } from "./capture.js";
import { errorMessage, isPlainObject, toJsonSafe } from "./json.js";
import { computeCaseResult, type Metric } from "./metrics.js";
import {
  FailureKind,
  RunStatus,
  aggregateJudgeUsage,
  createNode,
  createTrace,
  formatSummary,
  type CaseResult,
  type EvalCase,
  type EvalDataset,
  type EvalSummary,
  type Trace,
} from "./models.js";
import { fixed, pyFloat, pyStr } from "./pyfmt.js";
import { outputTextOf } from "./integrations/shared.js";

// ── Dataset loading ─────────────────────────────────────────────────────────

function stringList(value: unknown, field: string, caseId: string): string[] {
  if (value === undefined || value === null) return [];
  if (!Array.isArray(value)) throw new Error(`case '${caseId}': ${field} must be a list`);
  return value.map((v) => String(v));
}

function datasetVersion(value: unknown): number {
  if (value === undefined || value === null) return 1;
  const n = typeof value === "string" && /^\s*[+-]?\d+\s*$/.test(value) ? Number(value) : value;
  if (typeof n !== "number" || !Number.isInteger(n)) {
    throw new Error(`dataset version must be an integer, got ${JSON.stringify(value)}`);
  }
  return n;
}

/** Parse a golden dataset object (same schema as the Python `EvalSuite`). */
export function parseDataset(raw: unknown): EvalDataset {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
    throw new Error("dataset must be a mapping with a 'cases' list");
  }
  const r = raw as Record<string, unknown>;
  const rawCases = r.cases ?? [];
  if (!Array.isArray(rawCases)) throw new Error("dataset 'cases' must be a list");
  const cases: EvalCase[] = rawCases.map((c: unknown, i: number) => {
    if (!c || typeof c !== "object") throw new Error(`case #${i + 1} must be a mapping`);
    const rc = c as Record<string, unknown>;
    if (rc.id === undefined || rc.id === null) throw new Error(`case #${i + 1} is missing 'id'`);
    const id = String(rc.id);
    if (rc.input === undefined) throw new Error(`case '${id}' is missing 'input'`);
    const input = rc.input;
    if (typeof input !== "string" && !isPlainObject(input)) {
      throw new Error(`case '${id}': input must be a string or a mapping`);
    }
    const maxLatency = rc.max_latency_ms;
    if (maxLatency !== undefined && maxLatency !== null && typeof maxLatency !== "number") {
      throw new Error(`case '${id}': max_latency_ms must be a number`);
    }
    return {
      id,
      input,
      expected_tool_calls: stringList(rc.expected_tool_calls, "expected_tool_calls", id),
      expected_output_contains: stringList(rc.expected_output_contains, "expected_output_contains", id),
      expected_output_not_contains: stringList(rc.expected_output_not_contains, "expected_output_not_contains", id),
      max_latency_ms: typeof maxLatency === "number" ? maxLatency : null,
      judge: typeof rc.judge === "string" ? rc.judge : "rule",
      judge_criteria: typeof rc.judge_criteria === "string" ? rc.judge_criteria : null,
      tags: stringList(rc.tags, "tags", id),
    };
  });
  const dataset: EvalDataset = {
    version: datasetVersion(r.version),
    project: typeof r.project === "string" && r.project ? r.project : "unknown",
    description: typeof r.description === "string" ? r.description : "",
    cases,
  };
  if (typeof r.name === "string") dataset.name = r.name;
  return dataset;
}

/** Parse YAML (YAML 1.1, matching PyYAML's `safe_load`) or JSON dataset text. */
export async function parseDatasetText(text: string): Promise<unknown> {
  const { parse } = await import("yaml");
  return parse(text, { version: "1.1" });
}

/** Load a dataset from a YAML/JSON file path, a raw mapping, or an `EvalDataset`. */
export async function loadDataset(source: string | EvalDataset | Record<string, unknown>): Promise<EvalDataset> {
  if (typeof source !== "string") return parseDataset(source);
  let text: string;
  try {
    text = await readFile(source, "utf8");
  } catch (err) {
    if ((err as NodeJS.ErrnoException).code === "ENOENT") {
      throw Object.assign(new Error(`Dataset not found: ${source}`), { code: "ENOENT" });
    }
    throw err;
  }
  return parseDataset(await parseDatasetText(text));
}

// ── Threshold gates ─────────────────────────────────────────────────────────

export const THRESHOLD_METRICS = ["task_completion", "tool_accuracy", "pass_rate"] as const;
export type ThresholdMetric = (typeof THRESHOLD_METRICS)[number];
export type ThresholdOp = "<" | "<=" | ">" | ">=";

export interface Threshold {
  expression: string;
  metric: ThresholdMetric;
  op: ThresholdOp;
  threshold: number;
}

export interface GateResult extends Threshold {
  actual: number;
  /** True when the failure condition is met (the gate trips). */
  failed: boolean;
  message: string;
}

const THRESHOLD_RE = /^(\w+)\s*([<>]=?)\s*(\d+(?:\.\d+)?|\.\d+)$/;

/** Parse `"task_completion < 0.90"` (same grammar as the Python SDK). */
export function parseThreshold(expression: string): Threshold {
  const m = THRESHOLD_RE.exec(expression.trim());
  if (!m) throw new Error(`Invalid fail_on expression: '${expression}'`);
  const [, metric, op, value] = m as unknown as [string, string, ThresholdOp, string];
  if (!(THRESHOLD_METRICS as readonly string[]).includes(metric)) {
    throw new Error(`Unknown metric in fail_on: '${metric}'`);
  }
  return { expression: expression.trim(), metric: metric as ThresholdMetric, op, threshold: Number(value) };
}

/**
 * Parse one or more gate expressions. Accepts an array and/or strings containing several
 * expressions separated by commas, semicolons or newlines.
 */
export function parseFailOn(failOn: string | readonly string[] | undefined | null): Threshold[] {
  if (failOn === undefined || failOn === null) return [];
  const list = typeof failOn === "string" ? [failOn] : [...failOn];
  return list
    .flatMap((s) => s.split(/[,;\n]/))
    .map((s) => s.trim())
    .filter(Boolean)
    .map(parseThreshold);
}

function metricValue(summary: EvalSummary, metric: ThresholdMetric): number {
  switch (metric) {
    case "task_completion":
      return summary.task_completion_rate;
    case "tool_accuracy":
      return summary.tool_accuracy / 100.0;
    case "pass_rate":
      return summary.passed / Math.max(summary.total_cases, 1);
  }
}

function compare(actual: number, op: ThresholdOp, threshold: number): boolean {
  switch (op) {
    case "<":
      return actual < threshold;
    case "<=":
      return actual <= threshold;
    case ">":
      return actual > threshold;
    case ">=":
      return actual >= threshold;
  }
}

/** Evaluate gate expressions against a summary without throwing. */
export function checkThresholds(summary: EvalSummary, failOn: string | readonly string[] | Threshold[]): GateResult[] {
  const thresholds: Threshold[] =
    Array.isArray(failOn) && failOn.length && typeof failOn[0] === "object"
      ? (failOn as Threshold[])
      : parseFailOn(failOn as string | readonly string[]);
  return thresholds.map((t) => {
    const actual = metricValue(summary, t.metric);
    const failed = compare(actual, t.op, t.threshold);
    const message = `Eval gate failed: ${t.metric}=${fixed(actual, 3)} ${t.op} ${pyFloat(t.threshold)} (project=${summary.project})`;
    return { ...t, actual, failed, message };
  });
}

/** Raised when an eval run trips a CI threshold gate. Carries the full summary. */
export class EvalThresholdError extends Error {
  override name = "EvalThresholdError";
  constructor(
    message: string,
    readonly failures: GateResult[],
    readonly summary: EvalSummary,
  ) {
    super(message);
  }
}

// ── Suite ───────────────────────────────────────────────────────────────────

export type AgentFn = (input: Record<string, unknown>) => unknown;
export type Agent = AgentFn | { invoke: AgentFn };

export interface EvalRunOptions {
  /** Gate expression(s), e.g. `"task_completion < 0.90"`. Throws `EvalThresholdError` when tripped. */
  failOn?: string | readonly string[];
  /** Print case-by-case progress and the summary (default true, like Python). */
  verbose?: boolean;
  /** Extra metrics appended to the built-in ones. */
  metrics?: Metric[];
  /** Override the project from the dataset. */
  project?: string;
  /** Output sink for verbose logging (default: stdout). */
  write?: (text: string) => void;
}

/**
 * Convert an agent's return value into the trace output: mappings are kept as-is (like
 * Python), strings become `{output}`; Vercel AI SDK / Mastra results (`.text`) and OpenAI
 * Agents results (`.finalOutput`) are unwrapped; anything else is stringified.
 */
export function normalizeAgentOutput(value: unknown): Record<string, unknown> {
  if (isPlainObject(value)) return toJsonSafe(value) as Record<string, unknown>;
  if (value !== null && typeof value === "object") {
    const text = outputTextOf(value);
    if (text !== null && text !== undefined) return { output: typeof text === "string" ? text : pyStr(text) };
  }
  return { output: pyStr(value) };
}

async function runCase(agent: unknown, evalCase: EvalCase): Promise<Trace> {
  const input: Record<string, unknown> = isPlainObject(evalCase.input) ? evalCase.input : { input: evalCase.input };
  const sink: CaptureSink = { toolCalls: [] };
  const t0 = performance.now();
  try {
    const output = await withCapture(sink, async () => {
      if (agent && typeof (agent as { invoke?: unknown }).invoke === "function") {
        return (agent as { invoke: AgentFn }).invoke(input);
      }
      if (typeof agent === "function") return (agent as AgentFn)(input);
      const name = (agent as object | null)?.constructor?.name ?? typeof agent;
      throw new TypeError(`Agent ${name} is not callable`);
    });
    const latency = performance.now() - t0;
    const outputRecord = normalizeAgentOutput(output);
    const safeInput = toJsonSafe(input) as Record<string, unknown>;
    return createTrace({
      project: "eval",
      case_id: evalCase.id,
      input: safeInput,
      output: outputRecord,
      total_latency_ms: latency,
      status: RunStatus.COMPLETED,
      nodes: [
        createNode({
          node_id: "eval_root",
          node_name: "agent",
          input: safeInput,
          output: outputRecord,
          tool_calls: sink.toolCalls,
          latency_ms: latency,
        }),
      ],
    });
  } catch (err) {
    const latency = performance.now() - t0;
    return createTrace({
      project: "eval",
      case_id: evalCase.id,
      input: toJsonSafe(input) as Record<string, unknown>,
      output: {},
      total_latency_ms: latency,
      status: RunStatus.FAILED,
      failure_kind: FailureKind.UNKNOWN,
      failure_detail: errorMessage(err),
    });
  }
}

function percentileIndex(n: number, q: number): number {
  // Python: latencies_sorted[int(n * q) - 1] (a negative index wraps around)
  const idx = Math.floor(n * q) - 1;
  return idx < 0 ? idx + n : idx;
}

/** Aggregate case results into a summary (same arithmetic as Python `EvalSuite.run`). */
export function summarize(dataset: EvalDataset, results: CaseResult[], project?: string): EvalSummary {
  const n = results.length;
  const latencies = results.map((r) => r.latency_ms).sort((a, b) => a - b);
  return {
    run_id: randomUUID(),
    project: project ?? dataset.project,
    dataset_version: dataset.version,
    total_cases: n,
    passed: results.filter((r) => r.passed).length,
    failed: results.filter((r) => !r.passed).length,
    warnings: results.filter((r) => !r.passed && r.score >= 60).length,
    task_completion_rate: results.filter((r) => r.task_completion).length / Math.max(n, 1),
    tool_accuracy: n ? results.reduce((a, r) => a + r.tool_accuracy, 0) / n : 0.0,
    latency_p50_ms: n ? latencies[percentileIndex(n, 0.5)]! : 0.0,
    latency_p95_ms: n ? latencies[percentileIndex(n, 0.95)]! : 0.0,
    regressions: 0,
    baseline_run_id: null,
    case_results: results,
    timestamp: new Date().toISOString(),
    ...aggregateJudgeUsage(results),
  };
}

/**
 * Run evaluation suites against any agent: a function `(input) => output` (sync or async)
 * or an object with `.invoke(input)` (LangGraph style).
 *
 * ```ts
 * const summary = await EvalSuite.run("golden_v1.yaml", agent, { failOn: "task_completion < 0.90" });
 * ```
 */
export class EvalSuite {
  static async run(
    dataset: string | EvalDataset | Record<string, unknown>,
    agent: Agent | unknown,
    options: EvalRunOptions = {},
  ): Promise<EvalSummary> {
    const thresholds = parseFailOn(options.failOn);
    const ds = await loadDataset(dataset);
    const verbose = options.verbose ?? true;
    const write = options.write ?? ((text: string) => void process.stdout.write(text));

    const results: CaseResult[] = [];
    for (const [i, evalCase] of ds.cases.entries()) {
      if (verbose) write(`  [${i + 1}/${ds.cases.length}] ${evalCase.id} ... `);
      const trace = await runCase(agent, evalCase);
      const result = computeCaseResult(evalCase, trace, options.metrics);
      results.push(result);
      if (verbose) write(`${result.passed ? "pass" : "FAIL"} (${fixed(result.score, 0)})\n`);
    }

    const summary = summarize(ds, results, options.project);
    if (verbose) write(`\n${formatSummary(summary)}\n`);

    if (thresholds.length) {
      const failures = checkThresholds(summary, thresholds).filter((g) => g.failed);
      if (failures.length) {
        throw new EvalThresholdError(failures.map((f) => f.message).join("; "), failures, summary);
      }
    }
    return summary;
  }
}

/** Gate used when none is given: every case must pass (same default as the Python SDK). */
export const DEFAULT_FAIL_ON = "pass_rate < 1.0";

export interface EvalGateOptions extends Omit<EvalRunOptions, "failOn"> {
  /** Gate expression(s). Defaults to `DEFAULT_FAIL_ON`; `null` only records results. */
  failOn?: string | readonly string[] | null;
}

/**
 * Eval gate for test runners (Vitest, Jest, `node:test`), the counterpart of Python's
 * `@cortexops.eval_gate`. Resolves with the summary, or rejects with an `EvalThresholdError`
 * whose message lists every tripped condition followed by the summary.
 *
 * ```ts
 * test("payments agent", async () => {
 *   await evalGate(new URL("./golden_v1.yaml", import.meta.url), buildAgent(), {
 *     failOn: ["task_completion < 0.90", "tool_accuracy < 0.95"],
 *   });
 * }, 60_000);
 * ```
 */
export async function evalGate(
  dataset: string | URL | EvalDataset | Record<string, unknown>,
  agent: Agent | unknown,
  options: EvalGateOptions = {},
): Promise<EvalSummary> {
  const { failOn, ...runOptions } = options;
  const thresholds = parseFailOn(failOn === undefined ? DEFAULT_FAIL_ON : failOn);
  const source = dataset instanceof URL ? fileURLToPath(dataset) : dataset;
  const summary = await EvalSuite.run(source, agent, { verbose: false, ...runOptions });
  const failures = checkThresholds(summary, thresholds).filter((g) => g.failed);
  if (failures.length) {
    const message = `${failures.map((f) => f.message).join("\n")}\n\n${formatSummary(summary)}`;
    throw new EvalThresholdError(message, failures, summary);
  }
  return summary;
}
