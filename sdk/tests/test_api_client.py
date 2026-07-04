"""CortexClient HTTPS upload path (mocked)."""

from unittest.mock import MagicMock, patch

from cortexops.client import CortexClient
from tests.helpers import make_trace


def test_upload_trace():
    client = CortexClient(api_key="cxo-test", base_url="https://api.getcortexops.com")
    trace = make_trace({"output": "ok"}, project="payments-agent")
    with patch.object(client, "_post", return_value={"id": trace.trace_id}) as post:
        resp = client.push_trace(trace)
    assert resp["id"] == trace.trace_id
    post.assert_called_once()
    args, kwargs = post.call_args
    assert args[0] == "/v1/traces"


def test_list_traces():
    client = CortexClient(api_key="cxo-test", base_url="https://api.getcortexops.com")
    with patch.object(client, "_get", return_value=[{"trace_id": "abc"}]) as get:
        rows = client.list_traces("payments-agent", limit=10)
    assert rows[0]["trace_id"] == "abc"
    get.assert_called_once()
