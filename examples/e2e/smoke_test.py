#!/usr/bin/env python3
"""
CortexOps production smoke test — fast post-deploy verification.

Usage:
    export CORTEXOPS_API_KEY=cxo-...
    export CORTEXOPS_PROJECT=my-project
    python smoke_test.py

Exits 0 on success, 1 on any failure.
"""

from __future__ import annotations

import json
import os
import sys
import uuid

import httpx

BASE_URL = os.getenv("CORTEXOPS_API_URL", "https://api.getcortexops.com")
API_KEY = os.getenv("CORTEXOPS_API_KEY", "")
PROJECT = os.getenv("CORTEXOPS_PROJECT", "")

FAILURES: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    status = "ok" if ok else "FAIL"
    print(f"  [{status}] {name}" + (f" — {detail}" if detail else ""))
    if not ok:
        FAILURES.append(name + (f": {detail}" if detail else ""))


def main() -> int:
    if not API_KEY:
        print("Set CORTEXOPS_API_KEY")
        return 1
    if not PROJECT:
        print("Set CORTEXOPS_PROJECT")
        return 1

    print(f"\nCortexOps smoke test")
    print(f"  API:     {BASE_URL}")
    print(f"  Project: {PROJECT}\n")

    # 1. Health
    r = httpx.get(f"{BASE_URL}/health", timeout=15)
    check("health", r.status_code == 200 and r.json().get("status") == "ok",
          f"HTTP {r.status_code}")

    # 2. JWT login
    r = httpx.post(f"{BASE_URL}/v1/auth/token/issue",
                   headers={"X-API-Key": API_KEY}, timeout=15)
    check("jwt issue", r.status_code == 200 and "access_token" in r.json(),
          r.text[:120] if r.status_code != 200 else "")
    token = r.json().get("access_token", "") if r.status_code == 200 else ""
    bearer = {"Authorization": f"Bearer {token}"} if token else {}

    # 3. Quota
    r = httpx.get(f"{BASE_URL}/v1/traces/quota",
                  headers={"X-API-Key": API_KEY}, timeout=15)
    check("quota", r.status_code == 200, f"HTTP {r.status_code}")

    # 4. Ingest + list traces
    payload = {
        "project": PROJECT,
        "case_id": "smoke-test",
        "status": "failed",
        "total_latency_ms": 890.0,
        "failure_kind": "tool_error",
        "failure_detail": "smoke test failure",
        "input": {"query": "smoke test refund"},
        "output": {"error": "tool timeout"},
        "nodes": [{"node_name": "tool_call", "latency_ms": 890,
                   "tool_calls": [{"name": "lookup_refund"}]}],
        "environment": "production",
    }
    r = httpx.post(f"{BASE_URL}/v1/traces",
                   headers={"X-API-Key": API_KEY, "Content-Type": "application/json"},
                   json=payload, timeout=15)
    check("ingest trace", r.status_code == 201, f"HTTP {r.status_code}")
    trace_id = ""
    if r.status_code == 201:
        trace_id = r.json().get("trace_id", "")

    r = httpx.get(f"{BASE_URL}/v1/traces",
                  headers={"X-API-Key": API_KEY},
                  params={"project": PROJECT, "limit": 5}, timeout=15)
    check("list traces", r.status_code == 200 and isinstance(r.json(), list),
          f"HTTP {r.status_code}")

    # 5. Promote failed trace → golden case
    ds_name = f"smoke-{uuid.uuid4().hex[:6]}"
    r = httpx.post(f"{BASE_URL}/v1/eval/datasets",
                   headers={"X-API-Key": API_KEY, "Content-Type": "application/json"},
                   json={"name": ds_name, "description": "smoke",
                         "cases": [{"id": "placeholder", "input": {"query": "smoke"}}]},
                   timeout=15)
    if r.status_code == 402:
        check("create dataset", False, "pro required — skip promote")
    else:
        check("create dataset", r.status_code == 201, f"HTTP {r.status_code}")
        dataset_id = r.json().get("id", "") if r.status_code == 201 else ""
        if dataset_id and trace_id:
            r = httpx.post(
                f"{BASE_URL}/v1/eval/datasets/{dataset_id}/cases/from-trace",
                headers={"X-API-Key": API_KEY, "Content-Type": "application/json"},
                json={"trace_id": trace_id, "case_id": "smoke-promoted"},
                timeout=15,
            )
            check("promote trace", r.status_code == 201, f"HTTP {r.status_code} {r.text[:80]}")
            if r.status_code == 201:
                body = r.json()
                check("promoted case id", body.get("case_id") == "smoke-promoted",
                      json.dumps(body)[:80])

    # 6. Keys list (JWT)
    if bearer:
        r = httpx.get(f"{BASE_URL}/v1/keys/{PROJECT}",
                      headers={**bearer, "Content-Type": "application/json"},
                      timeout=15)
        check("list keys", r.status_code == 200, f"HTTP {r.status_code}")

    print()
    if FAILURES:
        print(f"FAILED ({len(FAILURES)}):")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print("All smoke checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
