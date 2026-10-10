import { describe, expect, it } from "vitest";
import {
  FailureKind,
  HallucinationMetric,
  JudgeHeuristicMetric,
  LatencyMetric,
  TaskCompletionMetric,
  ToolAccuracyMetric,
  computeCaseResult,
  createEvalCase,
  type EvalCase,
} from "../src/index.js";
import { pyRepr, pyRound } from "../src/pyfmt.js";
import { loadParity, makeTrace } from "./helpers.js";

const parity = loadParity();

describe("port of sdk/tests/test_metrics.py", () => {
  it("task completion", () => {
    const c = createEvalCase({ id: "c1", input: "test", expected_output_contains: ["approved", "REF-8821"] });
    const [score, fk] = new TaskCompletionMetric().score(c, makeTrace({ output: "Refund REF-8821 was approved successfully" }));
    expect(score).toBe(100.0);
    expect(fk).toBeNull();
  });

  it("latency metric", () => {
    const m = new LatencyMetric();
    const c = createEvalCase({ id: "c1", input: "test", max_latency_ms: 1000 });
    const [good] = m.score(c, makeTrace({}, [], 200));
    const [bad, fk] = m.score(c, makeTrace({}, [], 2000));
    expect(good).toBe(100.0);
    expect(bad).toBeLessThan(100.0);
    expect(fk).toBe(FailureKind.TIMEOUT);
  });

  it("tool accuracy", () => {
    const m = new ToolAccuracyMetric();
    const c = createEvalCase({ id: "c1", input: "test", expected_tool_calls: ["lookup_refund", "send_email"] });
    expect(m.score(c, makeTrace({}, ["lookup_refund", "send_email"]))[0]).toBe(100.0);
    const [partial, fk, fd] = m.score(c, makeTrace({}, ["lookup_refund"]));
    expect(partial).toBe(50.0);
    expect(fk).toBe(FailureKind.TOOL_CALL_MISMATCH);
    expect(fd).toContain("send_email");
  });
});

describe("parity with the Python SDK metrics (fixtures from scripts/gen_parity_fixtures.py)", () => {
  const matrix: any[] = parity.metric_matrix;

  it("covers a meaningful matrix", () => {
    expect(matrix.length).toBeGreaterThan(40);
  });

  for (const entry of matrix) {
    const c: EvalCase = { ...entry.case };
    const label = `${c.id}: ${JSON.stringify(entry.output).slice(0, 60)} tools=${entry.tool_calls.join(",")} latency=${entry.latency_ms}`;
    it(label, () => {
      const trace = makeTrace(entry.output, entry.tool_calls, entry.latency_ms);
      expect(new TaskCompletionMetric().score(c, trace)).toEqual(entry.metrics.task_completion);
      expect(new ToolAccuracyMetric().score(c, trace)).toEqual(entry.metrics.tool_accuracy);
      expect(new LatencyMetric().score(c, trace)).toEqual(entry.metrics.latency);
      expect(new HallucinationMetric().score(c, trace)).toEqual(entry.metrics.hallucination);
      if (entry.metrics.llm_judge) {
        expect(new JudgeHeuristicMetric().score(c, trace)).toEqual(entry.metrics.llm_judge);
      }
      const result = computeCaseResult(c, trace);
      const { trace: _t, latency_ms: _l, ...comparable } = result;
      expect(comparable).toEqual(entry.result);
    });
  }
});

describe("Python formatting helpers", () => {
  it("pyRound uses round-half-even on exact ties", () => {
    expect(pyRound(6.25, 1)).toBe(6.2);
    expect(pyRound(6.35, 1)).toBe(6.3); // 6.35 is 6.3499999... in binary
    expect(pyRound(93.75, 1)).toBe(93.8);
    expect(pyRound(93.65, 1)).toBe(93.7);
    expect(pyRound(0.5)).toBe(0);
    expect(pyRound(1.5)).toBe(2);
    expect(pyRound(2.5)).toBe(2);
    expect(pyRound(66.66666666666667, 1)).toBe(66.7);
  });

  it("pyRepr matches Python repr for JSON-like values", () => {
    expect(pyRepr(["a", "it's", 'say "hi"', 1, null, true, false])).toBe(`['a', "it's", 'say "hi"', 1, None, True, False]`);
    expect(pyRepr({ status: "ok", n: [1, { x: "y" }] })).toBe("{'status': 'ok', 'n': [1, {'x': 'y'}]}");
    expect(pyRepr("line\nbreak\\")).toBe("'line\\nbreak\\\\'");
  });
});
