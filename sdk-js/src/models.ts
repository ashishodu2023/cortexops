import { randomUUID } from "node:crypto";
import { fixed, percent } from "./pyfmt.js";

/*
 * Data models mirror the Python SDK (`cortexops.models`) field-for-field and use the
 * same snake_case names, so traces and eval summaries serialize to exactly the JSON
 * the CortexOps API (`TraceIngest`, `EvalSummaryIngest`) and existing tooling expect.
 */

export const RunStatus = {
  PENDING: "pending",
  RUNNING: "running",
  COMPLETED: "completed",
  FAILED: "failed",
} as const;
export type RunStatus = (typeof RunStatus)[keyof typeof RunStatus];

export const ToolCallStatus = {
  SUCCESS: "success",
  ERROR: "error",
  TIMEOUT: "timeout",
} as const;
export type ToolCallStatus = (typeof ToolCallStatus)[keyof typeof ToolCallStatus];

export const FailureKind = {
  TOOL_CALL_MISMATCH: "tool_call_mismatch",
  HALLUCINATION: "hallucination",
  PLAN_DEVIATION: "plan_deviation",
  TIMEOUT: "timeout",
  CONTEXT_OVERFLOW: "context_overflow",
  OUTPUT_FORMAT: "output_format",
  UNKNOWN: "unknown",
} as const;
export type FailureKind = (typeof FailureKind)[keyof typeof FailureKind];

export interface ToolCall {
  name: string;
  args: Record<string, unknown>;
  result: unknown;
  status: ToolCallStatus;
  latency_ms: number;
  error: string | null;
}

export interface TraceNode {
  node_id: string;
  node_name: string;
  input: Record<string, unknown>;
  output: Record<string, unknown>;
  tool_calls: ToolCall[];
  llm_prompt: string | null;
  llm_response: string | null;
  latency_ms: number;
  timestamp: string;
}

export interface Trace {
  trace_id: string;
  project: string;
  run_id: string;
  case_id: string | null;
  nodes: TraceNode[];
  input: Record<string, unknown>;
  output: Record<string, unknown>;
  total_latency_ms: number;
  status: RunStatus;
  failure_kind: FailureKind | null;
  failure_detail: string | null;
  environment: string | null;
  prompt_name: string | null;
  prompt_version: string | null;
  metadata: Record<string, unknown>;
  timestamp: string;
}

export function createToolCall(init: Partial<ToolCall> & { name: string }): ToolCall {
  return {
    args: {},
    result: null,
    status: ToolCallStatus.SUCCESS,
    latency_ms: 0,
    error: null,
    ...init,
  };
}

export function createNode(init: Partial<TraceNode> & { node_name: string }): TraceNode {
  return {
    node_id: randomUUID(),
    input: {},
    output: {},
    tool_calls: [],
    llm_prompt: null,
    llm_response: null,
    latency_ms: 0,
    timestamp: new Date().toISOString(),
    ...init,
  };
}

export function createTrace(init: Partial<Trace> & { project: string }): Trace {
  return {
    trace_id: randomUUID(),
    run_id: randomUUID(),
    case_id: null,
    nodes: [],
    input: {},
    output: {},
    total_latency_ms: 0,
    status: RunStatus.COMPLETED,
    failure_kind: null,
    failure_detail: null,
    environment: null,
    prompt_name: null,
    prompt_version: null,
    metadata: {},
    timestamp: new Date().toISOString(),
    ...init,
  };
}

/** All tool calls across all nodes (Python `Trace.tool_calls()`). */
export function traceToolCalls(trace: Trace): ToolCall[] {
  return trace.nodes.flatMap((node) => node.tool_calls);
}

// ── Eval models ────────────────────────────────────────────────────────────

export interface EvalCase {
  id: string;
  input: string | Record<string, unknown>;
  expected_tool_calls: string[];
  expected_output_contains: string[];
  expected_output_not_contains: string[];
  max_latency_ms: number | null;
  /** "rule" (default) or "llm" */
  judge: string;
  judge_criteria: string | null;
  tags: string[];
}

export interface EvalDataset {
  version: number;
  project: string;
  description: string;
  cases: EvalCase[];
  /** Dataset name, when the YAML declares one (used for dashboard snapshots). */
  name?: string;
}

export interface CaseResult {
  case_id: string;
  passed: boolean;
  /** 0.0 - 100.0 */
  score: number;
  task_completion: boolean;
  /** 0.0 - 100.0 */
  tool_accuracy: number;
  latency_ms: number;
  latency_ok: boolean;
  failure_kind: string | null;
  failure_detail: string | null;
  trace: Trace | null;
}

export interface EvalSummary {
  run_id: string;
  project: string;
  dataset_version: number;
  total_cases: number;
  passed: number;
  failed: number;
  warnings: number;
  /** 0.0 - 1.0 */
  task_completion_rate: number;
  /** 0.0 - 100.0 */
  tool_accuracy: number;
  latency_p50_ms: number;
  latency_p95_ms: number;
  regressions: number;
  baseline_run_id: string | null;
  case_results: CaseResult[];
  timestamp: string;
}

export function createEvalCase(init: Partial<EvalCase> & { id: string; input: EvalCase["input"] }): EvalCase {
  return {
    expected_tool_calls: [],
    expected_output_contains: [],
    expected_output_not_contains: [],
    max_latency_ms: null,
    judge: "rule",
    judge_criteria: null,
    tags: [],
    ...init,
  };
}

/** Human-readable summary, identical in layout to Python `EvalSummary.summary()`. */
export function formatSummary(s: EvalSummary): string {
  const lines = [
    `CortexOps eval — ${s.project}`,
    `  Run ID          : ${s.run_id}`,
    `  Cases           : ${s.total_cases}  (${s.passed} passed, ${s.failed} failed)`,
    `  Task completion : ${percent(s.task_completion_rate, 1)}`,
    `  Tool accuracy   : ${fixed(s.tool_accuracy, 1)}/100`,
    `  Latency p50/p95 : ${fixed(s.latency_p50_ms, 0)}ms / ${fixed(s.latency_p95_ms, 0)}ms`,
  ];
  if (s.regressions) {
    lines.push(`  Regressions     : ${s.regressions}  (vs baseline ${s.baseline_run_id})`);
  }
  const failing = s.case_results.filter((r) => !r.passed);
  if (failing.length) {
    lines.push("  Failed cases:");
    for (const r of failing) {
      lines.push(`    - ${r.case_id}: ${r.failure_kind || "unknown"} (score ${fixed(r.score, 0)})`);
    }
  }
  return lines.join("\n");
}
