from unittest.mock import MagicMock
from cortexops import CortexTracer, RunStatus
from tests.helpers import make_framework_mock


def test_pydantic_ai_wrap_traces():
    tracer = CortexTracer(project="test", sample_rate=1.0)
    mock = make_framework_mock("Agent", "pydantic_ai.agent")
    result = MagicMock()
    result.data = "refund_approved"
    mock.run_sync = MagicMock(return_value=result)
    wrapped = tracer.wrap(mock)
    assert wrapped.run_sync("Process refund").data == "refund_approved"
    assert tracer.last_trace().status == RunStatus.COMPLETED
