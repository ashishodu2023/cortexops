"""Framework auto-detection."""

from cortexops.tracer import CortexTracer
from tests.helpers import make_framework_mock


def test_langgraph():
    mock = make_framework_mock("CompiledStateGraph", "langgraph.graph.graph")
    assert CortexTracer._detect_framework(mock) == "langgraph"


def test_crewai():
    mock = make_framework_mock("Crew", "crewai.crew")
    assert CortexTracer._detect_framework(mock) == "crewai"


def test_google_adk():
    mock = make_framework_mock("Agent", "google.adk.agents")
    assert CortexTracer._detect_framework(mock) == "google_adk"


def test_pydantic_ai():
    mock = make_framework_mock("Agent", "pydantic_ai.agent")
    assert CortexTracer._detect_framework(mock) == "pydantic_ai"


def test_autogen():
    mock = make_framework_mock("AssistantAgent", "autogen.agentchat.assistant_agent", initiate_chat=lambda *a, **k: None)
    assert CortexTracer._detect_framework(mock) == "autogen"


def test_openai_agents():
    mock = make_framework_mock("Agent", "agents.agent")
    assert CortexTracer._detect_framework(mock) == "openai_agents"


def test_generic_fallback():
    def fn(x):
        return x

    assert CortexTracer._detect_framework(fn) == "generic"
