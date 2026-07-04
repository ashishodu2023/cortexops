"""Async-friendly wrappers exist for supported frameworks."""

import asyncio
from unittest.mock import MagicMock

from cortexops import CortexTracer
from tests.helpers import make_framework_mock


def test_langgraph_ainvoke_exists():
    tracer = CortexTracer(project="p", sample_rate=1.0)
    mock = make_framework_mock("CompiledStateGraph", "langgraph.graph.graph")
    mock.invoke = MagicMock(return_value={"ok": True})
    wrapped = tracer.wrap(mock)
    assert hasattr(wrapped, "ainvoke")

    result = asyncio.run(wrapped.ainvoke({"messages": []}))
    assert result["ok"] is True
