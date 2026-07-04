from unittest.mock import MagicMock
from cortexops import CortexTracer, RunStatus
from tests.helpers import make_framework_mock


def test_llamaindex_query_wrap_traces():
    tracer = CortexTracer(project="test", sample_rate=1.0)
    mock = make_framework_mock("RetrieverQueryEngine", "llama_index.core.query_engine")
    mock.query = MagicMock(return_value="policy text")
    wrapped = tracer.wrap(mock)
    assert wrapped.query("refund policy") == "policy text"
    assert tracer.last_trace().status == RunStatus.COMPLETED
