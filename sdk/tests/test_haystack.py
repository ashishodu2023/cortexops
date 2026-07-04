from unittest.mock import MagicMock
from cortexops import CortexTracer, RunStatus
from tests.helpers import make_framework_mock


def test_haystack_wrap_traces():
    tracer = CortexTracer(project="test", sample_rate=1.0)
    mock = make_framework_mock("Pipeline", "haystack.core.pipeline.pipeline")
    mock.run = MagicMock(return_value={"out": 1})
    wrapped = tracer.wrap(mock)
    assert wrapped.run({"query": "x"})["out"] == 1
    assert tracer.last_trace().status == RunStatus.COMPLETED
