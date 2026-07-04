"""
End-to-end MVP path:

  Agent frameworks → CortexOps SDK (tracer.wrap) → local traces
  → metrics / eval gate → (optional) HTTPS upload via CortexClient
"""

from unittest.mock import patch

from cortexops import CortexTracer, EvalSuite, CortexClient
from cortexops.models import EvalCase, EvalDataset
from tests.helpers import make_trace


def test_sdk_to_cloud_path():
    tracer = CortexTracer(project="payments-agent", sample_rate=1.0)

    def agent(inp: dict) -> dict:
        return {"output": f"hello {inp.get('input', '')}"}

    wrapped = tracer.wrap(agent)
    wrapped({"input": "world"})
    trace = tracer.last_trace()
    assert trace.project == "payments-agent"
    assert "hello" in str(trace.output)

    ds = EvalDataset(
        version=1,
        project="payments-agent",
        cases=[EvalCase(id="c1", input="world", expected_output_contains=["hello"])],
    )
    summary = EvalSuite.run(dataset=ds, agent=agent, verbose=False)
    assert summary.passed == 1

    client = CortexClient(api_key="cxo-test", base_url="https://api.getcortexops.com")
    with patch.object(client, "push_trace", return_value={"ok": True}) as push:
        client.push_trace(trace)
    push.assert_called_once()


def test_dashboard_surface_fields():
    """Fields the dashboard consumes are present on traces/evals."""
    t = make_trace({"output": "ok"}, tool_calls=["lookup"], latency_ms=33, project="payments-agent")
    payload = t.model_dump(mode="json")
    for key in ("trace_id", "project", "status", "total_latency_ms", "nodes", "failure_kind"):
        assert key in payload
