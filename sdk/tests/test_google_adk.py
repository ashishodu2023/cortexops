from unittest.mock import MagicMock
from cortexops import CortexTracer, RunStatus
from tests.helpers import make_framework_mock


def test_google_adk_wrap_traces():
    tracer = CortexTracer(project="test", sample_rate=1.0)
    mock = make_framework_mock("Agent", "google.adk.agents")
    mock.run = MagicMock(return_value={"ok": True})
    wrapped = tracer.wrap(mock)
    assert wrapped.run("hello")["ok"] is True
    assert tracer.last_trace().status == RunStatus.COMPLETED
