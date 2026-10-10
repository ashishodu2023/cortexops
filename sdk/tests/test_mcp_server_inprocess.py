"""cortexops MCP server exercised through a real MCP client session (skipped when `mcp` is not installed)."""

from __future__ import annotations

import asyncio

import httpx
import pytest

pytest.importorskip("mcp")

from cortexops.mcp_server import CortexOpsTools, Settings, build_server  # noqa: E402
from tests.mcp_compat import connect, is_error, payload, text  # noqa: E402
from tests.test_mcp_server import FakeClient  # noqa: E402

READ_TOOLS = {
    "whoami", "list_traces", "get_trace", "failures_by_prompt", "list_evals", "get_eval",
    "diff_evals", "list_datasets", "list_prompts", "diff_prompts",
}


def _server(client=None, **settings):
    base = {"api_key": "cxo-abcdefgh12345678", "api_url": "http://api.test"}
    base.update(settings)
    return build_server(CortexOpsTools(client or FakeClient(), Settings(**base)))


def _annotations(tool):
    ann = tool.annotations
    return getattr(ann, "read_only_hint", None) if hasattr(ann, "read_only_hint") else ann.readOnlyHint


def test_read_only_by_default():
    async def main():
        async with connect(_server()) as client:
            return (await client.list_tools()).tools

    tools = asyncio.run(main())
    assert {t.name for t in tools} == READ_TOOLS
    assert all(_annotations(t) is True for t in tools)


def test_write_tool_exposed_only_with_allow_writes():
    fake = FakeClient()

    async def main():
        async with connect(_server(fake, allow_writes=True)) as client:
            tools = {t.name: t for t in (await client.list_tools()).tools}
            result = await client.call_tool("promote_trace_to_dataset", {"trace_id": "t1", "dataset": "golden"})
            return tools, result

    tools, result = asyncio.run(main())
    promote = tools["promote_trace_to_dataset"]
    assert _annotations(promote) is False
    assert promote.description.startswith("WRITE OPERATION")
    assert payload(result)["case_id"] == "prod-t1"
    assert fake.calls[-1] == ("add_case_from_trace", "ds-1", "t1", None)


def test_tools_return_compact_json():
    async def main():
        async with connect(_server()) as client:
            listed = await client.call_tool("list_traces", {"status": "failed", "prompt_version": "v3"})
            grouped = await client.call_tool("failures_by_prompt", {})
            trace = await client.call_tool("get_trace", {"trace_id": "t1", "max_nodes": 2})
            diff = await client.call_tool("diff_prompts", {"prompt_name": "refund", "version_a": "v2",
                                                           "version_b": "v3"})
            who = await client.call_tool("whoami", {})
            return listed, grouped, trace, diff, who

    listed, grouped, trace, diff, who = asyncio.run(main())
    assert [t["trace_id"] for t in payload(listed)["traces"]] == ["t1", "t2"]
    assert payload(grouped)["groups"][0]["failure_rate"] == 0.667
    assert payload(trace)["omitted_nodes"] == 3
    assert payload(diff)["additions"] == 1
    assert payload(who)["key_project"] == "acme"


def test_tool_errors_are_readable():
    class Broken(FakeClient):
        def list_traces(self, project, limit=50, **filters):
            request = httpx.Request("GET", "http://api.test/v1/traces")
            raise httpx.HTTPStatusError("x", request=request, response=httpx.Response(
                403, json={"detail": "You can only access resources for your own project."}, request=request))

        def list_runs(self, project, limit=10):
            raise httpx.ConnectError("refused")

    async def main():
        async with connect(_server(Broken())) as client:
            forbidden = await client.call_tool("list_traces", {"project": "other"})
            offline = await client.call_tool("list_evals", {})
            bad_input = await client.call_tool("list_traces", {"since": "yesterday-ish"})
            return forbidden, offline, bad_input

    forbidden, offline, bad_input = asyncio.run(main())
    assert is_error(forbidden) and "403" in text(forbidden) and "own project" in text(forbidden)
    assert is_error(offline) and "Could not reach the CortexOps API at http://api.test" in text(offline)
    assert is_error(bad_input) and "Invalid time" in text(bad_input)


def test_missing_key_error_through_mcp():
    server = build_server(CortexOpsTools(None, Settings(api_key=None, api_url="http://api.test")))

    async def main():
        async with connect(server) as client:
            return await client.call_tool("whoami", {})

    result = asyncio.run(main())
    assert is_error(result) and "CORTEXOPS_API_KEY" in text(result)


def test_investigate_prompt():
    async def main():
        async with connect(_server()) as client:
            prompts = (await client.list_prompts()).prompts
            got = await client.get_prompt("investigate_failures", {"prompt_name": "refund", "since": "48h"})
            return prompts, got

    prompts, got = asyncio.run(main())
    assert [p.name for p in prompts] == ["investigate_failures"]
    body = got.messages[0].content.text
    assert "failures_by_prompt(since='48h', prompt_name='refund')" in body
