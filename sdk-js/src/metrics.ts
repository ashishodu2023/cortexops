import {
  FailureKind,
  traceToolCalls,
  type CaseResult,
  type EvalCase,
  type Trace,
} from "./models.js";
import { fixed, pyRepr, pyRound, pyStr } from "./pyfmt.js";

/*
 * Port of `cortexops/metrics.py`. Scores, failure kinds and failure details are kept
 * identical to the Python SDK so that the same dataset gates the same way in both.
 */

/** `[score 0-100, failure kind or null, failure detail or null]` */
export type MetricScore = [score: number, failureKind: string | null, failureDetail: string | null];

export interface Metric {
  name: string;
  score(evalCase: EvalCase, trace: Trace): MetricScore;
}

function has(obj: Record<string, unknown>, key: string): boolean {
  return Object.prototype.hasOwnProperty.call(obj, key);
}

/** Python: `str(output.get("output", output.get("result", output.get("answer", ""))))` */
function primaryOutput(output: Record<string, unknown>): string {
  if (has(output, "output")) return pyStr(output.output);
  if (has(output, "result")) return pyStr(output.result);
  if (has(output, "answer")) return pyStr(output.answer);
  return "";
}

function firstChars(s: string, n: number): string {
  return Array.from(s).slice(0, n).join("");
}

const ERROR_PATTERNS = [/error:/i, /exception:/i, /traceback/i, /failed to/i];

/** Checks whether the agent produced a non-empty, non-error output. */
export class TaskCompletionMetric implements Metric {
  name = "task_completion";

  score(evalCase: EvalCase, trace: Trace): MetricScore {
    const output = trace.output ?? {};
    const outputStr = primaryOutput(output);
    const lower = outputStr.toLowerCase();

    if (!outputStr || lower === "none" || lower === "null" || lower === "") {
      return [0.0, FailureKind.UNKNOWN, "Agent produced no output"];
    }

    for (const pattern of ERROR_PATTERNS) {
      if (pattern.test(outputStr)) {
        return [20.0, FailureKind.UNKNOWN, `Output contains error signal: ${firstChars(outputStr, 100)}`];
      }
    }

    const contains = evalCase.expected_output_contains;
    if (contains.length) {
      const hits = contains.filter((kw) => lower.includes(kw.toLowerCase())).length;
      const ratio = hits / contains.length;
      if (ratio < 1.0) {
        const missing = contains.filter((kw) => !lower.includes(kw.toLowerCase()));
        return [50.0 + 50.0 * ratio, FailureKind.OUTPUT_FORMAT, `Missing expected content: ${pyRepr(missing)}`];
      }
    }

    const notContains = evalCase.expected_output_not_contains;
    if (notContains.length) {
      const violations = notContains.filter((kw) => lower.includes(kw.toLowerCase()));
      if (violations.length) {
        return [30.0, FailureKind.HALLUCINATION, `Output contains prohibited content: ${pyRepr(violations)}`];
      }
    }

    return [100.0, null, null];
  }
}

/**
 * Checks whether expected tool calls were actually made. Looks at instrumented tool calls
 * on the trace first, then at `output.tool_calls_made` (agent self-reporting).
 */
export class ToolAccuracyMetric implements Metric {
  name = "tool_accuracy";

  score(evalCase: EvalCase, trace: Trace): MetricScore {
    if (!evalCase.expected_tool_calls.length) return [100.0, null, null];

    let actual = new Set(traceToolCalls(trace).map((tc) => tc.name));
    if (actual.size === 0) {
      const reported = (trace.output ?? {}).tool_calls_made;
      if (Array.isArray(reported)) actual = new Set(reported as string[]);
    }

    const expected = new Set(evalCase.expected_tool_calls);
    const missing = [...expected].filter((name) => !actual.has(name));
    if (!missing.length) return [100.0, null, null];

    const ratio = (expected.size - missing.length) / expected.size;
    return [pyRound(ratio * 100, 1), FailureKind.TOOL_CALL_MISMATCH, `Missing tool calls: ${pyRepr([...missing].sort())}`];
  }
}

/** Checks whether the agent responded within the case's latency budget. */
export class LatencyMetric implements Metric {
  name = "latency";

  score(evalCase: EvalCase, trace: Trace): MetricScore {
    const budget = evalCase.max_latency_ms;
    if (budget === null || budget === undefined) return [100.0, null, null];
    if (trace.total_latency_ms <= budget) return [100.0, null, null];
    const overage = trace.total_latency_ms - budget;
    return [
      Math.max(0.0, 100.0 - (overage / budget) * 100),
      FailureKind.TIMEOUT,
      `Latency ${fixed(trace.total_latency_ms, 0)}ms exceeded budget ${fixed(budget, 0)}ms`,
    ];
  }
}

const HALLUCINATION_PATTERNS: Array<[string, RegExp]> = [
  [
    String.raw`\bas of (january|february|march|april|may|june|july|august|september|october|november|december) 20[0-9]{2}\b`,
    /\bas of (january|february|march|april|may|june|july|august|september|october|november|december) 20[0-9]{2}\b/i,
  ],
  [String.raw`\bi (don't|do not) have (access|information|data)\b`, /\bi (don't|do not) have (access|information|data)\b/i],
  [String.raw`\bi cannot (access|retrieve|look up)\b`, /\bi cannot (access|retrieve|look up)\b/i],
];

/** Detects common hallucination signals in the agent output. */
export class HallucinationMetric implements Metric {
  name = "hallucination";

  score(_evalCase: EvalCase, trace: Trace): MetricScore {
    const output = pyStr(trace.output);
    for (const [source, pattern] of HALLUCINATION_PATTERNS) {
      if (pattern.test(output)) {
        return [40.0, FailureKind.HALLUCINATION, `Hallucination signal detected: pattern '${source}'`];
      }
    }
    return [100.0, null, null];
  }
}

const STOP_WORDS = new Set([
  "the", "a", "an", "is", "it", "in", "on", "at", "to", "and", "or", "of", "for",
  "be", "are", "was", "were", "will", "have", "has", "that", "this", "with", "not",
]);

/**
 * `judge: llm` cases. Mirrors the Python SDK's offline heuristic (keyword/stem overlap
 * between `judge_criteria` and the output); the hosted LLM call is not made from JS.
 */
export class JudgeHeuristicMetric implements Metric {
  name = "llm_judge";

  score(evalCase: EvalCase, trace: Trace): MetricScore {
    const criteria = evalCase.judge_criteria;
    if (evalCase.judge === "rule" || !criteria) return [100.0, null, null];

    const output = pyStr(trace.output ?? "");
    const words = (s: string) => new Set(s.toLowerCase().split(/\s+/).filter(Boolean));
    const criteriaKw = [...words(criteria)].filter((w) => !STOP_WORDS.has(w));
    const outputKw = [...words(output)].filter((w) => !STOP_WORDS.has(w));
    if (!criteriaKw.length) return [100.0, null, "No criteria keywords to match"];

    const outputSet = new Set(outputKw);
    const stemsMatch = (kw: string) => {
      const stem = kw.slice(0, 5);
      return outputSet.has(kw) || outputKw.some((w) => w.startsWith(stem) || kw.startsWith(w.slice(0, 5)));
    };
    const matched = criteriaKw.filter(stemsMatch).length;
    const overlap = matched / criteriaKw.length;
    const score = Math.min(100.0, overlap * 150.0);
    const detail = `Heuristic: ${matched}/${criteriaKw.length} criteria keywords matched (stem)`;
    return [score, score < 50.0 ? FailureKind.UNKNOWN : null, detail];
  }
}

/** Score one case against its trace (Python `compute_case_result`). */
export function computeCaseResult(evalCase: EvalCase, trace: Trace, extraMetrics: Metric[] = []): CaseResult {
  const metrics: Metric[] = [
    new TaskCompletionMetric(),
    new ToolAccuracyMetric(),
    new LatencyMetric(),
    new HallucinationMetric(),
  ];
  if (evalCase.judge === "llm") metrics.push(new JudgeHeuristicMetric());
  metrics.push(...extraMetrics);

  const scores: number[] = [];
  let failureKind: string | null = null;
  let failureDetail: string | null = null;
  for (const metric of metrics) {
    const [s, fk, fd] = metric.score(evalCase, trace);
    scores.push(s);
    if (s < 100.0 && failureKind === null) {
      failureKind = fk;
      failureDetail = fd;
    }
  }

  const finalScore = scores.reduce((a, b) => a + b, 0) / scores.length;
  const [taskScore] = new TaskCompletionMetric().score(evalCase, trace);
  const [toolScore] = new ToolAccuracyMetric().score(evalCase, trace);
  const [latencyScore] = new LatencyMetric().score(evalCase, trace);

  return {
    case_id: evalCase.id,
    passed: finalScore >= 80.0,
    score: pyRound(finalScore, 1),
    task_completion: taskScore >= 80.0,
    tool_accuracy: pyRound(toolScore, 1),
    latency_ms: trace.total_latency_ms,
    latency_ok: latencyScore >= 80.0,
    failure_kind: failureKind,
    failure_detail: failureDetail,
    trace,
    // the offline judge heuristic makes no LLM call, so there is no judge usage to report
    judge_cost_usd: null,
    judge_tokens_in: null,
    judge_tokens_out: null,
  };
}
