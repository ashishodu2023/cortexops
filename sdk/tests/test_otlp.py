from tests.helpers import make_trace


def test_otlp_payload_has_timestamps():
    payload = make_trace({"output": "ok"}).model_dump(mode="json")
    assert "timestamp" in payload
    assert payload["status"] == "completed"
