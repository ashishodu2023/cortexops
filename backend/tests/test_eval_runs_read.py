"""Reading eval runs back: GET /v1/evals/{run_id} and /v1/evals/diff."""
from __future__ import annotations

from conftest import PROJECT


def _ingest(client, score_c2: float) -> str:
    passed_c2 = score_c2 >= 50
    body = {
        "project": PROJECT,
        "total_cases": 2,
        "passed": 1 + passed_c2,
        "failed": 0 if passed_c2 else 1,
        "task_completion_rate": 1.0 if passed_c2 else 0.5,
        "tool_accuracy": (100.0 + score_c2) / 2,
        "latency_p50_ms": 10.0,
        "latency_p95_ms": 20.0,
        "case_results": [
            {"case_id": "c1", "passed": True, "score": 100.0, "task_completion": True,
             "tool_accuracy": 100.0, "latency_ms": 10.0},
            {"case_id": "c2", "passed": passed_c2, "score": score_c2, "task_completion": passed_c2,
             "tool_accuracy": score_c2, "latency_ms": 12.0,
             "failure_kind": None if passed_c2 else "hallucination"},
        ],
    }
    r = client.post("/v1/evals/ingest", json=body)
    assert r.status_code == 201, r.text
    return r.json()["run_id"]


def test_get_eval_run_includes_case_results(client):
    run_id = _ingest(client, score_c2=20.0)

    r = client.get(f"/v1/evals/{run_id}")

    assert r.status_code == 200, r.text
    cases = {c["case_id"]: c for c in r.json()["case_results"]}
    assert set(cases) == {"c1", "c2"}
    assert cases["c2"]["failure_kind"] == "hallucination"


def test_diff_eval_runs(client):
    baseline = _ingest(client, score_c2=95.0)
    candidate = _ingest(client, score_c2=20.0)

    r = client.get("/v1/evals/diff", params={"a": baseline, "b": candidate})

    assert r.status_code == 200, r.text
    assert r.json()["regressions"] == ["c2"]


def test_get_eval_run_404(client):
    assert client.get("/v1/evals/does-not-exist").status_code == 404
