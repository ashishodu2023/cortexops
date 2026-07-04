from tests.helpers import make_trace


def test_grafana_tempo_fields():
    t = make_trace({"output": "ok"})
    span = {"traceId": t.trace_id, "operationName": "agent.run", "tags": {"project": t.project}}
    assert span["traceId"]
    assert span["tags"]["project"] == "test"
