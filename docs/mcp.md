# CortexOps and the Model Context Protocol (MCP)

CortexOps works with [MCP](https://modelcontextprotocol.io) in both directions:

1. **Trace MCP tool calls.** Agents that call tools through an MCP `ClientSession` can have every call
   recorded as a CortexOps `ToolCall` (arguments, result summary, errors, latency) on the active trace.
2. **CortexOps MCP server.** `cortexops-mcp` exposes your traces, evals, golden datasets, and prompt
   registry to MCP clients such as Cursor and Claude Desktop, so you can ask "which traces failed after
   prompt v3?" or "promote this trace to my golden set" from your editor.

Both need the optional extra (supports `mcp` 1.10+ and 2.x):

```bash
pip install 'cortexops[mcp]'
```

---

## 1. Tracing MCP tool calls

### Quickstart

```python
import asyncio

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from cortexops import CortexTracer
from cortexops.integrations.mcp import instrument_mcp_session, trace_run

tracer = CortexTracer(project="support-agent")   # key from CORTEXOPS_API_KEY or `cortexops login`
tracer.set_prompt("triage-system", "v3")          # optional: tag traces with the prompt version

async def main():
    params = StdioServerParameters(command="npx", args=["-y", "@modelcontextprotocol/server-github"])
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        instrument_mcp_session(session, tracer, server_name="github")

        async with trace_run(tracer, input={"task": "triage issue 42"}) as trace:
            issue = await session.call_tool("get_issue", {"owner": "acme", "repo": "api", "issue_number": 42})
            # ... call your LLM, more tools ...
            trace.output = {"answer": "labelled as bug"}

asyncio.run(main())
```

With mcp 2.x you can also instrument the high-level `mcp.Client` (`instrument_mcp_session(client, tracer)`).
Instrumenting both a `Client` and its `client.session` records each call once.

Each call becomes a `ToolCall` named `<server>/<tool>` (for example `github/get_issue`). When `server_name`
is omitted, the server's advertised name is used if the session exposes it (mcp 2.x), otherwise the bare
tool name.

### Where calls are recorded

| Context | Result |
|---|---|
| Inside `mcp_node(tracer, "name")` | Appended to that node's `tool_calls` |
| Inside a running trace: `trace_run(...)` or a `tracer.wrap(...)` run in progress | A new node `mcp:<server>/<tool>` holding the single call, so each call gets its own bar in the waterfall |
| No active trace | Not recorded on any trace. The call still runs and `on_tool_call` still fires |

Orphan calls are not turned into standalone traces on purpose: that would spend trace quota and detach
the call from the agent run it belongs to. Open a `trace_run` around the agent run instead.

`trace_run` works as `async with` or `with`. It honors `sample_rate` / `sample_errors` (failed runs are
kept even when unsampled, with their tool calls), tags the active prompt version, ships the trace to the
hosted API off the event loop, and keeps concurrent asyncio tasks on separate traces.

Group several calls into one step with `mcp_node`:

```python
from cortexops.integrations.mcp import mcp_node

async with trace_run(tracer, input={"question": q}):
    async with mcp_node(tracer, "research") as node:
        await session.call_tool("search", {"query": q})
        await session.call_tool("fetch", {"url": url})
        node.output = {"sources": 2}
```

### Errors and failure classification

- A result with `isError: true` is recorded with `status="error"` and the error text. It is returned to
  your code unchanged unless you pass `raise_on_error=True`, which raises `MCPToolError` instead.
- An exception from `call_tool` (transport failure, protocol error) is recorded and re-raised. MCP request
  timeouts are recorded with `status="timeout"`.
- A `trace_run` that exits with an exception raised by an instrumented call (directly or as the
  `__cause__` of your own exception) is marked failed with `failure_kind="tool_error"` (or `"timeout"`).
  Other exceptions get `failure_kind="unknown"`.
- A run that completes despite tool errors stays `completed` and carries `metadata["mcp_tool_errors"]`.

### Options

```python
instrument_mcp_session(
    session, tracer,
    server_name="github",       # label used in "<server>/<tool>"
    trace_list_tools=False,     # also record list_tools() as "<server>/list_tools"
    qualify_names=True,         # False records the bare tool name instead of "<server>/<tool>"
    redact_keys=DEFAULT_REDACT_KEYS,  # argument keys replaced with "[REDACTED]"; () disables
    redact=None,                # callable applied to recorded args and results
    max_value_chars=1000,       # truncate long strings; containers are capped at 50 items
    raise_on_error=False,       # raise MCPToolError on isError results
    on_tool_call=None,          # callback receiving every ToolCall, even without an active trace
)
uninstrument_mcp_session(session)
```

### Privacy

- Arguments whose key looks like a secret (`password`, `secret`, `token`, `api_key`, `authorization`,
  `credential`, `cookie`, `private_key`, and suffixes such as `access_token`) are replaced with
  `"[REDACTED]"` before the trace leaves the process. `max_tokens` and similar keys are left alone.
- The hosted API additionally redacts email, card, SSN, and phone patterns on ingest.
- Long values are truncated so traces stay well under the 128KB ingest limit.
- Use `redact=` for anything domain-specific (customer ids, free-text fields).

### Evals

`ToolAccuracyMetric` accepts either form in golden datasets: `expected_tool_calls: ["get_issue"]` matches
`get_issue` on any MCP server, while `["github/get_issue"]` requires that server.

### Example

[`examples/mcp_tools/`](../examples/mcp_tools/) starts a small billing MCP server over stdio, runs two
refund tasks through an instrumented `ClientSession`, and prints the recorded tool calls:

```bash
python examples/mcp_tools/agent.py
```

---

## 2. The CortexOps MCP server

### Run it

```bash
pip install 'cortexops[mcp]'
cortexops login                 # stores the key in ~/.cortexops/credentials (or set CORTEXOPS_API_KEY)
cortexops-mcp                   # stdio transport, for Cursor / Claude Desktop
```

Without the `mcp` extra, `cortexops-mcp` exits with an install hint. Without an API key, the server still
starts and every tool returns a message explaining how to configure one.

### Cursor

Project-level `.cursor/mcp.json` (or global `~/.cursor/mcp.json`):

```json
{
  "mcpServers": {
    "cortexops": {
      "command": "cortexops-mcp",
      "env": {
        "CORTEXOPS_API_URL": "https://api.getcortexops.com"
      }
    }
  }
}
```

This relies on `cortexops login` having written `~/.cortexops/credentials`, which keeps the key out of
the repo. To pass the key explicitly, add `"CORTEXOPS_API_KEY": "cxo-..."` to `env`, and do not
commit that file. If Cursor cannot find the command, use the absolute path from `which cortexops-mcp`.

To let the agent promote traces into datasets, add `"args": ["--allow-writes"]`.

### Claude Desktop

Edit `claude_desktop_config.json`:

- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "cortexops": {
      "command": "/absolute/path/to/cortexops-mcp",
      "env": {
        "CORTEXOPS_API_KEY": "cxo-...",
        "CORTEXOPS_PROJECT": "payments-agent"
      }
    }
  }
}
```

Claude Desktop does not inherit your shell `PATH`, so use the absolute path printed by
`which cortexops-mcp` (inside the virtualenv where you installed `cortexops[mcp]`). Restart Claude Desktop
after editing the file.

### Claude Code

```bash
claude mcp add cortexops -- cortexops-mcp
# or pass settings explicitly:
claude mcp add cortexops -e CORTEXOPS_API_KEY=cxo-... -e CORTEXOPS_PROJECT=payments-agent -- cortexops-mcp
```

### Streamable HTTP (optional)

```bash
cortexops-mcp --transport streamable-http --host 127.0.0.1 --port 8765
# MCP endpoint: http://127.0.0.1:8765/mcp
```

The HTTP endpoint has no authentication of its own: anyone who can reach it acts with the server's API
key. Keep it on `127.0.0.1` unless it sits behind an authenticating proxy.

### Configuration

| Setting | Flag | Environment | Default |
|---|---|---|---|
| API key | | `CORTEXOPS_API_KEY` | `~/.cortexops/credentials` |
| API URL | `--api-url` | `CORTEXOPS_API_URL` | credentials file, then `https://api.getcortexops.com` |
| Default project | `--project` | `CORTEXOPS_PROJECT` | project bound to the key, then the credentials file |
| Enable write tools | `--allow-writes` | `CORTEXOPS_MCP_ALLOW_WRITES=1` | off |
| Transport | `--transport` | | `stdio` (`streamable-http` optional) |
| HTTP bind | `--host`, `--port` | | `127.0.0.1`, `8765` |

Every tool that takes `project` falls back to the default project. Keys are bound to one project, so in
practice you rarely pass it.

### Tools

All tools return compact JSON and truncate long values; time filters accept ISO 8601
(`2026-10-01T12:00:00Z`) or relative values (`30m`, `24h`, `7d`).

| Tool | What it does | Backend route |
|---|---|---|
| `whoami` | Project bound to the key, tier, monthly trace quota, retention, default project | `GET /v1/traces/quota` |
| `list_traces` | Recent traces filtered by `status`, `environment`, `prompt_name`, `prompt_version`, `since`, `until`, `limit` (max 200) | `GET /v1/traces` |
| `get_trace` | One trace: failure detail, prompt, input/output, summarized node waterfall with tool calls | `GET /v1/traces/{id}` |
| `failures_by_prompt` | Groups up to 500 recent traces by prompt name/version: traces, failures, failure rate, `failure_kind` breakdown, sample failed trace ids | `GET /v1/traces` |
| `list_evals` | Recent eval runs with pass/fail, task completion, tool accuracy, latency | `GET /v1/evals` |
| `get_eval` | One eval run and its failed cases (`include_passed` for all) | `GET /v1/evals/{run_id}` |
| `diff_evals` | Metric deltas and regressed / improved cases between two runs | `GET /v1/evals/diff` |
| `list_datasets` | Golden datasets for the key's project | `GET /v1/eval/datasets` |
| `list_prompts` | Prompt registry: latest version of each prompt with a content preview | `GET /v1/prompts/catalog` |
| `diff_prompts` | Unified diff between two registry versions (`3` or `v3`) | `GET /v1/prompts/diff` |
| `promote_trace_to_dataset` | **Write.** Adds a golden case built from a trace to a dataset (by id or exact name) and returns it as a YAML snippet for local golden files. Only registered with `--allow-writes`; needs a `read_write` key | `POST /v1/eval/datasets/{id}/cases/from-trace` |

The server also ships an `investigate_failures` prompt that walks the model through
`failures_by_prompt`, `list_traces`, `get_trace`, and `diff_prompts`.

Example questions:

- "Which traces failed after prompt v3 in production over the last 24 hours?"
- "Which prompt version has the highest failure rate this week, and what kind of failures?"
- "Show me the waterfall for trace 7f3c... and explain why it failed."
- "Did eval run B regress against run A? Which cases?"
- "What changed between refund-system v2 and v3?"
- "Promote trace 7f3c... to the golden dataset." (requires `--allow-writes`)

Note that trace `prompt_version` labels are whatever you passed to `tracer.set_prompt` (for example
`"v3"`), while the prompt registry numbers versions `1, 2, 3, ...` as you commit them.

### Security notes

- **Key scope.** The server can do whatever its API key can do, within the single project the key is
  bound to. Prefer a dedicated `read_only` key for MCP clients. Create one with
  `POST /v1/keys` (`"scope": "read_only"`) or from the dashboard. A `read_only` key makes
  `promote_trace_to_dataset` fail with a 403 even when `--allow-writes` is set.
- **Writes are opt-in.** Without `--allow-writes` the mutating tool is not registered at all, so the
  model cannot call it. Read tools carry the MCP `readOnlyHint` annotation; the write tool does not, so
  clients that honor annotations ask for confirmation.
- **Secrets.** The key is never returned by any tool (`whoami` shows a masked prefix and suffix). Prefer
  `cortexops login` over pasting keys into editor config files, and never commit `.cursor/mcp.json` with a
  key in it.
- **Data exposure.** Tool results include trace inputs, outputs, and tool arguments (already PII-redacted
  on ingest and truncated). They are sent to whichever model your MCP client uses.
- **HTTP transport.** Bind to `127.0.0.1` (the default); see above.
