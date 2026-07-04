from cortexops.tracer import CortexTracer
from tests.helpers import make_framework_mock


def test_agno_detected():
    mock = make_framework_mock("Agent", "agno.agent.agent")
    assert CortexTracer._detect_framework(mock) == "agno"
