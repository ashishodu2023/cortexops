from unittest.mock import MagicMock
from cortexops import CortexTracer, RunStatus
from tests.helpers import make_framework_mock


def test_crewai_wrap_traces():
    tracer = CortexTracer(project="test", sample_rate=1.0)
    mock = make_framework_mock("Crew", "crewai.crew")
    mock.kickoff = MagicMock(return_value="done")
    wrapped = tracer.wrap(mock)
    assert wrapped.kickoff(inputs={"ticket": "1"}) == "done"
    assert tracer.last_trace().status == RunStatus.COMPLETED
