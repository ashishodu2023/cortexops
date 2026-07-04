from unittest.mock import MagicMock
from cortexops import CortexTracer, RunStatus
from tests.helpers import make_framework_mock


def test_langgraph_wrap_traces():
    tracer = CortexTracer(project="test", sample_rate=1.0)
    mock = make_framework_mock("CompiledStateGraph", "langgraph.graph.graph")
    mock.invoke = MagicMock(return_value={"messages": ["ok"]})
    wrapped = tracer.wrap(mock)
    result = wrapped.invoke({"messages": ["hi"]})
    assert result["messages"] == ["ok"]
    assert tracer.last_trace().status == RunStatus.COMPLETED
