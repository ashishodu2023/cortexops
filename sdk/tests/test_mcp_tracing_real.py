"""MCP tool-call tracing against a real in-process MCP server (skipped when `mcp` is not installed)."""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("mcp")

from cortexops import CortexTracer  # noqa: E402
from cortexops.integrations.mcp import MCPToolError, instrument_mcp_session, mcp_node, trace_run  # noqa: E402
from cortexops.models import FailureKind, RunStatus, ToolCallStatus  # noqa: E402
from tests.mcp_compat import connect, server_class, session_of, tool_error_class  # noqa: E402


def _server():
    server = server_class()("billing")

    @server.tool()
    def add(a: int, b: int) -> int:
        """Add two integers."""
        return a + b

    @server.tool()
    def lookup_invoice(invoice_id: str, api_key: str = "") -> str:
        """Return an invoice summary."""
        return f"invoice {invoice_id}: $42.00 paid"

    @server.tool()
    def refund(invoice_id: str) -> str:
        """Refund an invoice (always fails here)."""
        raise tool_error_class()(f"invoice {invoice_id} is already refunded")

    return server


def test_real_session_calls_are_traced():
    tracer = CortexTracer(project="mcp-real", sample_rate=1.0)

    async def main():
        async with connect(_server()) as client:
            session = instrument_mcp_session(session_of(client), tracer, server_name="billing")
            async with trace_run(tracer, input={"task": "refund INV-7"}) as trace:
                total = await session.call_tool("add", {"a": 2, "b": 3})
                invoice = await session.call_tool("lookup_invoice", {"invoice_id": "INV-7", "api_key": "sk-x"})
                failed = await session.call_tool("refund", {"invoice_id": "INV-7"})
                trace.output = {"done": True}
            return total, invoice, failed

    total, invoice, failed = asyncio.run(main())
    trace = tracer.last_trace()
    assert trace.status == RunStatus.COMPLETED
    calls = trace.tool_calls()
    assert [tc.name for tc in calls] == ["billing/add", "billing/lookup_invoice", "billing/refund"]

    add, lookup, refund = calls
    assert add.status == ToolCallStatus.SUCCESS and add.args == {"a": 2, "b": 3}
    assert "5" in str(add.result)
    assert lookup.args == {"invoice_id": "INV-7", "api_key": "[REDACTED]"}
    assert "$42.00 paid" in str(lookup.result)
    assert refund.status == ToolCallStatus.ERROR
    assert "already refunded" in refund.error
    assert trace.metadata["mcp_tool_errors"] == 1
    assert all(tc.latency_ms > 0 for tc in calls)


def test_real_session_raise_on_error_marks_tool_error():
    tracer = CortexTracer(project="mcp-real", sample_rate=1.0)

    async def main():
        async with connect(_server()) as client:
            session = instrument_mcp_session(session_of(client), tracer, server_name="billing", raise_on_error=True)
            with pytest.raises(MCPToolError, match="already refunded"):
                async with trace_run(tracer):
                    async with mcp_node(tracer, "refund-step"):
                        await session.call_tool("refund", {"invoice_id": "INV-9"})

    asyncio.run(main())
    trace = tracer.last_trace()
    assert trace.status == RunStatus.FAILED
    assert trace.failure_kind == FailureKind.TOOL_ERROR
    assert trace.nodes[0].node_name == "refund-step"
    assert trace.nodes[0].tool_calls[0].name == "billing/refund"


def test_mcp_v2_client_instrumented_once():
    mcp = pytest.importorskip("mcp")
    if not hasattr(mcp, "Client"):
        pytest.skip("mcp.Client is mcp 2.x only")
    tracer = CortexTracer(project="mcp-real", sample_rate=1.0)

    async def main():
        async with connect(_server()) as client:
            instrument_mcp_session(client.session, tracer, server_name="billing")
            instrument_mcp_session(client, tracer, server_name="billing", trace_list_tools=True)
            async with trace_run(tracer):
                await client.list_tools()
                await client.call_tool("add", {"a": 1, "b": 1})

    asyncio.run(main())
    names = [tc.name for tc in tracer.last_trace().tool_calls()]
    assert names == ["billing/list_tools", "billing/add"]
