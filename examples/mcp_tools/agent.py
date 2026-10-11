"""Trace MCP tool calls with CortexOps.

    pip install 'cortexops[mcp]'
    python examples/mcp_tools/agent.py

Starts server.py over stdio, runs two refund tasks, and prints each trace's MCP tool calls.
Set CORTEXOPS_API_KEY (or run `cortexops login`) to also ship the traces to the hosted API.
"""
import asyncio
import sys
from pathlib import Path

from cortexops import CortexTracer
from cortexops.integrations.mcp import instrument_mcp_session, trace_run
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

tracer = CortexTracer(project="mcp-tools-demo")
tracer.set_prompt("refund-agent", "v1")


async def refund(session: ClientSession, order_id: str) -> str:
    async with trace_run(tracer, input={"task": f"refund {order_id}"}) as trace:
        await session.call_tool("lookup_order", {"order_id": order_id})
        result = await session.call_tool("issue_refund", {"order_id": order_id, "reason": "customer request"})
        trace.output = {"refunded": not (getattr(result, "is_error", None) or getattr(result, "isError", None))}
        return trace.trace_id


async def main() -> None:
    params = StdioServerParameters(command=sys.executable, args=[str(Path(__file__).with_name("server.py"))])
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        instrument_mcp_session(session, tracer, server_name="billing")
        await refund(session, "ORD-1")
        await refund(session, "ORD-2")  # already refunded: the MCP tool returns isError=true

    for trace in tracer.traces():
        errors = trace.metadata.get("mcp_tool_errors", 0)
        print(f"trace {trace.trace_id[:8]} status={trace.status.value} tool_errors={errors}")
        for tc in trace.tool_calls():
            print(f"  {tc.name:<22} {tc.status.value:<8} {tc.latency_ms:6.1f}ms  {tc.error or tc.result}")
    print("hosted" if tracer.is_hosted else "local only (set CORTEXOPS_API_KEY to ship traces)")


if __name__ == "__main__":
    asyncio.run(main())
