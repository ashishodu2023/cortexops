"""Shared helpers for CortexOps SDK integration tests."""

from __future__ import annotations

from cortexops.models import (
    RunStatus,
    ToolCall,
    ToolCallStatus,
    Trace,
    TraceNode,
)


def make_trace(
    output: dict | None = None,
    tool_calls: list[str] | None = None,
    latency_ms: float = 100.0,
    *,
    project: str = "test",
    llm_prompt: str | None = None,
    llm_response: str | None = None,
    parent_nodes: list[TraceNode] | None = None,
) -> Trace:
    tcs = [ToolCall(name=n, status=ToolCallStatus.SUCCESS) for n in (tool_calls or [])]
    nodes = parent_nodes or [
        TraceNode(
            node_id="n1",
            node_name="agent",
            output=output or {},
            tool_calls=tcs,
            latency_ms=latency_ms,
            llm_prompt=llm_prompt,
            llm_response=llm_response,
        )
    ]
    return Trace(
        project=project,
        total_latency_ms=latency_ms,
        output=output or {},
        nodes=nodes,
        status=RunStatus.COMPLETED,
    )


def make_framework_mock(class_name: str, module: str, **attrs):
    """Build a lightweight stand-in with the given class name/module for detection."""
    cls = type(class_name, (), {"__module__": module})
    obj = cls()
    for key, value in attrs.items():
        setattr(obj, key, value)
    return obj
