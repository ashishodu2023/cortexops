from unittest.mock import MagicMock
from cortexops.tracer import CortexTracer
from tests.helpers import make_framework_mock


def test_autogen_detected():
    mock = make_framework_mock(
        "AssistantAgent",
        "autogen.agentchat.assistant_agent",
        initiate_chat=MagicMock(),
    )
    assert CortexTracer._detect_framework(mock) == "autogen"
