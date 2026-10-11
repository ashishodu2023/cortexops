import { spawnSync } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { main, parseAgentSpec } from "../src/cli/main.js";
import { VERSION } from "../src/version.js";
import { GOLDEN_YAML, PAYMENTS_AGENT, isolateEnv, jsonResponse, mockFetch } from "./helpers.js";

const DIST_CLI = join(PAYMENTS_AGENT, "..", "..", "dist", "cli.js");
// Inside the package root: vitest only imports modules from within its workspace.
const TMP_ROOT = join(PAYMENTS_AGENT, "..", "..", "test", ".tmp");

let dir: string;

function agentFile(name: string, source: string): string {
  const path = join(dir, name);
  writeFileSync(path, source);
  return path;
}

async function run(args: string[], extra: { fetch?: any } = {}) {
  let stdout = "";
  let stderr = "";
  const code = await main(args, { stdout: (s) => (stdout += s), stderr: (s) => (stderr += s), cwd: dir, ...extra });
  return { code, stdout, stderr };
}

beforeEach(() => {
  isolateEnv();
  mkdirSync(TMP_ROOT, { recursive: true });
  dir = mkdtempSync(join(TMP_ROOT, "cli-"));
  agentFile(
    "agents.mjs",
    `import good from ${JSON.stringify(pathToFileURL(PAYMENTS_AGENT).href)};
export default good;
export const regressed = async (inp) => {
  const res = await good.invoke(inp);
  return { output: res.output.replace("escalated", "noted"), tool_calls_made: res.tool_calls_made };
};
export const broken = async (inp) => (/charge|deliver/.test(inp.input) ? {} : good.invoke(inp));
export const notAnAgent = 42;
export const factory = Promise.resolve(good);
export const buildIt = async () => good;
`,
  );
});

describe("cortexops-js CLI", () => {
  it("prints version and help", async () => {
    expect((await run(["version"])).stdout).toBe(`cortexops-js ${VERSION}\n`);
    expect((await run(["--version"])).code).toBe(0);
    const help = await run(["--help"]);
    expect(help.code).toBe(0);
    expect(help.stdout).toContain("eval run");
    expect((await run([])).code).toBe(0);
  });

  it("exits 2 on usage errors", async () => {
    const cases: Array<[string[], string]> = [
      [["bogus"], "Unknown command"],
      [["eval", "run", "--agent", "agents.mjs"], "--dataset is required"],
      [["eval", "run", "--dataset", GOLDEN_YAML], "--agent is required"],
      [["eval", "run", "--dataset", GOLDEN_YAML, "--agent", "agents.mjs", "--fail-on", "latency < 1"], "Unknown metric"],
      [["eval", "run", "--dataset", GOLDEN_YAML, "--agent", "agents.mjs", "--fail-on", "nonsense"], "Invalid fail_on"],
      [["eval", "run", "--dataset", "missing.yaml", "--agent", "agents.mjs"], "Dataset not found"],
      [["eval", "run", "--dataset", GOLDEN_YAML, "--agent", "nope.mjs"], "Could not load agent module"],
      [["eval", "run", "--dataset", GOLDEN_YAML, "--agent", "agents.mjs#missing"], "no export named 'missing'"],
      [["eval", "run", "--dataset", GOLDEN_YAML, "--agent", "agents.mjs#notAnAgent"], "is not a function"],
      [["eval", "run", "--dataset", GOLDEN_YAML, "--agent", "agents.mjs#notAnAgent()"], "Agent factory 'notAnAgent'"],
      [["eval", "run", "--dataset", GOLDEN_YAML, "--agent", "agents.mjs#"], "missing export name"],
      [["eval", "run", "--dataset", GOLDEN_YAML, "--agent", "agents.mjs", "--push"], "--push needs an API key"],
      [["eval", "run", "--dataset", GOLDEN_YAML, "--agent", "agents.mjs", "--wat"], "Unknown option: --wat"],
      [["eval", "run", "--dataset"], "--dataset requires a value"],
    ];
    for (const [args, message] of cases) {
      const res = await run(args);
      expect(res.code, args.join(" ")).toBe(2);
      expect(res.stderr).toContain(message);
    }
  });

  it("exits 0 when the gate passes and prints Python-style progress", async () => {
    const res = await run(["eval", "run", "-d", GOLDEN_YAML, "-a", "./agents.mjs", "--fail-on", "task_completion < 0.90"]);
    expect(res.code).toBe(0);
    expect(res.stdout).toContain("[1/9] refund_approved_01 ... pass (100)");
    expect(res.stdout).toContain("Cases           : 9  (9 passed, 0 failed)");
    expect(res.stdout).toContain("gate passed: task_completion < 0.90 (actual 1.000)");
    expect(res.stderr).toBe("");
  });

  it("parses file, file#name, file:name and factory () agent specs", () => {
    expect(parseAgentSpec("./agent.mjs")).toEqual({ file: "./agent.mjs", call: false });
    expect(parseAgentSpec("./agent.mjs#myAgent")).toEqual({ file: "./agent.mjs", exportName: "myAgent", call: false });
    expect(parseAgentSpec("agent.js:buildAgent()")).toEqual({ file: "agent.js", exportName: "buildAgent", call: true });
    expect(parseAgentSpec("C:\\agents\\agent.mjs")).toEqual({ file: "C:\\agents\\agent.mjs", call: false });
    expect(parseAgentSpec("C:\\agents\\agent.mjs:agent")).toEqual({ file: "C:\\agents\\agent.mjs", exportName: "agent", call: false });
  });

  it("exits 1 when a gate trips and still writes JSON, Markdown and the job summary", async () => {
    const stepSummary = join(dir, "step-summary.md");
    writeFileSync(stepSummary, "existing\n");
    vi.stubEnv("GITHUB_STEP_SUMMARY", stepSummary);
    const res = await run([
      "eval", "run",
      "--dataset", GOLDEN_YAML,
      "--agent", "agents.mjs#regressed",
      "--fail-on", "task_completion < 0.90",
      "--fail-on", "tool_accuracy < 0.5, pass_rate < 0.5",
      "--json", "out/results.json",
      "--summary-md", "out/summary.md",
      "--title", "Payments gate",
      "--quiet",
    ]);
    expect(res.code).toBe(1);
    expect(res.stderr).toContain("CI gate FAILED: Eval gate failed: task_completion=0.667 < 0.9 (project=payments-agent)");
    expect(res.stdout).not.toContain("[1/9]");
    expect(res.stdout).toContain("gate FAILED: task_completion < 0.90");
    expect(res.stdout).toContain("gate passed: tool_accuracy < 0.5");

    const json = JSON.parse(readFileSync(join(dir, "out/results.json"), "utf8"));
    // every case still scores >= 80, but task completion regressed: only the gate catches it
    expect(json).toMatchObject({
      schema_version: 1,
      generator: "cortexops-js",
      gate_passed: false,
      dataset_path: GOLDEN_YAML,
      pass_rate: 1,
      mean_score: expect.any(Number),
      project: "payments-agent",
      total_cases: 9,
      passed: 9,
      failed: 0,
      task_completion_rate: 6 / 9,
    });
    expect(json.thresholds).toEqual([
      { expression: "task_completion < 0.90", metric: "task_completion", op: "<", threshold: 0.9, actual: 6 / 9, failed: true },
      { expression: "tool_accuracy < 0.5", metric: "tool_accuracy", op: "<", threshold: 0.5, actual: 1, failed: false },
      { expression: "pass_rate < 0.5", metric: "pass_rate", op: "<", threshold: 0.5, actual: 1, failed: false },
    ]);
    expect(json.case_results).toHaveLength(9);
    expect(json.case_results[0]).not.toHaveProperty("trace");

    const md = readFileSync(join(dir, "out/summary.md"), "utf8");
    expect(md).toMatch(/^## Payments gate: FAILED\n/);
    expect(md).toContain("| `task_completion < 0.90` | 0.667 | FAILED |");
    expect(md).toContain("| `tool_accuracy < 0.5` | 1.000 | ok |");
    expect(md).toContain("_All cases passed._");
    expect(readFileSync(stepSummary, "utf8")).toBe(`existing\n${md}\n`);
    expect(res.stdout).toContain("Markdown summary appended to GITHUB_STEP_SUMMARY");
  });

  it("without --fail-on, the default gate is pass_rate < 1.0 (any failed case fails the run)", async () => {
    const stepSummary = join(dir, "step-summary.md");
    vi.stubEnv("GITHUB_STEP_SUMMARY", stepSummary);
    const res = await run([
      "eval", "run", "--dataset", GOLDEN_YAML, "--agent", "agents.mjs#broken",
      "--summary-md", "s.md", "--junit-xml", "junit.xml", "--output", "raw.json", "--no-step-summary", "-q",
    ]);
    expect(res.code).toBe(1);
    expect(res.stdout).toContain("fail-on : pass_rate < 1.0");
    expect(existsSync(stepSummary)).toBe(false);
    const md = readFileSync(join(dir, "s.md"), "utf8");
    expect(md).toMatch(/^## CortexOps eval gate: FAILED\n\nProject `payments-agent`, dataset `.+golden_v1.yaml` \(v1\), run `[0-9a-f]{8}`\n/);
    expect(md).toContain("| `pass_rate < 1.0` | 0.667 | FAILED |");
    expect(md).toContain("### Failed cases (3)");
    expect(md).toContain("| `dispute_duplicate_charge_01` | unknown | 50 | Agent produced no output |");
    expect(md).toMatch(/<sub>Generated by cortexops-js \d+\.\d+\.\d+<\/sub>\n$/);

    const junit = readFileSync(join(dir, "junit.xml"), "utf8");
    expect(junit).toMatch(/^<\?xml version="1.0" encoding="UTF-8"\?>\n<testsuites name="cortexops" tests="10" failures="4">\n/);
    expect(junit).toContain('<testsuite name="cortexops.payments-agent" tests="9" failures="3" errors="0"');
    expect(junit).toContain('<failure type="unknown" message="score 50: unknown">Agent produced no output</failure>');
    expect(junit).toContain('<testcase classname="cortexops.thresholds" name="fail_on: pass_rate &lt; 1.0" time="0">');
    expect(junit).toContain('<failure type="threshold" message="pass_rate=0.667 &lt; 1.0" />');

    const raw = JSON.parse(readFileSync(join(dir, "raw.json"), "utf8"));
    expect(raw.case_results[0].trace).toMatchObject({ project: "eval", case_id: "refund_approved_01" });
  });

  it("loads promised agents, factories and file:name specs", async () => {
    expect((await run(["eval", "run", "--dataset", GOLDEN_YAML, "--agent", "agents.mjs#factory", "-q"])).code).toBe(0);
    expect((await run(["eval", "run", "--dataset", GOLDEN_YAML, "--agent", "agents.mjs#buildIt()", "-q"])).code).toBe(0);
    expect((await run(["eval", "run", "--dataset", GOLDEN_YAML, "--agent", "agents.mjs:buildIt()", "-q"])).code).toBe(0);
  });

  it("--project overrides the dataset project", async () => {
    const res = await run(["eval", "run", "--dataset", GOLDEN_YAML, "--agent", "agents.mjs", "--project", "other", "--json", "r.json", "-q"]);
    expect(res.code).toBe(0);
    expect(JSON.parse(readFileSync(join(dir, "r.json"), "utf8")).project).toBe("other");
  });

  it("--push uploads the summary to the project bound to the key", async () => {
    const { fetch, requests } = mockFetch((req) =>
      req.url.endsWith("/v1/traces/quota") ? jsonResponse({ project: "key-project" }) : jsonResponse({ run_id: req.body.run_id, project: req.body.project }, 201),
    );
    const res = await run(
      ["eval", "run", "--dataset", GOLDEN_YAML, "--agent", "agents.mjs", "--push", "--api-key", "cxo-k", "--base-url", "http://api.test", "-q"],
      { fetch },
    );
    expect(res.code).toBe(0);
    expect(res.stdout).toContain("Note: API key is for project 'key-project'");
    expect(res.stdout).toMatch(/Eval pushed to CortexOps \(run_id=[0-9a-f-]{36}, project=key-project\)/);
    const ingest = requests.find((r) => r.url === "http://api.test/v1/evals/ingest")!;
    expect(ingest.headers["x-api-key"]).toBe("cxo-k");
    expect(ingest.body).toMatchObject({ project: "key-project", total_cases: 9, dataset: { name: "golden_v1" } });
    expect(ingest.body.dataset.cases).toHaveLength(9);
    expect(ingest.body.case_results[0]).not.toHaveProperty("trace");
  });

  it("a failed push warns but does not change the exit code", async () => {
    vi.stubEnv("CORTEXOPS_API_KEY", "cxo-env");
    const { fetch } = mockFetch(() => jsonResponse({ detail: "Forbidden" }, 403));
    const res = await run(["eval", "run", "--dataset", GOLDEN_YAML, "--agent", "agents.mjs", "--push", "--project", "x", "-q"], { fetch });
    expect(res.code).toBe(0);
    expect(res.stderr).toContain("Warning: eval push failed");
    expect(res.stderr).toContain("HTTP 403");
  });

  describe.skipIf(!existsSync(DIST_CLI))("built binary (dist/cli.js)", () => {
    it("runs as a real process with correct exit codes", () => {
      const env = { ...process.env, GITHUB_STEP_SUMMARY: "", CORTEXOPS_API_KEY: "" };
      const ok = spawnSync(process.execPath, [DIST_CLI, "eval", "run", "--dataset", GOLDEN_YAML, "--agent", "agents.mjs", "--fail-on", "task_completion < 0.9", "-q"], { cwd: dir, env, encoding: "utf8" });
      expect(ok.status, ok.stderr).toBe(0);
      const bad = spawnSync(process.execPath, [DIST_CLI, "eval", "run", "--dataset", GOLDEN_YAML, "--agent", "agents.mjs#regressed", "--fail-on", "task_completion < 0.9", "-q"], { cwd: dir, env, encoding: "utf8" });
      expect(bad.status).toBe(1);
      expect(bad.stderr).toContain("CI gate FAILED");
      const usage = spawnSync(process.execPath, [DIST_CLI, "eval", "run"], { cwd: dir, env, encoding: "utf8" });
      expect(usage.status).toBe(2);
    });
  });
});
