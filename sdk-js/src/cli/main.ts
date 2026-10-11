import { appendFile, mkdir, writeFile } from "node:fs/promises";
import { dirname, isAbsolute, resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { CortexClient } from "../client.js";
import { resolveApiKey } from "../config.js";
import { DEFAULT_FAIL_ON, EvalSuite, checkThresholds, loadDataset, parseFailOn, type GateResult, type Threshold } from "../eval.js";
import { formatSummary, type EvalDataset, type EvalSummary } from "../models.js";
import { fixed } from "../pyfmt.js";
import { buildReport, renderJunit, renderMarkdown } from "../report.js";
import type { FetchLike } from "../tracer.js";
import { VERSION } from "../version.js";

export interface CliIO {
  stdout: (text: string) => void;
  stderr: (text: string) => void;
  cwd: string;
  fetch?: FetchLike;
}

const HELP = `cortexops-js ${VERSION} - CortexOps CLI for JavaScript / TypeScript agents

Usage:
  cortexops-js eval run --dataset <golden.yaml> --agent <./agent.mjs[#export]> [options]
  cortexops-js version

eval run options:
  -d, --dataset <path>      Golden dataset (YAML or JSON, same format as the Python SDK)
  -a, --agent <spec>        Module exporting the agent: ./agent.mjs (default export, or an
                            export named "agent"), ./agent.mjs#name or ./agent.mjs:name.
                            Append () to call a factory: ./agent.mjs#buildAgent().
                            The agent is a function (input) => output, or an object with
                            .invoke()
      --fail-on <expr>      Gate condition, e.g. "task_completion < 0.90"; the run fails
                            when any condition is true. Repeatable; also accepts several
                            expressions separated by commas or newlines. Metrics (0-1):
                            task_completion, tool_accuracy, pass_rate.
                            Default: "${DEFAULT_FAIL_ON}" (every case must pass)
  -p, --project <name>      Override the dataset project
      --output-json <path>  Write the JSON report (schema_version 1, same as the Python
                            CLI; alias: --json)
  -o, --output <path>       Write the raw summary JSON, including per-case traces
      --summary-md <path>   Write a markdown report
      --junit-xml <path>    Write a JUnit XML report (one testcase per case and gate)
      --title <text>        Heading for the markdown report (default: CortexOps eval gate)
      --no-step-summary     Do not append the markdown report to GITHUB_STEP_SUMMARY
      --push                Upload the summary to CortexOps (POST /v1/evals/ingest)
      --api-key <key>       API key for --push (default: CORTEXOPS_API_KEY or
                            ~/.cortexops/credentials)
      --api-url <url>       API base URL (alias: --base-url; default: CORTEXOPS_API_URL
                            or https://api.getcortexops.com)
  -q, --quiet               Hide per-case progress

Exit codes: 0 = gate passed, 1 = gate failed, 2 = usage or configuration error.
`;

type FlagSpec = Record<string, { type: "string" | "boolean" | "multi"; short?: string }>;

const EVAL_RUN_FLAGS: FlagSpec = {
  dataset: { type: "string", short: "d" },
  agent: { type: "string", short: "a" },
  "fail-on": { type: "multi" },
  project: { type: "string", short: "p" },
  "output-json": { type: "string" },
  json: { type: "string" },
  output: { type: "string", short: "o" },
  "summary-md": { type: "string" },
  "junit-xml": { type: "string" },
  title: { type: "string" },
  "no-step-summary": { type: "boolean" },
  push: { type: "boolean" },
  "api-key": { type: "string" },
  "api-url": { type: "string" },
  "base-url": { type: "string" },
  quiet: { type: "boolean", short: "q" },
  help: { type: "boolean", short: "h" },
};

class UsageError extends Error {}

type Flags = Record<string, string | boolean | string[] | undefined>;

function parseFlags(args: string[], spec: FlagSpec): Flags {
  const flags: Flags = {};
  const byShort = new Map(Object.entries(spec).filter(([, s]) => s.short).map(([name, s]) => [s.short!, name]));
  for (let i = 0; i < args.length; i++) {
    const arg = args[i]!;
    let name: string | undefined;
    let inline: string | undefined;
    if (arg.startsWith("--")) {
      const eq = arg.indexOf("=");
      name = eq === -1 ? arg.slice(2) : arg.slice(2, eq);
      inline = eq === -1 ? undefined : arg.slice(eq + 1);
    } else if (/^-[a-zA-Z]$/.test(arg)) {
      name = byShort.get(arg.slice(1));
      if (!name) throw new UsageError(`Unknown option: ${arg}`);
    } else {
      throw new UsageError(`Unexpected argument: ${arg}`);
    }
    const s = spec[name];
    if (!s) throw new UsageError(`Unknown option: --${name}`);
    if (s.type === "boolean") {
      if (inline !== undefined) throw new UsageError(`--${name} does not take a value`);
      flags[name] = true;
      continue;
    }
    const value = inline ?? args[++i];
    if (value === undefined) throw new UsageError(`--${name} requires a value`);
    if (s.type === "multi") flags[name] = [...((flags[name] as string[] | undefined) ?? []), value];
    else flags[name] = value;
  }
  return flags;
}

function str(flags: Flags, name: string): string | undefined {
  const v = flags[name];
  return typeof v === "string" ? v : undefined;
}

/** `file`, `file#name`, `file:name` (Python CLI style), each optionally with `()` for a factory. */
export function parseAgentSpec(spec: string): { file: string; exportName?: string; call: boolean } {
  let file = spec;
  let name: string | undefined;
  const hash = spec.lastIndexOf("#");
  const colon = /^(.*[^:\\/]):([A-Za-z_$][\w$]*(?:\(\))?)$/.exec(spec);
  if (hash > 0) {
    file = spec.slice(0, hash);
    name = spec.slice(hash + 1);
  } else if (colon) {
    file = colon[1]!;
    name = colon[2]!;
  }
  const call = name?.endsWith("()") ?? false;
  if (call) name = name!.slice(0, -2);
  if (name === "") throw new UsageError(`Invalid --agent '${spec}': missing export name`);
  return { file, call, ...(name ? { exportName: name } : {}) };
}

async function loadAgent(spec: string, cwd: string): Promise<unknown> {
  const { file, exportName, call } = parseAgentSpec(spec);
  const path = isAbsolute(file) ? file : resolve(cwd, file);
  let mod: Record<string, unknown>;
  try {
    mod = (await import(pathToFileURL(path).href)) as Record<string, unknown>;
  } catch (err) {
    throw new UsageError(`Could not load agent module ${path}: ${(err as Error).message}`);
  }
  const fallback = mod.default as Record<string, unknown> | undefined;
  let agent: unknown;
  if (exportName) {
    agent = mod[exportName] ?? (fallback && typeof fallback === "object" ? fallback[exportName] : undefined);
    if (agent === undefined) throw new UsageError(`Agent module ${file} has no export named '${exportName}'`);
  } else {
    agent = mod.default ?? mod.agent;
    if (agent === undefined) throw new UsageError(`Agent module ${file} has no default export (use ${file}#exportName)`);
  }
  agent = await agent;
  if (call) {
    if (typeof agent !== "function") throw new UsageError(`Agent factory '${exportName ?? "default"}' in ${file} is not a function`);
    agent = await (agent as () => unknown)();
  }
  const callable = typeof agent === "function" || (agent !== null && typeof (agent as { invoke?: unknown })?.invoke === "function");
  if (!callable) throw new UsageError(`Agent '${exportName ?? "default"}' in ${file} is not a function or an object with .invoke()`);
  return agent;
}

async function writeOutput(path: string, content: string, cwd: string): Promise<string> {
  const full = isAbsolute(path) ? path : resolve(cwd, path);
  await mkdir(dirname(full), { recursive: true });
  await writeFile(full, content, "utf8");
  return full;
}

function datasetSnapshot(ds: EvalDataset) {
  if (!ds.name || !ds.cases.length) return undefined;
  return { name: ds.name, description: ds.description.trim(), cases: ds.cases as unknown as Array<Record<string, unknown>> };
}

async function pushSummary(
  summary: EvalSummary,
  ds: EvalDataset,
  opts: { apiKey: string; apiUrl?: string; projectExplicit: boolean },
  io: CliIO,
): Promise<void> {
  const client = new CortexClient({ apiKey: opts.apiKey, ...(opts.apiUrl ? { baseUrl: opts.apiUrl } : {}), ...(io.fetch ? { fetch: io.fetch } : {}) });
  if (!opts.projectExplicit) {
    try {
      const keyProject = await client.projectForKey();
      if (keyProject && keyProject !== summary.project) {
        io.stdout(`\nNote: API key is for project '${keyProject}' (not '${summary.project}'); pushing there\n`);
        summary.project = keyProject;
      }
    } catch {
      // fall back to the dataset project
    }
  }
  try {
    const snapshot = datasetSnapshot(ds);
    const stored = await client.pushEval(summary, snapshot ? { dataset: snapshot } : {});
    io.stdout(`\nEval pushed to CortexOps (run_id=${stored.run_id}, project=${stored.project})\n`);
  } catch (err) {
    io.stderr(`\nWarning: eval push failed: ${(err as Error).message}\n`);
  }
}

async function evalRun(args: string[], io: CliIO): Promise<number> {
  const flags = parseFlags(args, EVAL_RUN_FLAGS);
  if (flags.help) {
    io.stdout(HELP);
    return 0;
  }
  const datasetPath = str(flags, "dataset");
  const agentSpec = str(flags, "agent");
  if (!datasetPath) throw new UsageError("--dataset is required");
  if (!agentSpec) throw new UsageError("--agent is required (e.g. --agent ./agent.mjs#myAgent)");

  let thresholds: Threshold[];
  try {
    thresholds = parseFailOn((flags["fail-on"] as string[] | undefined) ?? DEFAULT_FAIL_ON);
  } catch (err) {
    throw new UsageError((err as Error).message);
  }

  const apiKey = flags.push ? resolveApiKey(str(flags, "api-key")) : undefined;
  if (flags.push && !apiKey) {
    throw new UsageError("--push needs an API key: --api-key, CORTEXOPS_API_KEY, or ~/.cortexops/credentials");
  }

  let ds: EvalDataset;
  try {
    ds = await loadDataset(isAbsolute(datasetPath) ? datasetPath : resolve(io.cwd, datasetPath));
  } catch (err) {
    throw new UsageError((err as Error).message);
  }
  const agent = await loadAgent(agentSpec, io.cwd);
  const project = str(flags, "project");

  io.stdout(`CortexOps eval\n  dataset : ${datasetPath} (${ds.cases.length} cases)\n  project : ${project ?? ds.project}\n`);
  for (const t of thresholds) io.stdout(`  fail-on : ${t.expression}\n`);
  io.stdout("\n");

  const quiet = Boolean(flags.quiet);
  const summary = await EvalSuite.run(ds, agent, {
    verbose: !quiet,
    write: io.stdout,
    ...(project ? { project } : {}),
  });
  if (quiet) io.stdout(`${formatSummary(summary)}\n`);

  const gates: GateResult[] = checkThresholds(summary, thresholds);

  if (flags.push && apiKey) {
    const apiUrl = str(flags, "api-url") ?? str(flags, "base-url");
    await pushSummary(summary, ds, { apiKey, ...(apiUrl ? { apiUrl } : {}), projectExplicit: Boolean(project) }, io);
  }

  const markdown = renderMarkdown(summary, gates, { dataset: datasetPath, ...(str(flags, "title") ? { title: str(flags, "title")! } : {}) });
  const outputs: Array<[string | undefined, string, () => string]> = [
    [str(flags, "output"), "Summary", () => `${JSON.stringify(summary, null, 2)}\n`],
    [str(flags, "output-json") ?? str(flags, "json"), "JSON report", () => `${JSON.stringify(buildReport(summary, gates, { dataset: datasetPath }), null, 2)}\n`],
    [str(flags, "summary-md"), "Markdown report", () => markdown],
    [str(flags, "junit-xml"), "JUnit report", () => renderJunit(summary, gates)],
  ];
  io.stdout("\n");
  for (const [path, label, render] of outputs) {
    if (path) io.stdout(`${label} written to ${await writeOutput(path, render(), io.cwd)}\n`);
  }
  const stepSummary = process.env.GITHUB_STEP_SUMMARY;
  if (stepSummary && !flags["no-step-summary"]) {
    try {
      await appendFile(stepSummary, `${markdown}\n`, "utf8");
      io.stdout("Markdown summary appended to GITHUB_STEP_SUMMARY\n");
    } catch (err) {
      io.stderr(`Warning: could not write GITHUB_STEP_SUMMARY: ${(err as Error).message}\n`);
    }
  }

  for (const g of gates) {
    io.stdout(`  gate ${g.failed ? "FAILED" : "passed"}: ${g.expression} (actual ${fixed(g.actual, 3)})\n`);
  }
  const failures = gates.filter((g) => g.failed);
  if (failures.length) {
    io.stderr(`\nCI gate FAILED: ${failures.map((f) => f.message).join("; ")}\n`);
    return 1;
  }
  return 0;
}

/** CLI entry point. Returns the process exit code. */
export async function main(argv: string[], partialIO: Partial<CliIO> = {}): Promise<number> {
  const io: CliIO = {
    stdout: (text) => void process.stdout.write(text),
    stderr: (text) => void process.stderr.write(text),
    cwd: process.cwd(),
    ...partialIO,
  };
  const [command, sub, ...rest] = argv;
  try {
    if (!command || command === "help" || command === "--help" || command === "-h") {
      io.stdout(HELP);
      return 0;
    }
    if (command === "version" || command === "--version" || command === "-v") {
      io.stdout(`cortexops-js ${VERSION}\n`);
      return 0;
    }
    if (command === "eval" && sub === "run") return await evalRun(rest, io);
    if (command === "eval" && (sub === undefined || sub === "--help" || sub === "-h")) {
      io.stdout(HELP);
      return 0;
    }
    throw new UsageError(`Unknown command: ${[command, sub].filter(Boolean).join(" ")}`);
  } catch (err) {
    if (err instanceof UsageError) {
      io.stderr(`Error: ${err.message}\nRun 'cortexops-js --help' for usage.\n`);
      return 2;
    }
    io.stderr(`Error: ${(err as Error)?.stack ?? String(err)}\n`);
    return 2;
  }
}
