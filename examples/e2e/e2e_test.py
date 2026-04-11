"""
CortexOps End-to-End Test Suite
================================
Tests the full CortexOps stack against the live API.

Usage:
    export CORTEXOPS_API_KEY=cxo-...
    export CORTEXOPS_PROJECT=payments-agent
    python e2e_test.py

    # Or with explicit args:
    python e2e_test.py --api-key cxo-... --project payments-agent

Requirements:
    pip install httpx cortexops
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import threading
import uuid
from datetime import datetime

import httpx

# ── Config ─────────────────────────────────────────────────────────────────
BASE_URL = os.getenv("CORTEXOPS_API_URL", "https://api.getcortexops.com")
API_KEY  = os.getenv("CORTEXOPS_API_KEY", "")
PROJECT  = os.getenv("CORTEXOPS_PROJECT", "payments-agent")

PASS = "PASS"
FAIL = "FAIL"
SKIP = "SKIP"

results: list[dict] = []
state: dict = {
    "trace_id": None,
    "free_key": None,
    "free_key_id": None,
    "rotated_key": None,
    "idempotency_key": str(uuid.uuid4()),
}


# ── Test runner ─────────────────────────────────────────────────────────────
def run_test(name: str, fn):
    start = time.perf_counter()
    try:
        fn()
        elapsed = (time.perf_counter() - start) * 1000
        results.append({"name": name, "status": PASS, "ms": round(elapsed, 1)})
        print(f"  PASS  {name}  ({elapsed:.0f}ms)")
    except AssertionError as e:
        elapsed = (time.perf_counter() - start) * 1000
        results.append({"name": name, "status": FAIL, "error": str(e), "ms": round(elapsed, 1)})
        print(f"  FAIL  {name}\n        {e}")
    except Exception as e:
        elapsed = (time.perf_counter() - start) * 1000
        results.append({"name": name, "status": FAIL, "error": str(e), "ms": round(elapsed, 1)})
        print(f"  FAIL  {name}\n        {type(e).__name__}: {e}")


def hdrs(key: str = "") -> dict:
    return {"X-API-Key": key or API_KEY, "Content-Type": "application/json"}


def chk(r: httpx.Response, expected: int, ctx: str = "") -> None:
    assert r.status_code == expected, \
        f"{ctx} expected HTTP {expected}, got {r.status_code}: {r.text[:200]}"


# ── Individual test functions ────────────────────────────────────────────────

def t01_health():
    r = httpx.get(f"{BASE_URL}/health", timeout=10)
    chk(r, 200, "GET /health")
    d = r.json()
    assert d["status"] == "ok"
    assert "version" in d
    assert "circuits" in d
    print(f"        version={d['version']} env={d['environment']}")


def t02_quota_pro():
    r = httpx.get(f"{BASE_URL}/v1/traces/quota", headers=hdrs(), timeout=10)
    chk(r, 200, "GET /quota")
    d = r.json()
    assert d["tier"] == "pro",                "tier should be pro"
    assert d["monthly_traces"]["unlimited"],   "unlimited should be true"
    assert d["retention_days"] == 90,         "retention should be 90 days"
    assert d["features"]["slack_alerts"],     "slack_alerts should be true"
    assert d["features"]["llm_judge"],        "llm_judge should be true"
    assert d["features"]["prompt_versioning"],"prompt_versioning should be true"
    assert d["upgrade_url"] is None,          "upgrade_url should be null for Pro"
    print(f"        used={d['monthly_traces']['used']} traces this month")


def t03_ingest_trace():
    payload = {
        "project": PROJECT, "case_id": "e2e-basic",
        "status": "completed", "total_latency_ms": 342.5,
        "input": {"query": "Refund order #4821"},
        "output": {"action": "refund_approved", "amount": 49.99},
        "nodes": [
            {"node_name": "classify_intent", "latency_ms": 89},
            {"node_name": "process_refund", "latency_ms": 253},
        ],
        "environment": "production",
    }
    r = httpx.post(f"{BASE_URL}/v1/traces", headers=hdrs(), json=payload, timeout=10)
    chk(r, 201, "POST /v1/traces")
    d = r.json()
    assert "trace_id" in d
    assert d["project"] == PROJECT
    assert d["status"] == "completed"
    assert d["total_latency_ms"] == 342.5
    state["trace_id"] = d["trace_id"]
    print(f"        trace_id={d['trace_id']}")


def t04_pii_redaction():
    payload = {
        "project": PROJECT, "case_id": "e2e-pii",
        "status": "completed", "total_latency_ms": 120.0,
        "input": {"query": "Refund for user ashish@paypal.com card 4111 1111 1111 1111"},
        "output": {"message": "Processed for SSN 123-45-6789"},
        "environment": "production",
    }
    r = httpx.post(f"{BASE_URL}/v1/traces", headers=hdrs(), json=payload, timeout=10)
    chk(r, 201, "POST /v1/traces PII")
    trace_id = r.json()["trace_id"]

    r2 = httpx.get(f"{BASE_URL}/v1/traces/{trace_id}", headers=hdrs(), timeout=10)
    chk(r2, 200, "GET /v1/traces/:id")
    raw = json.dumps(r2.json().get("raw_trace", {}))
    assert "ashish@paypal.com" not in raw,       "Email not redacted"
    assert "4111 1111 1111 1111" not in raw,     "Card not redacted"
    assert "123-45-6789" not in raw,             "SSN not redacted"
    assert any(t in raw for t in ["[EMAIL]", "[CARD]", "[SSN]"]), "No redaction tokens found"
    print("        email, card, SSN redacted in stored trace")


def t05_idempotency():
    payload = {
        "project": PROJECT, "case_id": "e2e-idem",
        "status": "completed", "total_latency_ms": 200.0,
        "environment": "production",
    }
    h = {**hdrs(), "Idempotency-Key": state["idempotency_key"]}
    r1 = httpx.post(f"{BASE_URL}/v1/traces", headers=h, json=payload, timeout=10)
    chk(r1, 201, "First POST")
    id1 = r1.json()["trace_id"]

    r2 = httpx.post(f"{BASE_URL}/v1/traces", headers=h, json=payload, timeout=10)
    assert r2.status_code in (200, 201)
    id2 = r2.json()["trace_id"]
    assert id1 == id2, f"Idempotency failed: {id1} != {id2}"
    print(f"        same trace_id={id1} on both requests")


def t06_failed_trace():
    payload = {
        "project": PROJECT, "case_id": "e2e-fail",
        "status": "failed", "total_latency_ms": 3240.0,
        "failure_kind": "TIMEOUT", "failure_detail": "LLM exceeded 3s",
        "environment": "production",
    }
    r = httpx.post(f"{BASE_URL}/v1/traces", headers=hdrs(), json=payload, timeout=10)
    chk(r, 201, "POST /v1/traces failed")
    d = r.json()
    assert d["status"] == "failed"
    assert d["failure_kind"] == "TIMEOUT"
    print("        failure_kind=TIMEOUT stored correctly")


def t07_list_traces():
    r = httpx.get(f"{BASE_URL}/v1/traces",
                  params={"project": PROJECT, "limit": 5},
                  headers=hdrs(), timeout=10)
    chk(r, 200, "GET /v1/traces")
    d = r.json()
    assert isinstance(d, list)
    assert len(d) > 0
    assert len(d) <= 5
    print(f"        {len(d)} traces returned")


def t08_get_trace():
    assert state["trace_id"], "Skipping — no trace_id from t03"
    r = httpx.get(f"{BASE_URL}/v1/traces/{state['trace_id']}",
                  headers=hdrs(), timeout=10)
    chk(r, 200, "GET /v1/traces/:id")
    d = r.json()
    assert d["trace_id"] == state["trace_id"]
    assert "raw_trace" in d
    print(f"        raw_trace keys: {list(d['raw_trace'].keys())}")


def t09_trace_404():
    r = httpx.get(f"{BASE_URL}/v1/traces/{uuid.uuid4()}",
                  headers=hdrs(), timeout=10)
    chk(r, 404, "GET /v1/traces/unknown")


def t10_create_free_key():
    r = httpx.post(f"{BASE_URL}/v1/keys",
                   json={"project": PROJECT, "name": "e2e-free"},
                   timeout=10)
    chk(r, 201, "POST /v1/keys")
    d = r.json()
    assert d["raw_key"].startswith("cxo-")
    assert d["tier"] == "free"
    assert d["is_active"]
    state["free_key"]    = d["raw_key"]
    state["free_key_id"] = d["id"]
    print(f"        free key created id={d['id'][:8]}...")


def t11_free_quota():
    assert state["free_key"]
    r = httpx.get(f"{BASE_URL}/v1/traces/quota",
                  headers=hdrs(state["free_key"]), timeout=10)
    chk(r, 200, "GET /quota free")
    d = r.json()
    assert d["tier"] == "free"
    assert d["monthly_traces"]["limit"] == 5000
    assert not d["monthly_traces"]["unlimited"]
    assert d["retention_days"] == 7
    assert not d["features"]["slack_alerts"]
    assert d["upgrade_url"] is not None
    print("        tier=free limit=5000 retention=7d")


def t12_free_pro_blocked():
    assert state["free_key"]
    r = httpx.post(f"{BASE_URL}/v1/prompts",
                   headers=hdrs(state["free_key"]),
                   json={"project": PROJECT, "prompt_name": "test",
                         "content": "test", "model": "gpt-4o",
                         "commit_message": "test"},
                   timeout=10)
    assert r.status_code == 402, f"Expected 402, got {r.status_code}"
    assert r.json()["detail"]["error"] == "pro_required"
    print("        402 pro_required returned correctly")


def t13_rotate_key():
    assert state["free_key_id"]
    r = httpx.post(f"{BASE_URL}/v1/keys/{state['free_key_id']}/rotate",
                   headers=hdrs(), timeout=10)
    chk(r, 200, "POST /v1/keys/:id/rotate")
    d = r.json()
    assert d["new_key"].startswith("cxo-")
    assert d["old_key_id"] == state["free_key_id"]
    assert d["new_key"] != state["free_key"]
    state["rotated_key"] = d["new_key"]
    print(f"        old key revoked, new key issued")


def t14_old_key_rejected():
    assert state["free_key"]
    r = httpx.get(f"{BASE_URL}/v1/traces/quota",
                  headers=hdrs(state["free_key"]), timeout=10)
    assert r.status_code == 401, f"Expected 401 for revoked key, got {r.status_code}"
    print("        revoked key correctly rejected 401")


def t15_invalid_key():
    r = httpx.get(f"{BASE_URL}/v1/traces/quota",
                  headers=hdrs("cxo-invalidtestkey"), timeout=10)
    assert r.status_code == 401, f"Expected 401, got {r.status_code}"


def t16_missing_key():
    r = httpx.get(f"{BASE_URL}/v1/traces/quota", timeout=10)
    assert r.status_code == 401, f"Expected 401, got {r.status_code}"


def t17_prompt_versioning_pro():
    r = httpx.post(f"{BASE_URL}/v1/prompts",
                   headers=hdrs(),
                   json={"project": PROJECT,
                         "prompt_name": "e2e-classifier",
                         "content": "Classify: refund_approved | fraud_blocked | escalate.",
                         "model": "gpt-4o", "temperature": 0.1,
                         "commit_message": "e2e test"},
                   timeout=10)
    chk(r, 201, "POST /v1/prompts pro")
    d = r.json()
    assert d["prompt_name"] == "e2e-classifier"
    assert d["version"] >= 1
    print(f"        prompt version={d['version']} created")


def t18_sdk_key_resolution():
    try:
        from cortexops.tracer import CortexTracer, _resolve_api_key
        resolved = _resolve_api_key(None)
        assert resolved == API_KEY, f"SDK resolved wrong key"
        tracer = CortexTracer(project=PROJECT)
        assert tracer.api_key == API_KEY
        assert tracer.is_hosted
        print("        key auto-loaded from env, is_hosted=True")
    except ImportError:
        results[-1]["status"] = SKIP
        print("        SKIP — pip install cortexops")


def t19_sdk_trace_callable():
    try:
        from cortexops import CortexTracer

        def my_agent(inp: dict) -> dict:
            time.sleep(0.05)
            return {"action": "refund_approved", "amount": inp.get("amount", 0)}

        tracer = CortexTracer(project=PROJECT)
        instrumented = tracer.wrap(my_agent)
        result = instrumented({"query": "refund", "amount": 49.99})

        assert result["action"] == "refund_approved"
        trace = tracer.last_trace()
        assert trace is not None
        assert trace.total_latency_ms > 0
        print(f"        traced callable latency={trace.total_latency_ms:.0f}ms")
    except ImportError:
        results[-1]["status"] = SKIP
        print("        SKIP — pip install cortexops")


def t20_concurrent_traces():
    errors = []

    def send(i: int):
        payload = {
            "project": PROJECT, "case_id": f"e2e-concurrent-{i}",
            "status": "completed", "total_latency_ms": 100.0 + i,
            "environment": "production",
        }
        r = httpx.post(f"{BASE_URL}/v1/traces", headers=hdrs(),
                       json=payload, timeout=15)
        if r.status_code not in (200, 201):
            errors.append(f"trace {i}: {r.status_code}")

    threads = [threading.Thread(target=send, args=(i,)) for i in range(5)]
    for t in threads: t.start()
    for t in threads: t.join()
    assert not errors, f"Concurrent errors: {errors}"
    print("        5 concurrent traces all succeeded")


# ── Summary ─────────────────────────────────────────────────────────────────

def print_summary() -> int:
    passed  = sum(1 for r in results if r["status"] == PASS)
    failed  = sum(1 for r in results if r["status"] == FAIL)
    skipped = sum(1 for r in results if r["status"] == SKIP)
    total   = len(results)

    print()
    print("=" * 60)
    print(f"  CortexOps E2E — {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 60)
    print(f"  PASS:  {passed}/{total}")
    print(f"  FAIL:  {failed}/{total}")
    print(f"  SKIP:  {skipped}/{total}")
    if failed:
        print("\n  Failures:")
        for r in results:
            if r["status"] == FAIL:
                print(f"    x {r['name']}")
                print(f"      {r.get('error','')}")
    print()
    print("  All tests passed." if not failed else "  Some tests failed.")
    print("=" * 60)
    return 1 if failed else 0


# ── Main ────────────────────────────────────────────────────────────────────

def main():
    global API_KEY, PROJECT, BASE_URL

    parser = argparse.ArgumentParser(description="CortexOps E2E test suite")
    parser.add_argument("--api-key",  default=API_KEY)
    parser.add_argument("--project",  default=PROJECT)
    parser.add_argument("--base-url", default=BASE_URL)
    args = parser.parse_args()

    API_KEY  = args.api_key
    PROJECT  = args.project
    BASE_URL = args.base_url

    if not API_KEY:
        print("Error: set CORTEXOPS_API_KEY or pass --api-key")
        sys.exit(1)

    print(f"\nCortexOps E2E Test Suite")
    print(f"  API:     {BASE_URL}")
    print(f"  Project: {PROJECT}")
    print(f"  Key:     {API_KEY[:12]}...\n")

    tests = [
        ("1.  Health check",                        t01_health),
        ("2.  Quota — Pro tier verified",            t02_quota_pro),
        ("3.  Ingest trace — completed",             t03_ingest_trace),
        ("4.  PII redaction",                        t04_pii_redaction),
        ("5.  Idempotency key",                      t05_idempotency),
        ("6.  Failed trace with metadata",           t06_failed_trace),
        ("7.  List traces",                          t07_list_traces),
        ("8.  Get trace by ID",                      t08_get_trace),
        ("9.  Trace 404 for unknown ID",             t09_trace_404),
        ("10. Create free-tier key",                 t10_create_free_key),
        ("11. Free key quota shape",                 t11_free_quota),
        ("12. Free key — Pro feature 402",           t12_free_pro_blocked),
        ("13. Key rotation",                         t13_rotate_key),
        ("14. Old key rejected after rotation",      t14_old_key_rejected),
        ("15. Invalid key — 401",                    t15_invalid_key),
        ("16. Missing key — 401",                    t16_missing_key),
        ("17. Prompt versioning (Pro)",              t17_prompt_versioning_pro),
        ("18. SDK key auto-resolution",              t18_sdk_key_resolution),
        ("19. SDK wrap and trace callable",          t19_sdk_trace_callable),
        ("20. Concurrent traces",                    t20_concurrent_traces),
    ]

    for name, fn in tests:
        run_test(name, fn)

    sys.exit(print_summary())


if __name__ == "__main__":
    main()