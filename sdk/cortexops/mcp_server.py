"""CortexOps MCP server: query traces, evals, datasets, and prompts from Cursor, Claude Desktop, or any MCP client.

    pip install 'cortexops[mcp]'
    CORTEXOPS_API_KEY=cxo-... cortexops-mcp                      # stdio (default)
    cortexops-mcp --transport streamable-http --port 8765         # local HTTP endpoint at /mcp

Configuration (flags override environment):
    CORTEXOPS_API_KEY           API key; falls back to ~/.cortexops/credentials (`cortexops login`)
    CORTEXOPS_API_URL           API base URL (default https://api.getcortexops.com)
    CORTEXOPS_PROJECT           default project; otherwise the project bound to the key is used
    CORTEXOPS_MCP_ALLOW_WRITES  "1"/"true" to expose mutating tools (promote_trace_to_dataset)

All tools are read-only unless writes are enabled. Prefer a read_only API key for this server.
"""
from __future__ import annotations

import argparse
import functools
import json
import os
import re
import sys
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from .auth import load_credentials
from .client import CortexClient
from .integrations.mcp import truncate_value

__all__ = ["CortexOpsTools", "MCPNotInstalledError", "Settings", "build_server", "main", "resolve_settings"]

_DEFAULT_API_URL = "https://api.getcortexops.com"
_INSTALL_HINT = "cortexops-mcp needs the optional MCP dependencies. Install them with: pip install 'cortexops[mcp]'"
_MAX_OUTPUT_CHARS = 24_000
_MAX_TRACE_LIST = 200
_MAX_ANALYZED_TRACES = 500  # GET /v1/traces caps limit at 500
_RELATIVE_TIME = re.compile(r"^(\d+)\s*([mhdw])$")
_TIME_UNITS = {"m": "minutes", "h": "hours", "d": "days", "w": "weeks"}

SERVER_INSTRUCTIONS = """\
CortexOps stores traces of AI agent runs (status, failure_kind, prompt_name/prompt_version, node waterfall),
eval runs, golden datasets, and a versioned prompt registry.
Typical flow: whoami -> failures_by_prompt or list_traces(status="failed", prompt_version=...) -> get_trace
-> list_datasets -> promote_trace_to_dataset (only when writes are enabled).
Time filters accept ISO 8601 or relative values like "30m", "24h", "7d". Results are truncated for size.
"""


class MCPNotInstalledError(ImportError):
    """The optional `mcp` package is not installed."""


class ToolInputError(ValueError):
    """A tool was called with arguments or configuration it cannot work with."""


# ── Configuration ──────────────────────────────────────────────────────────

@dataclass
class Settings:
    api_key: str | None
    api_url: str
    project: str | None = None
    fallback_project: str | None = None
    key_source: str = "none"
    allow_writes: bool = False

    @property
    def masked_key(self) -> str | None:
        if not self.api_key:
            return None
        return self.api_key[:8] + "..." + self.api_key[-4:]


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def resolve_settings(
    *, api_url: str | None = None, project: str | None = None, allow_writes: bool | None = None,
) -> Settings:
    """Resolve key / URL / project the same way the SDK does: env vars first, then ~/.cortexops/credentials."""
    creds = load_credentials() or {}
    env_key = os.getenv("CORTEXOPS_API_KEY")
    if env_key:
        api_key, source = env_key, "env:CORTEXOPS_API_KEY"
    elif creds.get("api_key"):
        api_key, source = creds["api_key"], "~/.cortexops/credentials"
    else:
        api_key, source = None, "none"
    url = api_url or os.getenv("CORTEXOPS_API_URL") or creds.get("api_url") or _DEFAULT_API_URL
    return Settings(
        api_key=api_key,
        api_url=url.rstrip("/"),
        project=project or os.getenv("CORTEXOPS_PROJECT") or None,
        fallback_project=creds.get("project") or None,
        key_source=source,
        allow_writes=_truthy(os.getenv("CORTEXOPS_MCP_ALLOW_WRITES")) if allow_writes is None else allow_writes,
    )


# ── Formatting helpers ─────────────────────────────────────────────────────

def parse_time(value: str | None, *, now: datetime | None = None) -> str | None:
    """Normalize "24h" / "7d" / ISO 8601 to a naive-UTC ISO timestamp (the API stores naive UTC)."""
    if value is None or not str(value).strip():
        return None
    text = str(value).strip().lower()
    current = now or datetime.now(timezone.utc)
    match = _RELATIVE_TIME.match(text)
    if match:
        moment = current - timedelta(**{_TIME_UNITS[match.group(2)]: int(match.group(1))})
    else:
        try:
            moment = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00").replace("z", "+00:00"))
        except ValueError:
            raise ToolInputError(
                f"Invalid time {value!r}: use ISO 8601 (2026-10-01T12:00:00Z) or relative like 30m, 24h, 7d"
            ) from None
    if moment.tzinfo is not None:
        moment = moment.astimezone(timezone.utc)
    return moment.replace(tzinfo=None).isoformat(timespec="seconds")


def parse_prompt_version(value: str | int) -> int:
    """Registry versions are integers; accept 3, "3", or "v3"."""
    text = str(value).strip().lower().removeprefix("v")
    if not text.isdigit():
        raise ToolInputError(f"Prompt registry versions are integers (e.g. 3 or 'v3'), got {value!r}")
    return int(text)


def _clip(value: Any, limit: int) -> Any:
    return truncate_value(value, max_chars=limit) if value is not None else None


def _compact(d: dict) -> dict:
    return {k: v for k, v in d.items() if v is not None and v != [] and v != {}}


def _round(value: Any, digits: int = 1) -> Any:
    return round(value, digits) if isinstance(value, (int, float)) else value


def dump(result: Any) -> str:
    """Serialize a tool result as compact JSON, shrinking it to stay within the output cap."""
    text = json.dumps(result, default=str, ensure_ascii=False)
    if len(text) <= _MAX_OUTPUT_CHARS:
        return text
    text = json.dumps(truncate_value(result, max_chars=200), default=str, ensure_ascii=False)
    if len(text) <= _MAX_OUTPUT_CHARS:
        return text
    return text[:_MAX_OUTPUT_CHARS] + f"...[output truncated, {len(text) - _MAX_OUTPUT_CHARS} more chars]"


def _trace_row(t: dict) -> dict:
    prompt = None
    if t.get("prompt_name"):
        prompt = f"{t['prompt_name']}@{t.get('prompt_version') or '?'}"
    return _compact({
        "trace_id": t.get("trace_id"),
        "status": t.get("status"),
        "failure_kind": t.get("failure_kind"),
        "failure_detail": _clip(t.get("failure_detail"), 200),
        "prompt": prompt,
        "environment": t.get("environment"),
        "latency_ms": _round(t.get("total_latency_ms"), 0),
        "case_id": t.get("case_id"),
        "created_at": t.get("created_at"),
    })


def _eval_row(run: dict) -> dict:
    return _compact({
        "run_id": run.get("run_id"),
        "status": run.get("status"),
        "created_at": run.get("created_at"),
        "total_cases": run.get("total_cases"),
        "passed": run.get("passed"),
        "failed": run.get("failed"),
        "task_completion_rate": _round(run.get("task_completion_rate"), 3),
        "tool_accuracy": _round(run.get("tool_accuracy")),
        "latency_p50_ms": _round(run.get("latency_p50_ms"), 0),
        "latency_p95_ms": _round(run.get("latency_p95_ms"), 0),
        "regressions": run.get("regressions") or None,
        "baseline_run_id": run.get("baseline_run_id"),
    })


# ── Tool logic (independent of the mcp package) ────────────────────────────

class CortexOpsTools:
    """The operations exposed over MCP, backed by `CortexClient`. Every method returns JSON-serializable data."""

    def __init__(self, client: CortexClient | Any | None, settings: Settings) -> None:
        self.client = client
        self.settings = settings
        self._bound_project: str | None = None

    def _api(self) -> Any:
        if self.client is None:
            raise ToolInputError(
                "No CortexOps API key configured. Set CORTEXOPS_API_KEY in this MCP server's env "
                "(or run `cortexops login`), then restart the server."
            )
        return self.client

    def project(self, project: str | None = None) -> str:
        if project:
            return project
        if self.settings.project:
            return self.settings.project
        if self._bound_project is None:
            self._bound_project = str(self._api().get_quota().get("project") or "")
        if self._bound_project and self._bound_project != "__dev__":
            return self._bound_project
        if self.settings.fallback_project:
            return self.settings.fallback_project
        raise ToolInputError("Cannot infer a project for this key: pass `project` or set CORTEXOPS_PROJECT.")

    def whoami(self) -> dict:
        quota = self._api().get_quota()
        self._bound_project = str(quota.get("project") or "")
        try:
            default_project: str | None = self.project()
        except ToolInputError:
            default_project = None
        return _compact({
            "key_project": quota.get("project"),
            "default_project": default_project,
            "tier": quota.get("tier"),
            "monthly_traces": quota.get("monthly_traces"),
            "retention_days": quota.get("retention_days"),
            "features": quota.get("features"),
            "api_url": self.settings.api_url,
            "key": self.settings.masked_key,
            "key_source": self.settings.key_source,
            "writes_enabled": self.settings.allow_writes,
        })

    def list_traces(
        self,
        project: str | None = None,
        status: str | None = None,
        environment: str | None = None,
        prompt_name: str | None = None,
        prompt_version: str | None = None,
        since: str | None = None,
        until: str | None = None,
        limit: int = 20,
    ) -> dict:
        proj = self.project(project)
        limit = max(1, min(int(limit), _MAX_TRACE_LIST))
        rows = self._api().list_traces(
            proj, limit,
            status=status or None, environment=environment or None,
            prompt_name=prompt_name or None, prompt_version=prompt_version or None,
            since=parse_time(since), until=parse_time(until),
        )
        filters = _compact({
            "status": status, "environment": environment, "prompt_name": prompt_name,
            "prompt_version": prompt_version, "since": since, "until": until,
        })
        return {
            "project": proj,
            "filters": filters,
            "count": len(rows),
            "more_available": len(rows) == limit,
            "traces": [_trace_row(t) for t in rows],
        }

    def get_trace(self, trace_id: str, max_nodes: int = 40) -> dict:
        detail = self._api().get_trace(trace_id)
        raw = detail.get("raw_trace") or {}
        nodes = raw.get("nodes") or []
        max_nodes = max(1, min(int(max_nodes), 200))
        waterfall = []
        for node in nodes[:max_nodes]:
            calls = [
                _compact({
                    "name": tc.get("name"),
                    "status": tc.get("status"),
                    "latency_ms": _round(tc.get("latency_ms"), 0),
                    "args": _clip(tc.get("args"), 200),
                    "result": _clip(tc.get("result"), 300),
                    "error": _clip(tc.get("error"), 300),
                })
                for tc in (node.get("tool_calls") or [])[:20]
            ]
            waterfall.append(_compact({
                "node": node.get("node_name"),
                "latency_ms": _round(node.get("latency_ms"), 0),
                "tool_calls": calls,
                "omitted_tool_calls": max(0, len(node.get("tool_calls") or []) - 20) or None,
                "llm_prompt": _clip(node.get("llm_prompt"), 300),
                "llm_response": _clip(node.get("llm_response"), 300),
                "input": _clip(node.get("input"), 200),
                "output": _clip(node.get("output"), 200),
            }))
        summary = _trace_row(detail)
        summary["failure_detail"] = _clip(detail.get("failure_detail"), 1000)
        return _compact({
            **summary,
            "project": detail.get("project"),
            "sampled": detail.get("sampled"),
            "input": _clip(raw.get("input"), 500),
            "output": _clip(raw.get("output"), 500),
            "metadata": _clip(raw.get("metadata"), 200),
            "node_count": len(nodes),
            "omitted_nodes": max(0, len(nodes) - max_nodes) or None,
            "waterfall": waterfall,
        })

    def failures_by_prompt(
        self,
        project: str | None = None,
        prompt_name: str | None = None,
        since: str | None = "7d",
        until: str | None = None,
        environment: str | None = None,
        limit: int = _MAX_ANALYZED_TRACES,
    ) -> dict:
        proj = self.project(project)
        limit = max(1, min(int(limit), _MAX_ANALYZED_TRACES))
        rows = self._api().list_traces(
            proj, limit,
            prompt_name=prompt_name or None, environment=environment or None,
            since=parse_time(since), until=parse_time(until),
        )
        groups: dict[tuple[str, str], dict[str, Any]] = {}
        for t in rows:
            key = (t.get("prompt_name") or "(untagged)", t.get("prompt_version") or "(untagged)")
            g = groups.setdefault(key, {"total": 0, "failed": 0, "kinds": Counter(), "samples": []})
            g["total"] += 1
            if t.get("status") == "failed":
                g["failed"] += 1
                g["kinds"][t.get("failure_kind") or "unknown"] += 1
                if len(g["samples"]) < 3:
                    g["samples"].append(t.get("trace_id"))
        ranked = sorted(groups.items(), key=lambda kv: (-kv[1]["failed"], -kv[1]["total"]))
        return {
            "project": proj,
            "window": _compact({"since": since, "until": until, "environment": environment}),
            "traces_analyzed": len(rows),
            "window_truncated": len(rows) == limit,
            "groups": [
                _compact({
                    "prompt_name": name,
                    "prompt_version": version,
                    "traces": g["total"],
                    "failed": g["failed"],
                    "failure_rate": round(g["failed"] / g["total"], 3) if g["total"] else 0.0,
                    "failure_kinds": dict(g["kinds"].most_common()),
                    "sample_failed_trace_ids": g["samples"],
                })
                for (name, version), g in ranked
            ],
        }

    def list_evals(self, project: str | None = None, limit: int = 10) -> dict:
        proj = self.project(project)
        runs = self._api().list_runs(proj, max(1, min(int(limit), 100)))
        return {"project": proj, "count": len(runs), "eval_runs": [_eval_row(r) for r in runs]}

    def get_eval(self, run_id: str, include_passed: bool = False, max_cases: int = 50) -> dict:
        run = self._api().get_eval(run_id)
        cases = run.get("case_results") or []
        shown = cases if include_passed else [c for c in cases if not c.get("passed")]
        max_cases = max(1, min(int(max_cases), 200))
        return _compact({
            **_eval_row(run),
            "project": run.get("project"),
            "dataset_version": run.get("dataset_version"),
            "cases_shown": "all" if include_passed else "failed only",
            "omitted_cases": max(0, len(shown) - max_cases) or None,
            "case_results": [
                _compact({
                    "case_id": c.get("case_id"),
                    "passed": c.get("passed"),
                    "score": _round(c.get("score")),
                    "tool_accuracy": _round(c.get("tool_accuracy")),
                    "latency_ms": _round(c.get("latency_ms"), 0),
                    "failure_kind": c.get("failure_kind"),
                    "failure_detail": _clip(c.get("failure_detail"), 300),
                })
                for c in shown[:max_cases]
            ],
        })

    def diff_evals(self, run_id_a: str, run_id_b: str) -> dict:
        diff = self._api().diff(run_id_a, run_id_b)
        return _compact({
            "baseline_run_id": diff.get("run_id_a", run_id_a),
            "candidate_run_id": diff.get("run_id_b", run_id_b),
            "task_completion_delta": _round(diff.get("task_completion_delta"), 3),
            "tool_accuracy_delta": _round(diff.get("tool_accuracy_delta")),
            "latency_p95_delta_ms": _round(diff.get("latency_p95_delta_ms"), 0),
            "regressions": diff.get("regressions") or [],
            "improvements": diff.get("improvements") or [],
            "note": "regression/improvement = same case scored more than 5 points lower/higher in the candidate run",
        })

    def list_datasets(self) -> dict:
        datasets = self._api().list_datasets()
        return {
            "count": len(datasets),
            "datasets": [
                _compact({
                    "dataset_id": d.get("id"),
                    "name": d.get("name"),
                    "description": _clip(d.get("description") or None, 200),
                    "case_count": d.get("case_count"),
                    "project": d.get("project"),
                    "created_at": d.get("created_at"),
                })
                for d in datasets
            ],
        }

    def _resolve_dataset(self, dataset: str) -> dict:
        datasets = self._api().list_datasets()
        for d in datasets:
            if d.get("id") == dataset:
                return d
        named = [d for d in datasets if str(d.get("name", "")).lower() == dataset.strip().lower()]
        if len(named) == 1:
            return named[0]
        if len(named) > 1:
            ids = ", ".join(str(d.get("id")) for d in named)
            raise ToolInputError(f"Several datasets are named {dataset!r} ({ids}); pass the dataset_id instead.")
        names = ", ".join(sorted(str(d.get("name")) for d in datasets)) or "none"
        raise ToolInputError(f"No dataset with id or name {dataset!r}. Available: {names}")

    def promote_trace_to_dataset(self, trace_id: str, dataset: str, case_id: str | None = None) -> dict:
        if not self.settings.allow_writes:
            raise ToolInputError("Writes are disabled. Restart cortexops-mcp with --allow-writes to promote traces.")
        target = self._resolve_dataset(dataset)
        created = self._api().add_case_from_trace(target["id"], trace_id, case_id=case_id or None)
        case = created.get("case")
        snippet = None
        if isinstance(case, dict):
            import yaml

            snippet = yaml.safe_dump([case], sort_keys=False, allow_unicode=True)
        return _compact({
            "dataset_id": created.get("dataset_id"),
            "dataset_name": created.get("dataset_name"),
            "case_id": created.get("case_id"),
            "case_count": created.get("case_count"),
            "case": _clip(case, 300),
            "golden_yaml": _clip(snippet, 4000),
        })

    def list_prompts(self, project: str | None = None) -> dict:
        proj = self.project(project)
        catalog = self._api().list_prompt_catalog(proj)
        return {
            "project": proj,
            "count": len(catalog),
            "prompts": [
                _compact({
                    "prompt_name": p.get("prompt_name"),
                    "latest_version": p.get("version"),
                    "model": p.get("model") or None,
                    "temperature": p.get("temperature"),
                    "commit_message": _clip(p.get("commit_message") or None, 200),
                    "author": p.get("author") or None,
                    "created_at": p.get("created_at"),
                    "content_preview": _clip(p.get("content"), 200),
                })
                for p in catalog
            ],
        }

    def diff_prompts(
        self,
        prompt_name: str,
        version_a: str | int,
        version_b: str | int,
        project: str | None = None,
        max_lines: int = 200,
    ) -> dict:
        proj = self.project(project)
        a, b = parse_prompt_version(version_a), parse_prompt_version(version_b)
        diff = self._api().diff_prompts(proj, prompt_name, a, b)
        lines = diff.get("diff_lines") or []
        max_lines = max(1, min(int(max_lines), 1000))
        return _compact({
            "project": proj,
            "prompt_name": diff.get("prompt_name", prompt_name),
            "version_a": diff.get("version_a", a),
            "version_b": diff.get("version_b", b),
            "additions": diff.get("additions"),
            "deletions": diff.get("deletions"),
            "identical": not lines,
            "diff": "\n".join(str(line).rstrip("\n") for line in lines[:max_lines]),
            "omitted_lines": max(0, len(lines) - max_lines) or None,
        })


# ── MCP wiring ─────────────────────────────────────────────────────────────

def _mcp_api() -> tuple[Any, type[Exception]]:
    """Return (server class, ToolError class) for the installed mcp major version."""
    try:
        from mcp.server.mcpserver import MCPServer  # mcp >= 2
        from mcp.server.mcpserver.exceptions import ToolError

        return MCPServer, ToolError
    except ImportError:
        pass
    try:
        from mcp.server.fastmcp import FastMCP  # mcp 1.x
        from mcp.server.fastmcp.exceptions import ToolError as LegacyToolError

        return FastMCP, LegacyToolError
    except ImportError as exc:
        raise MCPNotInstalledError(_INSTALL_HINT) from exc


def _http_error_message(exc: Any) -> str:
    response = exc.response
    detail: Any = None
    try:
        body = response.json()
        detail = body.get("detail", body) if isinstance(body, dict) else body
    except Exception:
        detail = (response.text or "")[:300]
    if isinstance(detail, dict):
        detail = detail.get("message") or detail.get("error") or json.dumps(detail)[:300]
    code = response.status_code
    hint = {
        401: "The API key was rejected; check CORTEXOPS_API_KEY.",
        402: "This feature needs a CortexOps Pro plan.",
        429: "Rate limit or monthly quota reached.",
    }.get(code, "")
    if code == 403 and "read_only" in str(detail) and "read_write" not in str(detail):
        hint = "This key is read_only; promoting traces needs a read_write key."
    return " ".join(p for p in (f"CortexOps API returned {code}: {detail}", hint) if p)


def _guard(tools: CortexOpsTools, tool_error: type[Exception], fn: Callable[..., Any]) -> Callable[..., Any]:
    """Run blocking client calls off the event loop and turn expected failures into MCP tool errors."""

    async def run(*args: Any, **kwargs: Any) -> str:
        import anyio.to_thread
        import httpx

        try:
            result = await anyio.to_thread.run_sync(functools.partial(fn, *args, **kwargs))
        except ToolInputError as exc:
            raise tool_error(str(exc)) from None
        except httpx.HTTPStatusError as exc:
            raise tool_error(_http_error_message(exc)) from None
        except httpx.RequestError as exc:
            raise tool_error(
                f"Could not reach the CortexOps API at {tools.settings.api_url} ({type(exc).__name__}). "
                "Check CORTEXOPS_API_URL and that the API is running."
            ) from None
        return dump(result)

    return run


def build_server(
    tools: CortexOpsTools | None = None,
    *,
    settings: Settings | None = None,
    host: str = "127.0.0.1",
    port: int = 8765,
) -> Any:
    """Create the MCP server (MCPServer on mcp 2.x, FastMCP on mcp 1.x) with all CortexOps tools registered."""
    server_cls, tool_error = _mcp_api()
    from mcp.types import ToolAnnotations

    if tools is None:
        settings = settings or resolve_settings()
        client = CortexClient(api_key=settings.api_key, base_url=settings.api_url) if settings.api_key else None
        tools = CortexOpsTools(client, settings)

    kwargs: dict[str, Any] = {"instructions": SERVER_INSTRUCTIONS, "log_level": "WARNING"}
    if server_cls.__name__ == "FastMCP":
        kwargs.update(host=host, port=port)
    server = server_cls("cortexops", **kwargs)
    read_only = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)
    g = functools.partial(_guard, tools, tool_error)

    def tool(name: str, title: str, annotations: Any = read_only) -> Callable[[Callable[..., Any]], Any]:
        return server.tool(name=name, title=title, annotations=annotations, structured_output=False)

    @tool("whoami", "Who am I / quota")
    async def whoami() -> str:
        """Show the project bound to the API key, plan tier, monthly trace quota, retention, API URL,
        and the default project used when tools are called without `project`."""
        return await g(tools.whoami)()

    @tool("list_traces", "List traces")
    async def list_traces(
        project: str | None = None,
        status: str | None = None,
        environment: str | None = None,
        prompt_name: str | None = None,
        prompt_version: str | None = None,
        since: str | None = None,
        until: str | None = None,
        limit: int = 20,
    ) -> str:
        """List recent agent traces, newest first.

        Filters: status ("failed" | "completed"), environment (e.g. "production"), prompt_name and
        prompt_version (exact labels set via tracer.set_prompt, e.g. "v3"), since/until (ISO 8601 or
        relative like "24h", "7d"). limit: 1-200 (default 20). Example: which traces failed after prompt
        v3 -> status="failed", prompt_version="v3"."""
        return await g(tools.list_traces)(
            project, status, environment, prompt_name, prompt_version, since, until, limit,
        )

    @tool("get_trace", "Get trace waterfall")
    async def get_trace(trace_id: str, max_nodes: int = 40) -> str:
        """Get one trace: status, failure kind/detail, prompt version, input/output, and a summarized
        node waterfall with tool calls (args, results, errors, latency). Long values are truncated."""
        return await g(tools.get_trace)(trace_id, max_nodes)

    @tool("failures_by_prompt", "Failures by prompt version")
    async def failures_by_prompt(
        project: str | None = None,
        prompt_name: str | None = None,
        since: str | None = "7d",
        until: str | None = None,
        environment: str | None = None,
        limit: int = 500,
    ) -> str:
        """Group recent traces by prompt name/version and report traces, failures, failure rate,
        failure_kind breakdown, and sample failed trace ids. Analyzes up to `limit` (max 500) most recent
        traces in the window (default last 7 days). Use it to spot which prompt version regressed."""
        return await g(tools.failures_by_prompt)(project, prompt_name, since, until, environment, limit)

    @tool("list_evals", "List eval runs")
    async def list_evals(project: str | None = None, limit: int = 10) -> str:
        """List recent eval runs with pass/fail counts, task completion, tool accuracy, p50/p95 latency,
        and regressions vs baseline. limit: 1-100."""
        return await g(tools.list_evals)(project, limit)

    @tool("get_eval", "Get eval run")
    async def get_eval(run_id: str, include_passed: bool = False, max_cases: int = 50) -> str:
        """Get one eval run's summary and its case results (failed cases only unless include_passed)."""
        return await g(tools.get_eval)(run_id, include_passed, max_cases)

    @tool("diff_evals", "Diff two eval runs")
    async def diff_evals(run_id_a: str, run_id_b: str) -> str:
        """Compare eval run B (candidate) against run A (baseline): metric deltas plus regressed and
        improved case ids."""
        return await g(tools.diff_evals)(run_id_a, run_id_b)

    @tool("list_datasets", "List golden datasets")
    async def list_datasets() -> str:
        """List the golden eval datasets of the key's project (id, name, case count)."""
        return await g(tools.list_datasets)()

    @tool("list_prompts", "List prompt catalog")
    async def list_prompts(project: str | None = None) -> str:
        """List the prompt registry: latest version of each prompt with model, temperature, commit
        message, and a content preview."""
        return await g(tools.list_prompts)(project)

    @tool("diff_prompts", "Diff prompt versions")
    async def diff_prompts(
        prompt_name: str,
        version_a: str,
        version_b: str,
        project: str | None = None,
        max_lines: int = 200,
    ) -> str:
        """Unified diff between two registry versions of a prompt. Versions are registry integers;
        "3" and "v3" are both accepted."""
        return await g(tools.diff_prompts)(prompt_name, version_a, version_b, project, max_lines)

    if tools.settings.allow_writes:
        write = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False)

        @tool("promote_trace_to_dataset", "Promote trace to golden dataset (writes)", annotations=write)
        async def promote_trace_to_dataset(trace_id: str, dataset: str, case_id: str | None = None) -> str:
            """WRITE OPERATION: append a new golden eval case built from a trace to a dataset.
            `dataset` is a dataset id or exact name (see list_datasets). Optional case_id (2-64 chars);
            defaults to prod-<trace id prefix>. Returns the case plus a YAML snippet for a local golden
            file. Requires a read_write API key. Confirm with the user first."""
            return await g(tools.promote_trace_to_dataset)(trace_id, dataset, case_id)

    @server.prompt(name="investigate_failures", description="Find which prompt version is failing and why.")
    def investigate_failures(prompt_name: str = "", since: str = "24h") -> str:
        scope = f"prompt '{prompt_name}'" if prompt_name else "all prompts"
        return (
            f"Investigate CortexOps agent failures for {scope} since {since}.\n"
            f"1. Call failures_by_prompt(since='{since}'"
            + (f", prompt_name='{prompt_name}'" if prompt_name else "")
            + ") and identify the prompt version with the highest failure rate.\n"
            "2. Call list_traces(status='failed', prompt_version=<that version>) and get_trace on 2-3 of them.\n"
            "3. Summarize the common failure_kind, the failing tool calls or outputs, and a likely root cause.\n"
            "4. If list_prompts shows that prompt in the registry, use diff_prompts against the previous version.\n"
            "5. Suggest which failed traces to promote into a golden dataset; only promote after the user agrees."
        )

    return server


def _run_http(server: Any, host: str, port: int) -> None:
    settings = getattr(server, "settings", None)
    if settings is not None and hasattr(settings, "host"):  # mcp 1.x: host/port live on FastMCP settings
        settings.host, settings.port = host, port
        server.run(transport="streamable-http")
    else:
        server.run(transport="streamable-http", host=host, port=port)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="cortexops-mcp",
        description="CortexOps MCP server: query traces, evals, datasets, and prompts from an MCP client.",
    )
    parser.add_argument("--transport", choices=["stdio", "streamable-http"], default="stdio")
    parser.add_argument("--host", default="127.0.0.1", help="bind address for streamable-http (default 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8765, help="port for streamable-http (default 8765)")
    parser.add_argument("--project", default=None, help="default project (overrides CORTEXOPS_PROJECT)")
    parser.add_argument("--api-url", default=None, help="API base URL (overrides CORTEXOPS_API_URL)")
    parser.add_argument(
        "--allow-writes", action="store_true", default=None,
        help="expose mutating tools such as promote_trace_to_dataset (or CORTEXOPS_MCP_ALLOW_WRITES=1)",
    )
    args = parser.parse_args(argv)

    settings = resolve_settings(api_url=args.api_url, project=args.project, allow_writes=args.allow_writes)
    try:
        server = build_server(settings=settings, host=args.host, port=args.port)
    except MCPNotInstalledError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if not settings.api_key:
        print(
            "cortexops-mcp: no API key found (CORTEXOPS_API_KEY or ~/.cortexops/credentials); "
            "tools will return a configuration error until one is set.",
            file=sys.stderr,
        )
    if args.transport == "stdio":
        server.run(transport="stdio")
    else:
        _run_http(server, args.host, args.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
