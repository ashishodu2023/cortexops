import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { beforeEach, describe, expect, it } from "vitest";
import {
  CortexTracer,
  EvalSuite,
  EvalThresholdError,
  checkThresholds,
  evalGate,
  createEvalCase,
  formatSummary,
  loadDataset,
  normalizeAgentOutput,
  parseDataset,
  parseFailOn,
  parseThreshold,
  summarize,
  type CaseResult,
  type EvalDataset,
  type EvalSummary,
} from "../src/index.js";
import { GOLDEN_YAML, isolateEnv, loadParity, sleep } from "./helpers.js";
// @ts-expect-error -- plain ESM example without type declarations
import paymentsAgent, { buildAgent } from "../examples/payments-agent.mjs";

const parity = loadParity();

beforeEach(() => {
  isolateEnv();
});

function twoCaseDataset(): EvalDataset {
  return {
    version: 1,
    project: "test-agent",
    description: "",
    cases: [
      createEvalCase({ id: "case_01", input: "What is 2+2?", expected_output_contains: ["4"] }),
      createEvalCase({ id: "case_02", input: "Say hello", expected_output_contains: ["hello"] }),
    ],
  };
}

describe("port of sdk/tests/test_evaluation.py, test_regressions.py, test_eval_suite.py", () => {
  it("passes a good agent", async () => {
    const agent = (inp: Record<string, unknown>) =>
      String(inp.input).includes("2+2") ? { output: "The answer is 4" } : { output: "hello there" };
    const summary = await EvalSuite.run(twoCaseDataset(), agent, { verbose: false });
    expect(summary.total_cases).toBe(2);
    expect(summary.passed).toBe(2);
    expect(summary.task_completion_rate).toBe(1.0);
  });

  it("throws EvalThresholdError when the gate trips", async () => {
    const bad = () => ({ output: "nothing useful" });
    await expect(EvalSuite.run(twoCaseDataset(), bad, { verbose: false, failOn: "task_completion < 0.5" })).rejects.toBeInstanceOf(
      EvalThresholdError,
    );
    const ds = { version: 1, project: "reg", description: "", cases: [createEvalCase({ id: "c1", input: "hi", expected_output_contains: ["hello"] })] };
    const err = await EvalSuite.run(ds, () => ({ output: "nope" }), { verbose: false, failOn: "task_completion < 0.9" }).catch((e) => e);
    expect(err).toBeInstanceOf(EvalThresholdError);
    expect(err.message).toBe("Eval gate failed: task_completion=0.000 < 0.9 (project=reg)");
    expect(err.summary.total_cases).toBe(1);
    expect(err.failures).toHaveLength(1);
  });

  it("renders the summary", async () => {
    const ds = { version: 1, project: "test-agent", description: "", cases: [createEvalCase({ id: "c1", input: "hi", expected_output_contains: ["hi"] })] };
    const summary = await EvalSuite.run(ds, (inp: Record<string, unknown>) => ({ output: inp.input }), { verbose: false });
    const text = formatSummary(summary);
    expect(text).toContain("test-agent");
    expect(text).toContain("Task completion");
  });

  it("prints progress like Python when verbose", async () => {
    let out = "";
    await EvalSuite.run(twoCaseDataset(), () => ({ output: "4 hello" }), { write: (s) => (out += s) });
    expect(out).toContain("  [1/2] case_01 ... pass (100)\n");
    expect(out).toContain("  [2/2] case_02 ... pass (100)\n");
    expect(out).toContain("CortexOps eval — test-agent");
  });
});

describe("golden dataset parity: examples/langgraph_payments/golden_v1.yaml", () => {
  it("JS port of the payments agent produces the same outputs and case results as Python", async () => {
    const summary = await EvalSuite.run(GOLDEN_YAML, paymentsAgent, { verbose: false });
    const expected = parity.golden;
    expect({
      project: summary.project,
      dataset_version: summary.dataset_version,
      total_cases: summary.total_cases,
      passed: summary.passed,
      failed: summary.failed,
      warnings: summary.warnings,
      task_completion_rate: summary.task_completion_rate,
      tool_accuracy: summary.tool_accuracy,
    }).toEqual(expected.summary);
    for (const r of summary.case_results) {
      expect(r.trace!.output).toEqual(expected.outputs[r.case_id]);
    }
    const comparable = summary.case_results.map(({ trace: _t, latency_ms: _l, ...rest }) => rest);
    expect(comparable).toEqual(expected.case_results);
  });

  it("gates the golden dataset with the same expression as the repo's CI", async () => {
    const summary = await EvalSuite.run(GOLDEN_YAML, paymentsAgent, { verbose: false, failOn: "task_completion < 0.85" });
    expect(summary.failed).toBe(0);
  });

  it("counts instrumented tool calls even when the agent does not self-report them", async () => {
    const tracer = new CortexTracer({ project: "payments-agent" });
    const inner = buildAgent({ tracer });
    const agent = async (inp: Record<string, unknown>) => {
      const { output } = await inner.invoke(inp);
      return { output };
    };
    const summary = await EvalSuite.run(GOLDEN_YAML, agent, { verbose: false });
    expect(summary.tool_accuracy).toBe(100);
    expect(summary.passed).toBe(9);
    const dispute = summary.case_results.find((r) => r.case_id === "dispute_unauthorized_01")!;
    expect(dispute.trace!.nodes[0]!.tool_calls.map((tc) => tc.name)).toEqual(["classify_dispute", "route_escalation"]);
  });

  it("detects a regression (agent that skips escalation)", async () => {
    const regressed = async (inp: Record<string, unknown>) => {
      const res = await paymentsAgent.invoke(inp);
      return { ...res, tool_calls_made: res.tool_calls_made.filter((t: string) => t !== "route_escalation") };
    };
    const err = await EvalSuite.run(GOLDEN_YAML, regressed, { verbose: false, failOn: ["tool_accuracy < 0.95", "pass_rate < 0.5"] }).catch(
      (e) => e,
    );
    expect(err).toBeInstanceOf(EvalThresholdError);
    expect(err.failures.map((f: any) => f.metric)).toEqual(["tool_accuracy"]);
    expect(err.summary.tool_accuracy).toBeCloseTo((6 * 100 + 3 * 50) / 9, 10);
  });
});

describe("thresholds", () => {
  const makeSummary = ([passed, total, tc, tool]: number[]): EvalSummary => ({
    ...summarize({ version: 1, project: "gate-proj", description: "", cases: [] }, []),
    project: "gate-proj",
    total_cases: total!,
    passed: passed!,
    failed: total! - passed!,
    task_completion_rate: tc!,
    tool_accuracy: tool!,
  });

  for (const g of parity.gates.results) {
    it(`${JSON.stringify(g.summary)} ${g.expression}`, () => {
      const [result] = checkThresholds(makeSummary(g.summary), [g.expression]);
      expect(result!.failed).toBe(g.failed);
      if (g.failed) expect(result!.message).toBe(g.message);
    });
  }

  for (const inv of parity.gates.invalid) {
    it(`rejects '${inv.expression}' like Python`, () => {
      expect(() => parseThreshold(inv.expression)).toThrow(inv.error);
    });
  }

  it("accepts multiple expressions (array, comma, semicolon, newline)", () => {
    expect(parseFailOn(["task_completion < 0.9", "pass_rate < 1, tool_accuracy<=0.5; task_completion < .5\n"]).map((t) => t.expression)).toEqual([
      "task_completion < 0.9",
      "pass_rate < 1",
      "tool_accuracy<=0.5",
      "task_completion < .5",
    ]);
    expect(parseFailOn(undefined)).toEqual([]);
  });

  it("validates expressions before running the agent", async () => {
    let calls = 0;
    await expect(EvalSuite.run(twoCaseDataset(), () => calls++, { verbose: false, failOn: "latency < 3" })).rejects.toThrow(
      "Unknown metric in fail_on: 'latency'",
    );
    expect(calls).toBe(0);
  });
});

describe("summary arithmetic", () => {
  for (const p of parity.percentiles) {
    it(`p50/p95 for n=${p.latencies.length}`, () => {
      const results = p.latencies.map(
        (latency: number, i: number): CaseResult => ({
          case_id: `c${i}`,
          passed: true,
          score: 100,
          task_completion: true,
          tool_accuracy: 100,
          latency_ms: latency,
          latency_ok: true,
          failure_kind: null,
          failure_detail: null,
          trace: null,
        }),
      );
      const s = summarize({ version: 1, project: "p", description: "", cases: [] }, results);
      expect(s.latency_p50_ms).toBe(p.p50);
      expect(s.latency_p95_ms).toBe(p.p95);
    });
  }

  it("empty dataset", async () => {
    const s = await EvalSuite.run({ project: "p", cases: [] }, () => "x", { verbose: false });
    expect(s).toMatchObject({ total_cases: 0, passed: 0, task_completion_rate: 0, tool_accuracy: 0, latency_p50_ms: 0, latency_p95_ms: 0 });
  });

  it("formats the summary like Python EvalSummary.summary()", () => {
    const { summary, text } = parity.summary_text;
    const s: EvalSummary = { ...summary, case_results: summary.case_results.map((r: any) => ({ ...r, trace: null })) };
    // Python renders the enum as "FailureKind.UNKNOWN"; the JS SDK prints the value.
    expect(formatSummary(s)).toBe(text.replace("FailureKind.UNKNOWN", "unknown"));
  });
});

describe("agents and outputs", () => {
  it("supports sync, async and .invoke() agents, and string inputs vs mapping inputs", async () => {
    const seen: unknown[] = [];
    const ds = parseDataset({
      project: "p",
      cases: [
        { id: 1, input: "plain" },
        { id: "two", input: { input: "mapped", extra: 1 } },
      ],
    });
    await EvalSuite.run(ds, (inp: unknown) => (seen.push(inp), "ok"), { verbose: false });
    await EvalSuite.run(ds, { invoke: async (inp: unknown) => (seen.push(inp), "ok") }, { verbose: false });
    expect(seen).toEqual([{ input: "plain" }, { input: "mapped", extra: 1 }, { input: "plain" }, { input: "mapped", extra: 1 }]);
  });

  it("records agent exceptions as failed traces", async () => {
    const ds = parseDataset({ project: "p", cases: [{ id: "c", input: "x" }] });
    const s = await EvalSuite.run(ds, async () => {
      await sleep(1);
      throw new Error("kaput");
    }, { verbose: false });
    expect(s.case_results[0]).toMatchObject({ passed: false, score: 75, failure_kind: "unknown", failure_detail: "Agent produced no output" });
    expect(s.case_results[0]!.trace).toMatchObject({ status: "failed", failure_detail: "kaput", output: {} });
    const notCallable = await EvalSuite.run(ds, 42, { verbose: false });
    expect(notCallable.case_results[0]!.trace!.failure_detail).toBe("Agent Number is not callable");
  });

  it("normalizes agent outputs", () => {
    class GenerateTextResult {
      get text() {
        return "from ai sdk";
      }
    }
    class RunResult {
      finalOutput = { answer: 42 };
    }
    expect(normalizeAgentOutput({ output: "x", tool_calls_made: ["a"] })).toEqual({ output: "x", tool_calls_made: ["a"] });
    expect(normalizeAgentOutput("text")).toEqual({ output: "text" });
    expect(normalizeAgentOutput(null)).toEqual({ output: "None" });
    expect(normalizeAgentOutput(["a", 1])).toEqual({ output: "['a', 1]" });
    expect(normalizeAgentOutput(new GenerateTextResult())).toEqual({ output: "from ai sdk" });
    expect(normalizeAgentOutput(new RunResult())).toEqual({ output: "{'answer': 42}" });
  });
});

describe("dataset loading", () => {
  const dir = mkdtempSync(join(tmpdir(), "cortexops-ds-"));

  it("loads YAML with Python (YAML 1.1) semantics and JSON", async () => {
    const yamlPath = join(dir, "d.yaml");
    writeFileSync(yamlPath, "project: p\nversion: '2'\ncases:\n  - id: 7\n    input: yes\n    tags: [a]\n");
    await expect(loadDataset(yamlPath)).rejects.toThrow("input must be a string or a mapping");
    writeFileSync(yamlPath, "project: p\nversion: '2'\ncases:\n  - id: 7\n    input: 'yes'\n    expected_output_contains: [on]\n");
    const ds = await loadDataset(yamlPath);
    expect(ds.version).toBe(2);
    expect(ds.cases[0]).toMatchObject({ id: "7", input: "yes", expected_output_contains: ["true"] });

    const jsonPath = join(dir, "d.json");
    writeFileSync(jsonPath, JSON.stringify({ project: "j", cases: [{ id: "a", input: { q: 1 }, max_latency_ms: 5 }] }));
    expect((await loadDataset(jsonPath)).cases[0]).toMatchObject({ id: "a", input: { q: 1 }, max_latency_ms: 5 });
  });

  it("reports missing files and malformed cases", async () => {
    await expect(loadDataset(join(dir, "missing.yaml"))).rejects.toThrow(/Dataset not found/);
    expect(() => parseDataset({ cases: [{ input: "x" }] })).toThrow("missing 'id'");
    expect(() => parseDataset({ cases: [{ id: "x" }] })).toThrow("missing 'input'");
    expect(() => parseDataset({ version: "1.0.0", cases: [] })).toThrow("dataset version must be an integer");
    expect(parseDataset({ cases: [] })).toMatchObject({ project: "unknown", version: 1, description: "" });
  });
});

describe("evalGate (test-runner helper, like @cortexops.eval_gate)", () => {
  it("resolves with the summary when the default gate (pass_rate < 1.0) holds; accepts file URLs", async () => {
    const summary = await evalGate(pathToFileURL(GOLDEN_YAML), paymentsAgent);
    expect(summary).toMatchObject({ project: "payments-agent", total_cases: 9, passed: 9 });
  });

  it("rejects with every tripped condition followed by the summary", async () => {
    const regressed = async (inp: any) => {
      const res = await paymentsAgent.invoke(inp);
      return /charge|deliver/.test(inp.input) ? {} : res;
    };
    const err = await evalGate(GOLDEN_YAML, regressed, { failOn: ["task_completion < 0.9", "tool_accuracy < 0.5", "pass_rate < 1"] }).catch((e) => e);
    expect(err).toBeInstanceOf(EvalThresholdError);
    expect(err.failures.map((f: any) => f.metric)).toEqual(["task_completion", "pass_rate"]);
    expect(err.message).toBe(
      "Eval gate failed: task_completion=0.667 < 0.9 (project=payments-agent)\n" +
        "Eval gate failed: pass_rate=0.667 < 1.0 (project=payments-agent)\n\n" +
        formatSummary(err.summary),
    );
    await expect(evalGate(GOLDEN_YAML, regressed, { failOn: null })).resolves.toMatchObject({ failed: 3 });
  });

  it("validates expressions before running the agent", async () => {
    let calls = 0;
    await expect(evalGate(GOLDEN_YAML, () => calls++, { failOn: "latency < 1" })).rejects.toThrow("Unknown metric in fail_on: 'latency'");
    expect(calls).toBe(0);
  });
});
