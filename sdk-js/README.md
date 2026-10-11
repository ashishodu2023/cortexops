# @cortexops/sdk

TypeScript / JavaScript SDK for [CortexOps](https://getcortexops.com): trace AI agents in production and gate releases on golden-dataset evals.

It is the JavaScript counterpart of the Python `cortexops` SDK. It sends the same trace and eval payloads to the same REST API, reads the same golden YAML datasets, and computes the same metric scores. Python and TypeScript results are therefore directly comparable.

- **Tracing** for Vercel AI SDK, LangGraph.js, OpenAI Agents SDK, Mastra, or any function, with nodes, tool calls, token usage, prompt versions, head sampling and error capture
- **Eval gate**: `EvalSuite`, `evalGate()` for Vitest / Jest / `node:test`, and the `cortexops-js eval run` CLI for CI
- **API client** for traces and eval runs
- Node.js 18+, ESM and CommonJS, full type definitions, one runtime dependency (`yaml`)

```bash
npm install @cortexops/sdk
```

## Contents

- [Tracing quickstart](#tracing-quickstart)
- [Framework integrations](#framework-integrations)
- [Eval gate](#eval-gate)
- [CLI](#cli)
- [API client](#api-client)
- [Configuration](#configuration)
- [Compatibility with the Python SDK](#compatibility-with-the-python-sdk)

## Tracing quickstart

```ts
import { CortexTracer } from "@cortexops/sdk";

const tracer = new CortexTracer({ project: "payments-agent" }); // API key from CORTEXOPS_API_KEY

const agent = tracer.wrap(async (input: { query: string }) => {
  const intent = tracer.traceNode("classify", () => classify(input.query));
  return tracer.traceNode("respond", async () => {
    const refund = await lookupRefund(input.query);
    tracer.recordToolCall("lookup_refund", { args: { query: input.query }, result: refund, latencyMs: 42 });
    return { output: `Refund ${refund.id} is ${refund.status}`, intent };
  });
});

await agent({ query: "Where is refund REF-8821?" });
console.log(tracer.lastTrace()); // traces are also kept in memory (last 1000)

await tracer.shutdown(); // before the process exits: waits for in-flight uploads
```

- **Uploads never block your agent.** Each finished trace is POSTed to `/v1/traces` in the background, with a 2 s timeout and an `Idempotency-Key`. Failures are dropped; pass `onFlushError` to observe them. `await tracer.flush()` waits for pending uploads.
- **Without an API key** the tracer is local-only. Traces are still available through `tracer.traces()` and `tracer.lastTrace()`.
- **Errors** thrown by the agent are recorded (`status: "failed"`, `failure_detail`) and re-thrown unchanged.
- **Nodes and tool calls** attach to the active trace through `AsyncLocalStorage`, so concurrent requests never mix.

### Prompt versions

```ts
tracer.setPrompt("refund-system", "v3"); // tag every following trace

// Per request: isolated per async context, safe under concurrency
await tracer.usePrompt("refund-system", "v4-canary", () => agent(input));
```

Inside `usePrompt`, `setPrompt` and `clearPrompt` only affect that scope.

### Sampling

```ts
const tracer = new CortexTracer({ sampleRate: 0.1 }); // keep 10% of runs (or CORTEXOPS_SAMPLE_RATE=0.1)
```

The sampling decision is made when a run starts. Failed runs are always captured, even when not sampled, unless you set `sampleErrors: false`. Traces record `metadata.sample_rate` and `metadata.sampled`, and error-captured traces also get `metadata.captured_reason: "error"`.

### Options

| Option | Default | |
|---|---|---|
| `project` | `CORTEXOPS_PROJECT` or `"default"` | |
| `apiKey` | `CORTEXOPS_API_KEY`, then `~/.cortexops/credentials` | Omit for local-only tracing |
| `apiUrl` | `CORTEXOPS_API_URL` or `https://api.getcortexops.com` | |
| `environment` | `CORTEXOPS_ENVIRONMENT` or `"development"` | |
| `sampleRate` | `CORTEXOPS_SAMPLE_RATE` or `1.0` | 0.0 - 1.0 |
| `sampleErrors` | `true` | Capture failed runs even when not sampled |
| `localStore` / `maxLocalTraces` | `true` / `1000` | In-memory trace buffer |
| `flushTimeoutMs` | `2000` | Per-upload timeout |
| `fetch` | global `fetch` | Custom transport (proxies, tests) |
| `onFlushError` | none | `(error, trace) => void` |

Lower-level API: `tracer.startTrace(input)` returns a `TraceRun` (`addNode`, `recordToolCall`, `setMetadata`, `addUsage`, `end`, `fail`, `run(fn)`). `tracer.runTraced(fn, options)` covers custom wrappers.

## Framework integrations

The integrations use structural typing. The SDK does not depend on any framework package and works with whichever version you have installed. `tracer.wrap(x)` auto-detects the framework (`detectFramework(x)` tells you what it found). The explicit wrappers below do the same thing.

| Framework | Wrapper | Captured |
|---|---|---|
| Vercel AI SDK 5 / 6 / 7 | `wrapGenerateText`, `wrapStreamText`, `cortexopsMiddleware` | one node per step, tool calls with results and errors, token usage, model, finish reason |
| LangGraph.js | `wrapLangGraph` (`invoke`, `stream`) | one node per graph node, tool calls on the node that ran them |
| OpenAI Agents SDK (JS) | `wrapOpenAIAgentsRun`, `wrapOpenAIAgent` | one node per agent, tool calls and handoffs with outputs, usage, last agent |
| Mastra | `wrapMastraAgent` (`generate`, `stream`) | one node per step, tool calls with results, usage, model |
| Anything else | `tracer.wrap(fn)`, objects with `.invoke()` | input, output, latency, errors, plus your `traceNode` / `recordToolCall` calls |

Runnable examples: [`examples/`](./examples) (`vercel-ai.mjs`, `langgraph.mjs`, `openai-agents.mjs`, `mastra.mjs`, and the `payments-agent.mjs` used by the eval gate).

### Vercel AI SDK

```ts
import { generateText, streamText, wrapLanguageModel, stepCountIs } from "ai";
import { openai } from "@ai-sdk/openai";
import { CortexTracer, wrapGenerateText, wrapStreamText, cortexopsMiddleware } from "@cortexops/sdk";

const tracer = new CortexTracer({ project: "support-bot" });

const tracedGenerateText = wrapGenerateText(tracer, generateText);
const { text } = await tracedGenerateText({ model: openai("gpt-4o-mini"), prompt: "Where is order 42?", tools, stopWhen: stepCountIs(3) });

// Streaming: finalized from onFinish / onError; your own callbacks still run
const tracedStreamText = wrapStreamText(tracer, streamText);

// Or trace at the model level: each call becomes an llm:<model> node on the active trace
const model = wrapLanguageModel({ model: openai("gpt-4o-mini"), middleware: cortexopsMiddleware(tracer) });
```

### LangGraph.js

```ts
import { wrapLangGraph } from "@cortexops/sdk";

const graph = workflow.compile();
const traced = wrapLangGraph(tracer, graph); // or tracer.wrap(graph)

await traced.invoke({ messages: [{ role: "user", content: "Refund REF-8821?" }] });
for await (const chunk of await traced.stream(input, { streamMode: "updates" })) { /* ... */ }
```

Nodes and tool calls come from a LangChain callback handler that is appended to `config.callbacks`. Your own callbacks keep working. If you pass a `CallbackManager` instance instead of an array, the run is still traced, but without per-node detail.

### OpenAI Agents SDK

```ts
import { Agent, run } from "@openai/agents";
import { wrapOpenAIAgentsRun, wrapOpenAIAgent } from "@cortexops/sdk";

const tracedRun = wrapOpenAIAgentsRun(tracer, run);
const result = await tracedRun(agent, "What is the status of refund REF-8821?");
const stream = await tracedRun(agent, "...", { stream: true }); // finalized when stream.completed resolves

// Or an agent with a traced .run() (what tracer.wrap(agent) returns)
const traced = wrapOpenAIAgent(tracer, agent, { run });
```

### Mastra

```ts
import { wrapMastraAgent } from "@cortexops/sdk";

const traced = wrapMastraAgent(tracer, mastraAgent); // or tracer.wrap(mastraAgent)
const result = await traced.generate("Where is order 42?", { maxSteps: 3 });
```

## Eval gate

Golden datasets use the same YAML format as the Python SDK. The format is described by a JSON Schema shipped with the package, at [`schema/golden-dataset.v1.schema.json`](./schema/golden-dataset.v1.schema.json) (import path `@cortexops/sdk/schema/golden-dataset.v1.json`).

```yaml
version: 1
project: payments-agent
cases:
  - id: refund_approved_01
    input: "What is the status of refund REF-8821?"
    expected_tool_calls: [lookup_refund]
    expected_output_contains: ["approved"]
    max_latency_ms: 3000
```

```ts
import { EvalSuite, EvalThresholdError } from "@cortexops/sdk";

const summary = await EvalSuite.run("golden_v1.yaml", agent, {
  failOn: ["task_completion < 0.90", "tool_accuracy < 0.95"], // throws EvalThresholdError when any is true
});
console.log(summary.task_completion_rate, summary.latency_p95_ms);
```

The agent can be a function `(input) => output`, an object with `.invoke()`, or anything `tracer.wrap()` returned. String inputs are passed as `{ input: "..." }`. For scoring, the output is read from:

- `output` (or the whole return value if it's a string), checked for `expected_output_contains`
- `tool_calls_made` (an array of tool names)
- tool calls captured by the tracer during the case: integrations, `recordToolCall`

### In a test runner

`evalGate()` is the counterpart of Python's `@cortexops.eval_gate`. It defaults to `pass_rate < 1.0`, so every case must pass. On failure it throws an error listing every tripped condition, followed by the summary.

```ts
import { test } from "vitest";
import { evalGate } from "@cortexops/sdk";

test("payments agent meets the gate", async () => {
  await evalGate(new URL("./golden_v1.yaml", import.meta.url), buildAgent(), {
    failOn: ["task_completion < 0.90", "tool_accuracy < 0.95"],
  });
}, 60_000);
```

### Metrics and gates

Scores are identical to the Python SDK: the TypeScript implementation is tested against fixtures generated from the Python code.

| Metric | Score (0-100) |
|---|---|
| `task_completion` | 100 when every `expected_output_contains` string is present (case-insensitive), else 50 + 50 x the fraction found; 30 if an `expected_output_not_contains` string appears, 20 on error-like output, 0 on empty output |
| `tool_accuracy` | percentage of `expected_tool_calls` that were called (traced tool calls, else the output's `tool_calls_made`) |
| `latency` | 100 within `max_latency_ms`, then decreasing |
| `hallucination` | 40 when the output matches a fabrication pattern, else 100 |
| `llm_judge` | `judge: llm` cases only: keyword overlap with `judge_criteria` (the offline heuristic) |

A case passes when the mean of its metric scores is at least 80. The first metric below 100 sets its `failure_kind` and `failure_detail`. Gate expressions have the form `<metric> <op> <value>`, where `metric` is `task_completion`, `tool_accuracy` or `pass_rate` (all 0-1) and `op` is `<`, `<=`, `>` or `>=`. The gate **fails when the condition is true**, exactly as in Python.

## CLI

```bash
npx cortexops-js eval run \
  --dataset golden_v1.yaml \
  --agent "./agent.mjs#buildAgent()" \
  --fail-on "task_completion < 0.90" --fail-on "tool_accuracy < 0.95" \
  --output-json eval-report.json --summary-md eval-summary.md --junit-xml eval-junit.xml
```

| Flag | |
|---|---|
| `-d, --dataset` | Golden dataset (YAML or JSON) |
| `-a, --agent` | `./agent.mjs` (default export or `agent`), `./agent.mjs#name` or `./agent.mjs:name`; append `()` to call a factory (quote it in shells). TypeScript agents: compile first, or run Node with a loader such as `tsx` (`node --import tsx node_modules/.bin/cortexops-js ...`) |
| `--fail-on` | Repeatable or comma / newline separated. Default: `pass_rate < 1.0` |
| `-p, --project` | Override the dataset project |
| `--output-json` (`--json`) | JSON report: same `schema_version: 1` format as the Python CLI |
| `-o, --output` | Raw summary JSON including per-case traces |
| `--summary-md`, `--title` | Markdown report |
| `--junit-xml` | JUnit XML (one testcase per case and per gate) |
| `--no-step-summary` | Do not append to `$GITHUB_STEP_SUMMARY` (appended by default when set) |
| `--push` | Upload the summary (`POST /v1/evals/ingest`); without `--project` the run goes to the project bound to the key |
| `--api-key`, `--api-url` (`--base-url`) | For `--push` |
| `-q, --quiet` | Summary only |

Exit codes: `0` gate passed, `1` gate failed, `2` usage or configuration error. The markdown, JUnit and JSON reports match the Python CLI's formats, so the same CI tooling reads either.

### GitHub Actions

```yaml
- uses: actions/setup-node@v4
  with:
    node-version: 22
- run: npm ci
- run: npx cortexops-js eval run -d evals/golden_v1.yaml -a ./dist/agent.js#agent --fail-on "task_completion < 0.90" --junit-xml eval-junit.xml
  env:
    CORTEXOPS_API_KEY: ${{ secrets.CORTEXOPS_API_KEY }} # only needed with --push
```

The markdown report is appended to the job summary automatically.

## API client

```ts
import { CortexClient } from "@cortexops/sdk";

const client = new CortexClient(); // apiKey / baseUrl from options, env or ~/.cortexops/credentials
await client.pushTrace(trace);
const traces = await client.listTraces("payments-agent", { limit: 20, status: "failed", promptVersion: "v3" });
const detail = await client.getTrace(traces[0].trace_id);
await client.pushEval(summary, { dataset: { name: "golden_v1", cases } });
const runs = await client.listRuns("payments-agent");
```

HTTP errors throw a `CortexApiError` that exposes `status` and `body`.

## Configuration

| Variable | Used for |
|---|---|
| `CORTEXOPS_API_KEY` | API key (`cxo-...`) for trace upload, `--push` and `CortexClient` |
| `CORTEXOPS_API_URL` | API base URL (default `https://api.getcortexops.com`) |
| `CORTEXOPS_PROJECT` | Default tracer project |
| `CORTEXOPS_ENVIRONMENT` | Trace environment (default `development`) |
| `CORTEXOPS_SAMPLE_RATE` | Default sample rate (0.0 - 1.0) |
| `GITHUB_STEP_SUMMARY` | Set by GitHub Actions; the CLI appends its markdown report |

The API key is resolved in this order: explicit option, then `CORTEXOPS_API_KEY`, then `~/.cortexops/credentials`. That last file is written by `cortexops login` from the Python CLI.

## Compatibility with the Python SDK

- **Same wire format.** Trace and eval objects use the Python field names (`snake_case`: `trace_id`, `total_latency_ms`, `tool_calls`, ...). Data can move between the two SDKs and the API without mapping.
- **Same scoring.** Metric scores, case pass/fail, p50/p95, gate expressions and gate error messages are tested against fixtures generated by the Python SDK. The fixtures are produced by `scripts/gen_parity_fixtures.py`.
- **LLM judge.** `judge: llm` cases use the offline heuristic in both SDKs. Calling a hosted judge is not supported yet.
- **Runtime.** Node.js 18 or newer. Browsers and edge runtimes are not supported, because the tracer relies on `AsyncLocalStorage` and the CLI reads files.

## Development

```bash
cd sdk-js
npm ci
npm run lint    # eslint + tsc --noEmit (strict)
npm test        # vitest
npm run build   # tsup: dist/index.{js,cjs,d.ts,d.cts} and dist/cli.js
```

To regenerate the parity fixtures after changing the Python SDK, run `python scripts/gen_parity_fixtures.py` with the SDK installed (`pip install -e ../sdk`).

## License

MIT
