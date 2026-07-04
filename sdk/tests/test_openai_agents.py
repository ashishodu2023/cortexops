from cortexops.tracer import CortexTracer
from tests.helpers import make_framework_mock


def test_openai_agents_detected():
    mock = make_framework_mock("Agent", "agents.agent")
    assert CortexTracer._detect_framework(mock) == "openai_agents"
