"""Safety failure kinds emitted by the SDK (prompt_injection, tool_misuse) are stored as plain strings."""
from __future__ import annotations

import os
import sqlite3

from conftest import PROJECT


def _case(case_id: str, failure_kind: str) -> dict:
    return {
        "case_id": case_id, "passed": False, "score": 0.0, "task_completion": True,
        "tool_accuracy": 100.0, "latency_ms": 12.0,
        "failure_kind": failure_kind, "failure_detail": f"{failure_kind} detected",
    }


def test_ingest_stores_safety_failure_kinds(client):
    body = {
        "project": PROJECT,
        "total_cases": 2,
        "passed": 0,
        "failed": 2,
        "task_completion_rate": 1.0,
        "tool_accuracy": 100.0,
        "latency_p50_ms": 12.0,
        "latency_p95_ms": 12.0,
        "case_results": [_case("inj_01", "prompt_injection"), _case("misuse_01", "FailureKind.tool_misuse")],
    }
    r = client.post("/v1/evals/ingest", json=body)
    assert r.status_code == 201, r.text

    db_path = os.environ["DATABASE_URL"].split("///", 1)[1]
    with sqlite3.connect(db_path) as conn:
        rows = dict(conn.execute(
            "SELECT case_id, failure_kind FROM case_results WHERE run_id = ?", (r.json()["run_id"],)
        ).fetchall())
    assert rows == {"inj_01": "prompt_injection", "misuse_01": "tool_misuse"}
