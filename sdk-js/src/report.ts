import type { GateResult } from "./eval.js";
import { judgeUsage, type EvalSummary } from "./models.js";
import { fixed, pyFloat } from "./pyfmt.js";
import { VERSION } from "./version.js";

/**
 * Eval gate reports: the same JSON report, markdown and JUnit XML formats as the Python
 * CLI (`cortexops eval run --output-json/--summary-md/--junit-xml`), so CI tooling can
 * consume either.
 */

export const REPORT_SCHEMA_VERSION = 1;
export const MAX_FAILED_CASES = 50;
const DETAIL_CHARS = 160;

export function passRate(summary: EvalSummary): number {
  return summary.passed / Math.max(summary.total_cases, 1);
}

/** Mean case score, 0-100. */
export function meanScore(summary: EvalSummary): number {
  const scores = summary.case_results.map((r) => r.score);
  return scores.length ? scores.reduce((a, b) => a + b, 0) / scores.length : 0;
}

export function gatePassed(gates: readonly GateResult[]): boolean {
  return !gates.some((g) => g.failed);
}

export interface EvalReport extends Omit<EvalSummary, "case_results"> {
  schema_version: number;
  cortexops_version: string;
  generator: string;
  gate_passed: boolean;
  dataset_path: string | null;
  pass_rate: number;
  mean_score: number;
  thresholds: Array<Pick<GateResult, "expression" | "metric" | "op" | "threshold" | "actual" | "failed">>;
  case_results: Array<Omit<EvalSummary["case_results"][number], "trace">>;
}

/** JSON-serialisable report: the summary fields (without per-case traces) plus gate results. */
export function buildReport(summary: EvalSummary, gates: readonly GateResult[], options: { dataset?: string } = {}): EvalReport {
  const { case_results, timestamp, judge_cost_usd: _cost, judge_tokens_in: _in, judge_tokens_out: _out, ...rest } = summary;
  return {
    schema_version: REPORT_SCHEMA_VERSION,
    cortexops_version: VERSION,
    generator: "cortexops-js",
    gate_passed: gatePassed(gates),
    dataset_path: options.dataset ?? null,
    pass_rate: passRate(summary),
    mean_score: meanScore(summary),
    thresholds: gates.map(({ expression, metric, op, threshold, actual, failed }) => ({ expression, metric, op, threshold, actual, failed })),
    ...rest,
    case_results: case_results.map(({ trace: _trace, ...r }) => ({ ...r, ...judgeUsage(r) })),
    timestamp,
    ...judgeUsage(summary),
  };
}

function pct(value: number): string {
  return `${fixed(value * 100, 1)}%`;
}

function ms(value: number): string {
  return value >= 10 ? `${fixed(value, 0)} ms` : `${fixed(value, 1)} ms`;
}

function cell(text: unknown): string {
  let s = String(text).trim().split(/\s+/).filter(Boolean).join(" ");
  if (s.length > DETAIL_CHARS) s = `${s.slice(0, DETAIL_CHARS - 3)}...`;
  return s.replace(/\|/g, "\\|");
}

export interface MarkdownOptions {
  dataset?: string;
  title?: string;
  maxFailedCases?: number;
}

/** GitHub-flavoured markdown for a job summary or PR comment. */
export function renderMarkdown(summary: EvalSummary, gates: readonly GateResult[] = [], options: MarkdownOptions = {}): string {
  const title = options.title ?? "CortexOps eval gate";
  const maxFailed = options.maxFailedCases ?? MAX_FAILED_CASES;
  const lines = [`## ${title}: ${gatePassed(gates) ? "PASSED" : "FAILED"}`, ""];

  const context = [`Project \`${summary.project}\``];
  if (options.dataset) context.push(`dataset \`${options.dataset}\` (v${summary.dataset_version})`);
  context.push(`run \`${summary.run_id.slice(0, 8)}\``);
  lines.push(context.join(", "), "");

  lines.push(
    "| Metric | Value |",
    "|---|---|",
    `| Cases | ${summary.total_cases} |`,
    `| Passed / failed | ${summary.passed} / ${summary.failed} |`,
    `| Pass rate | ${pct(passRate(summary))} |`,
    `| Mean score | ${fixed(meanScore(summary), 1)}/100 |`,
    `| Task completion | ${pct(summary.task_completion_rate)} |`,
    `| Tool accuracy | ${pct(summary.tool_accuracy / 100)} |`,
    `| Latency p50 / p95 | ${ms(summary.latency_p50_ms)} / ${ms(summary.latency_p95_ms)} |`,
    "",
  );

  if (gates.length) {
    lines.push(
      "### Thresholds",
      "",
      "The gate fails when any condition below is true.",
      "",
      "| Fail on | Actual | Result |",
      "|---|---|---|",
    );
    for (const g of gates) lines.push(`| \`${cell(g.expression)}\` | ${fixed(g.actual, 3)} | ${g.failed ? "FAILED" : "ok"} |`);
    lines.push("");
  }

  const failing = summary.case_results.filter((r) => !r.passed);
  if (failing.length) {
    lines.push(`### Failed cases (${failing.length})`, "", "| Case | Failure kind | Score | Detail |", "|---|---|---|---|");
    for (const r of failing.slice(0, maxFailed)) {
      const detail = r.failure_detail ? cell(r.failure_detail) : "";
      lines.push(`| \`${cell(r.case_id)}\` | ${r.failure_kind || "unknown"} | ${fixed(r.score, 0)} | ${detail} |`);
    }
    if (failing.length > maxFailed) lines.push(`\n_...and ${failing.length - maxFailed} more failed cases._`);
    lines.push("");
  } else {
    lines.push("_All cases passed._", "");
  }

  lines.push(`<sub>Generated by cortexops-js ${VERSION}</sub>`);
  return `${lines.join("\n")}\n`;
}

function xmlAttr(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/\r/g, "&#13;")
    .replace(/\n/g, "&#10;")
    .replace(/\t/g, "&#09;");
}

function xmlText(value: string): string {
  return value.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function element(indent: string, tag: string, attrs: Record<string, string>, children: string[] = [], text = ""): string {
  const open = `${indent}<${tag}${Object.entries(attrs).map(([k, v]) => ` ${k}="${xmlAttr(v)}"`).join("")}`;
  if (children.length) return `${open}>\n${children.join("\n")}\n${indent}</${tag}>`;
  if (text) return `${open}>${xmlText(text)}</${tag}>`;
  return `${open} />`;
}

/** JUnit XML: one testcase per eval case plus one per gate condition. */
export function renderJunit(summary: EvalSummary, gates: readonly GateResult[]): string {
  const project = summary.project;
  const caseElements = summary.case_results.map((r) => {
    const failure: string[] = [];
    if (!r.passed) {
      const kind = r.failure_kind || "unknown";
      failure.push(element("      ", "failure", { type: kind, message: `score ${fixed(r.score, 0)}: ${kind}` }, [], r.failure_detail ?? ""));
    }
    return element("    ", "testcase", { classname: `cortexops.${project}`, name: r.case_id, time: fixed(r.latency_ms / 1000, 3) }, failure);
  });
  const totalTime = summary.case_results.reduce((a, r) => a + r.latency_ms, 0) / 1000;
  const cases = element(
    "  ",
    "testsuite",
    { name: `cortexops.${project}`, tests: String(summary.total_cases), failures: String(summary.failed), errors: "0", time: fixed(totalTime, 3) },
    caseElements,
  );

  const gateFailures = gates.filter((g) => g.failed).length;
  const gateElements = gates.map((g) =>
    element(
      "    ",
      "testcase",
      { classname: "cortexops.thresholds", name: `fail_on: ${g.expression}`, time: "0" },
      g.failed
        ? [element("      ", "failure", { type: "threshold", message: `${g.metric}=${fixed(g.actual, 3)} ${g.op} ${pyFloat(g.threshold)}` })]
        : [],
    ),
  );
  const gateSuite = element(
    "  ",
    "testsuite",
    { name: "cortexops.thresholds", tests: String(gates.length), failures: String(gateFailures), errors: "0", time: "0" },
    gateElements,
  );

  const root = element(
    "",
    "testsuites",
    { name: "cortexops", tests: String(summary.total_cases + gates.length), failures: String(summary.failed + gateFailures) },
    [cases, gateSuite],
  );
  return `<?xml version="1.0" encoding="UTF-8"?>\n${root}\n`;
}
