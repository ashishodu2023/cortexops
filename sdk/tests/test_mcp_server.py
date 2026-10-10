"""cortexops.mcp_server tool logic, settings, and CLI behaviour (no `mcp` package required)."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import httpx
import pytest

from cortexops import mcp_server
from cortexops.client import CortexClient
from cortexops.mcp_server import (
    CortexOpsTools,
    Settings,
    ToolInputError,
    dump,
    parse_prompt_version,
    parse_time,
    resolve_settings,
)


class FakeClient:
    def __init__(self, project: str = "acme") -> None:
        self.project_bound = project
        self.calls: list[tuple] = []
        self.traces = [
            {"trace_id": "t1", "status": "failed", "failure_kind": "tool_error", "failure_detail": "x" * 500,
             "prompt_name": "refund", "prompt_version": "v3", "environment": "production",
             "total_latency_ms": 812.4, "created_at": "2026-10-09T10:00:00"},
            {"trace_id": "t2", "status": "failed", "failure_kind": None,
             "prompt_name": "refund", "prompt_version": "v3", "total_latency_ms": 100.0},
            {"trace_id": "t3", "status": "completed", "prompt_name": "refund", "prompt_version": "v3"},
            {"trace_id": "t4", "status": "completed", "prompt_name": "refund", "prompt_version": "v2"},
            {"trace_id": "t5", "status": "failed", "failure_kind": "timeout"},
        ]
        self.datasets = [
            {"id": "ds-1", "name": "golden", "description": "", "case_count": 4, "project": "acme"},
            {"id": "ds-2", "name": "Smoke", "description": "smoke set", "case_count": 1, "project": "acme"},
        ]

    def get_quota(self):
        self.calls.append(("get_quota",))
        return {"project": self.project_bound, "tier": "free", "monthly_traces": {"used": 5, "limit": 5000},
                "retention_days": 7, "features": {"llm_judge": False}}

    def list_traces(self, project, limit=50, **filters):
        self.calls.append(("list_traces", project, limit, filters))
        rows = self.traces
        if filters.get("status"):
            rows = [t for t in rows if t["status"] == filters["status"]]
        if filters.get("prompt_version"):
            rows = [t for t in rows if t.get("prompt_version") == filters["prompt_version"]]
        return rows[:limit]

    def get_trace(self, trace_id):
        nodes = [
            {"node_name": f"n{i}", "latency_ms": 10.26, "tool_calls": [
                {"name": "github/get_issue", "status": "error", "latency_ms": 5, "args": {"q": "y" * 400},
                 "error": "not found"},
            ], "llm_prompt": "p" * 1000}
            for i in range(5)
        ]
        return {"trace_id": trace_id, "project": "acme", "status": "failed", "failure_kind": "tool_error",
                "failure_detail": "boom", "prompt_name": "refund", "prompt_version": "v3",
                "total_latency_ms": 50.0, "raw_trace": {"input": {"q": "hi"}, "output": {}, "nodes": nodes}}

    def list_runs(self, project, limit=10):
        self.calls.append(("list_runs", project, limit))
        return [{"run_id": "r1", "status": "completed", "total_cases": 3, "passed": 2, "failed": 1,
                 "task_completion_rate": 0.66666, "tool_accuracy": 88.888, "latency_p95_ms": 120.4,
                 "regressions": 0, "case_results": [{"case_id": "c1"}]}]

    def get_eval(self, run_id):
        return {"run_id": run_id, "project": "acme", "total_cases": 2, "passed": 1, "failed": 1,
                "case_results": [
                    {"case_id": "ok", "passed": True, "score": 100.0},
                    {"case_id": "bad", "passed": False, "score": 20.0, "failure_kind": "hallucination",
                     "failure_detail": "made up a refund id"},
                ]}

    def diff(self, a, b):
        return {"run_id_a": a, "run_id_b": b, "task_completion_delta": -0.12345, "tool_accuracy_delta": 1.0,
                "latency_p95_delta_ms": 30.2, "regressions": ["c1"], "improvements": []}

    def list_datasets(self):
        return self.datasets

    def add_case_from_trace(self, dataset_id, trace_id, *, case_id=None):
        self.calls.append(("add_case_from_trace", dataset_id, trace_id, case_id))
        return {"dataset_id": dataset_id, "dataset_name": "golden", "case_id": case_id or f"prod-{trace_id[:8]}",
                "case_count": 5, "case": {"id": "prod-t1", "input": "hi"}}

    def list_prompt_catalog(self, project):
        return [{"id": "pv1", "prompt_name": "refund", "version": 3, "content": "You are " + "z" * 400,
                 "model": "gpt-4o", "temperature": 0.2, "commit_message": "tighten", "author": "",
                 "created_at": "2026-10-01T00:00:00"}]

    def diff_prompts(self, project, prompt_name, a, b):
        self.calls.append(("diff_prompts", project, prompt_name, a, b))
        return {"prompt_name": prompt_name, "version_a": a, "version_b": b, "additions": 1, "deletions": 1,
                "diff_lines": ["--- refund v2", "+++ refund v3", "-old", "+new"]}


def _tools(client=None, **settings) -> CortexOpsTools:
    base = {"api_key": "cxo-abcdefgh12345678", "api_url": "http://api.test"}
    base.update(settings)
    return CortexOpsTools(client if client is not None else FakeClient(), Settings(**base))


# ── helpers ────────────────────────────────────────────────────────────────

def test_parse_time_relative_and_iso():
    now = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)
    assert parse_time("24h", now=now) == "2026-10-08T12:00:00"
    assert parse_time("7d", now=now) == "2026-10-02T12:00:00"
    assert parse_time("30m", now=now) == "2026-10-09T11:30:00"
    assert parse_time("2026-10-01T05:00:00Z") == "2026-10-01T05:00:00"
    assert parse_time("2026-10-01T05:00:00-07:00") == "2026-10-01T12:00:00"
    assert parse_time("2026-10-01") == "2026-10-01T00:00:00"
    assert parse_time(None) is None and parse_time("  ") is None
    with pytest.raises(ToolInputError, match="Invalid time"):
        parse_time("last tuesday")


def test_parse_prompt_version():
    assert parse_prompt_version("v3") == 3
    assert parse_prompt_version(" 12 ") == 12
    assert parse_prompt_version(4) == 4
    with pytest.raises(ToolInputError):
        parse_prompt_version("latest")


def test_dump_caps_output():
    small = dump({"a": 1})
    assert json.loads(small) == {"a": 1}
    big = dump({"rows": ["x" * 1000 for _ in range(100)]})
    assert len(big) <= mcp_server._MAX_OUTPUT_CHARS + 100
    many = dump({"rows": [{"k": "v" * 150, "j": i} for i in range(2000)]})
    assert "1950 more items" in many and len(many) <= mcp_server._MAX_OUTPUT_CHARS
    huge = dump({f"k{i}": ["w" * 200] * 50 for i in range(50)})
    assert huge.endswith("more chars]") and len(huge) < mcp_server._MAX_OUTPUT_CHARS + 100


# ── settings ───────────────────────────────────────────────────────────────

def test_resolve_settings_env_wins(monkeypatch):
    monkeypatch.setattr(mcp_server, "load_credentials",
                        lambda: {"api_key": "cxo-file", "api_url": "http://file", "project": "file-proj"})
    monkeypatch.setenv("CORTEXOPS_API_KEY", "cxo-env-key-123456")
    monkeypatch.setenv("CORTEXOPS_API_URL", "http://env/")
    monkeypatch.setenv("CORTEXOPS_PROJECT", "env-proj")
    monkeypatch.setenv("CORTEXOPS_MCP_ALLOW_WRITES", "true")
    s = resolve_settings()
    assert (s.api_key, s.api_url, s.project, s.key_source) == ("cxo-env-key-123456", "http://env", "env-proj",
                                                               "env:CORTEXOPS_API_KEY")
    assert s.fallback_project == "file-proj" and s.allow_writes is True
    assert s.masked_key == "cxo-env-...3456"
    assert resolve_settings(api_url="http://flag", project="flag-proj", allow_writes=False).api_url == "http://flag"


def test_resolve_settings_credentials_file(monkeypatch):
    for var in ("CORTEXOPS_API_KEY", "CORTEXOPS_API_URL", "CORTEXOPS_PROJECT", "CORTEXOPS_MCP_ALLOW_WRITES"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(mcp_server, "load_credentials",
                        lambda: {"api_key": "cxo-file-key-0000", "api_url": "http://file", "project": "p"})
    s = resolve_settings()
    assert (s.api_key, s.api_url, s.key_source, s.allow_writes) == (
        "cxo-file-key-0000", "http://file", "~/.cortexops/credentials", False)
    monkeypatch.setattr(mcp_server, "load_credentials", lambda: None)
    s = resolve_settings()
    assert s.api_key is None and s.api_url == "https://api.getcortexops.com"


# ── project resolution ─────────────────────────────────────────────────────

def test_project_resolution_order():
    client = FakeClient(project="key-proj")
    tools = _tools(client)
    assert tools.project("explicit") == "explicit"
    assert tools.project() == "key-proj"
    assert tools.project() == "key-proj"
    assert [c for c in client.calls if c[0] == "get_quota"] == [("get_quota",)]
    assert _tools(FakeClient(), project="env-proj").project() == "env-proj"
    assert _tools(FakeClient(project="__dev__"), fallback_project="creds-proj").project() == "creds-proj"
    with pytest.raises(ToolInputError, match="CORTEXOPS_PROJECT"):
        _tools(FakeClient(project="__dev__")).project()


def test_missing_key_gives_actionable_error():
    tools = CortexOpsTools(None, Settings(api_key=None, api_url="http://x"))
    with pytest.raises(ToolInputError, match="CORTEXOPS_API_KEY"):
        tools.list_traces()


# ── tools ──────────────────────────────────────────────────────────────────

def test_whoami():
    out = _tools(allow_writes=True).whoami()
    assert out["key_project"] == "acme" and out["default_project"] == "acme"
    assert out["key"] == "cxo-abcd...5678"
    assert out["writes_enabled"] is True
    assert "cxo-abcdefgh12345678" not in json.dumps(out)


def test_list_traces_filters_and_rows():
    client = FakeClient()
    out = _tools(client).list_traces(status="failed", prompt_version="v3", since="2026-10-01T00:00:00Z", limit=999)
    _, project, limit, filters = client.calls[-1]
    assert project == "acme" and limit == 200
    assert filters["status"] == "failed" and filters["prompt_version"] == "v3"
    assert filters["since"] == "2026-10-01T00:00:00" and filters["until"] is None
    assert out["count"] == 2 and out["more_available"] is False
    row = out["traces"][0]
    assert row["prompt"] == "refund@v3" and row["latency_ms"] == 812
    assert row["failure_detail"].endswith("[truncated 300 chars]")
    assert "failure_kind" not in out["traces"][1]


def test_get_trace_summarizes_waterfall():
    out = _tools().get_trace("t1", max_nodes=3)
    assert out["node_count"] == 5 and out["omitted_nodes"] == 2
    assert len(out["waterfall"]) == 3
    node = out["waterfall"][0]
    assert node["node"] == "n0" and node["latency_ms"] == 10
    assert node["tool_calls"][0]["error"] == "not found"
    assert "truncated" in node["tool_calls"][0]["args"]["q"]
    assert "truncated" in node["llm_prompt"]
    assert out["input"] == {"q": "hi"}


def test_failures_by_prompt_groups_and_ranks():
    client = FakeClient()
    out = _tools(client).failures_by_prompt(since="7d")
    assert client.calls[-1][2] == 500
    assert out["traces_analyzed"] == 5
    top = out["groups"][0]
    assert (top["prompt_name"], top["prompt_version"]) == ("refund", "v3")
    assert top["traces"] == 3 and top["failed"] == 2 and top["failure_rate"] == 0.667
    assert top["failure_kinds"] == {"tool_error": 1, "unknown": 1}
    assert top["sample_failed_trace_ids"] == ["t1", "t2"]
    untagged = next(g for g in out["groups"] if g["prompt_name"] == "(untagged)")
    assert untagged["failure_kinds"] == {"timeout": 1}
    v2 = next(g for g in out["groups"] if g["prompt_version"] == "v2")
    assert v2["failed"] == 0 and "failure_kinds" not in v2


def test_evals_tools():
    tools = _tools()
    runs = tools.list_evals()
    assert runs["eval_runs"][0]["task_completion_rate"] == 0.667
    assert "case_results" not in runs["eval_runs"][0]
    detail = tools.get_eval("r1")
    assert [c["case_id"] for c in detail["case_results"]] == ["bad"]
    assert [c["case_id"] for c in tools.get_eval("r1", include_passed=True)["case_results"]] == ["ok", "bad"]
    diff = tools.diff_evals("a", "b")
    assert diff["task_completion_delta"] == -0.123 and diff["regressions"] == ["c1"]
    assert diff["baseline_run_id"] == "a" and diff["candidate_run_id"] == "b"


def test_datasets_and_promote():
    client = FakeClient()
    read_only = _tools(client)
    assert [d["name"] for d in read_only.list_datasets()["datasets"]] == ["golden", "Smoke"]
    with pytest.raises(ToolInputError, match="--allow-writes"):
        read_only.promote_trace_to_dataset("t1", "golden")

    tools = _tools(client, allow_writes=True)
    out = tools.promote_trace_to_dataset("t1", "smoke", case_id="refund-regression")
    assert client.calls[-1] == ("add_case_from_trace", "ds-2", "t1", "refund-regression")
    assert out["case_id"] == "refund-regression" and out["case_count"] == 5
    assert out["golden_yaml"] == "- id: prod-t1\n  input: hi\n"
    tools.promote_trace_to_dataset("t1", "ds-1")
    assert client.calls[-1][1] == "ds-1"
    with pytest.raises(ToolInputError, match="Available: Smoke, golden"):
        tools.promote_trace_to_dataset("t1", "nope")
    client.datasets.append({"id": "ds-3", "name": "golden"})
    with pytest.raises(ToolInputError, match="Several datasets"):
        tools.promote_trace_to_dataset("t1", "golden")


def test_prompt_tools():
    client = FakeClient()
    tools = _tools(client)
    catalog = tools.list_prompts()
    assert catalog["prompts"][0]["latest_version"] == 3
    assert "truncated" in catalog["prompts"][0]["content_preview"]
    assert "author" not in catalog["prompts"][0]
    diff = tools.diff_prompts("refund", "v2", "3")
    assert client.calls[-1] == ("diff_prompts", "acme", "refund", 2, 3)
    assert diff["diff"].splitlines()[-1] == "+new" and diff["identical"] is False


def test_http_error_messages():
    def err(code, body):
        request = httpx.Request("GET", "http://api.test/v1/x")
        return httpx.HTTPStatusError("boom", request=request, response=httpx.Response(code, json=body,
                                                                                         request=request))

    assert "rejected" in mcp_server._http_error_message(err(401, {"detail": "Invalid API key"}))
    backend_scope = mcp_server._http_error_message(err(403, {"detail": {
        "error": "insufficient_scope",
        "message": "This endpoint requires a read_write key. Your key has read_only scope.",
    }}))
    assert backend_scope == ("CortexOps API returned 403: This endpoint requires a read_write key. "
                             "Your key has read_only scope.")
    terse_scope = mcp_server._http_error_message(err(403, {"detail": "key is read_only"}))
    assert terse_scope.endswith("promoting traces needs a read_write key.")
    assert "404: Trace t9 not found" in mcp_server._http_error_message(err(404, {"detail": "Trace t9 not found"}))


# ── client additions ───────────────────────────────────────────────────────

def test_client_list_traces_sends_filters():
    client = CortexClient(api_key="cxo-test", base_url="http://api.test")
    response = MagicMock()
    response.json.return_value = []
    with patch("httpx.get", return_value=response) as get:
        client.list_traces("acme", 10, status="failed", prompt_version="v3", since="2026-10-01T00:00:00")
        params = get.call_args.kwargs["params"]
        assert params == {"project": "acme", "limit": 10, "status": "failed", "prompt_version": "v3",
                          "from": "2026-10-01T00:00:00"}
        client.list_traces("acme")
        assert get.call_args.kwargs["params"] == {"project": "acme", "limit": 50}
        client.get_quota()
        assert get.call_args.args[0] == "http://api.test/v1/traces/quota"
        client.diff_prompts("acme", "refund", 1, 2)
        assert get.call_args.args[0] == "http://api.test/v1/prompts/diff"
        assert get.call_args.kwargs["params"]["version_b"] == 2
        client.list_prompt_versions("acme", "refund")
        assert get.call_args.kwargs["params"] == {"project": "acme", "prompt_name": "refund", "limit": 20}


# ── CLI ────────────────────────────────────────────────────────────────────

def test_main_without_mcp_installed_prints_install_hint(monkeypatch, capsys):
    for name in ("mcp", "mcp.server", "mcp.server.mcpserver", "mcp.server.mcpserver.exceptions",
                 "mcp.server.fastmcp", "mcp.server.fastmcp.exceptions", "mcp.types"):
        monkeypatch.setitem(sys.modules, name, None)
    assert mcp_server.main([]) == 1
    assert "pip install 'cortexops[mcp]'" in capsys.readouterr().err


def test_console_script_registered():
    try:
        import tomllib
    except ModuleNotFoundError:  # Python 3.10
        pytest.skip("tomllib unavailable")
    from pathlib import Path

    pyproject = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text())
    assert pyproject["project"]["scripts"]["cortexops-mcp"] == "cortexops.mcp_server:main"
    assert any(dep.startswith("mcp") for dep in pyproject["project"]["optional-dependencies"]["mcp"])
