"""Judge cost and token usage are accepted on ingest and returned on every eval read path."""
from __future__ import annotations

import uuid

from conftest import PROJECT


def _body(**extra) -> dict:
    case = {
        "case_id": "c1", "passed": True, "score": 100.0,
        "task_completion": True, "tool_accuracy": 100.0, "latency_ms": 10.0,
    }
    case.update(extra.pop("case", {}))
    return {
        "run_id": str(uuid.uuid4()),
        "project": PROJECT,
        "total_cases": 1,
        "passed": 1,
        "failed": 0,
        "task_completion_rate": 1.0,
        "tool_accuracy": 100.0,
        "latency_p50_ms": 10.0,
        "latency_p95_ms": 20.0,
        "case_results": [case],
        **extra,
    }


def test_judge_cost_round_trips(client):
    body = _body(
        judge_cost_usd=0.00045, judge_tokens_in=1000, judge_tokens_out=500,
        case={"judge_cost_usd": 0.00045, "judge_tokens_in": 1000, "judge_tokens_out": 500},
    )
    created = client.post("/v1/evals/ingest", json=body)
    assert created.status_code == 201, created.text

    fetched = client.get(f"/v1/evals/{body['run_id']}")
    assert fetched.status_code == 200, fetched.text
    runs = client.get("/v1/evals", params={"project": PROJECT}).json()
    listed = next(r for r in runs if r["run_id"] == body["run_id"])
    for run in (created.json(), fetched.json(), listed):
        assert (run["judge_cost_usd"], run["judge_tokens_in"], run["judge_tokens_out"]) == (0.00045, 1000, 500)
        assert run["case_results"][0]["judge_cost_usd"] == 0.00045


def test_payload_without_cost_fields_is_accepted(client):
    r = client.post("/v1/evals/ingest", json=_body())
    assert r.status_code == 201, r.text
    run = r.json()
    assert (run["judge_cost_usd"], run["judge_tokens_in"], run["judge_tokens_out"]) == (None, None, None)
    assert run["case_results"][0]["judge_cost_usd"] is None


def test_unknown_cost_with_known_tokens(client):
    r = client.post("/v1/evals/ingest", json=_body(judge_tokens_in=10, judge_tokens_out=5))
    assert r.status_code == 201, r.text
    assert (r.json()["judge_cost_usd"], r.json()["judge_tokens_in"]) == (None, 10)


def test_negative_cost_rejected(client):
    r = client.post("/v1/evals/ingest", json=_body(judge_cost_usd=-1.0))
    assert r.status_code == 422
