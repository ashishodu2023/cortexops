"""OTLP/HTTP trace ingest: convention mapping, encodings, auth, limits and redaction."""
from __future__ import annotations

import gzip
import json
import os
import sqlite3
import uuid

import pytest
from app.auth import generate_api_key, get_current_key_info
from app.main import app
from app.routers.otlp import get_otlp_key_info
from app.tiers import FREE_MONTHLY_TRACE_LIMIT, TierInfo
from fastapi.testclient import TestClient
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceResponse
from otlp_samples import (
    export_json,
    genai_semconv_trace,
    logfire_trace,
    new_span_id,
    new_trace_id,
    openinference_trace,
    span,
    to_protobuf,
    traceloop_trace,
)

URL = "/v1/otlp/v1/traces"


def _record_id(trace_id: str) -> str:
    return str(uuid.UUID(hex=trace_id))


@pytest.fixture
def project() -> str:
    return f"otel-{uuid.uuid4().hex[:8]}"


@pytest.fixture
def make_client(project):
    """Client authenticated as a key for `project`; override tier / usage / scope per test."""
    clients = []

    def _make(**tier_kwargs) -> TestClient:
        info = TierInfo(**{"project": project, "tier": "pro", "key_id": "k", **tier_kwargs})
        app.dependency_overrides[get_otlp_key_info] = lambda: info
        app.dependency_overrides[get_current_key_info] = lambda: info
        c = TestClient(app)
        c.__enter__()
        clients.append(c)
        return c

    yield _make
    for c in clients:
        c.__exit__(None, None, None)
    app.dependency_overrides.clear()


@pytest.fixture
def client(make_client):
    return make_client()


def _post(c: TestClient, payload: dict, **headers):
    return c.post(URL, content=json.dumps(payload), headers={"Content-Type": "application/json", **headers})


def _detail(c: TestClient, trace_id: str) -> dict:
    r = c.get(f"/v1/traces/{_record_id(trace_id)}")
    assert r.status_code == 200, r.text
    return r.json()


def _nodes_by_name(raw: dict) -> dict[str, dict]:
    return {n["node_name"]: n for n in raw["nodes"]}


# ── Convention mapping ────────────────────────────────────────────────────

def test_genai_semconv_trace_maps_to_cortexops_trace(client, project):
    trace_id, payload = genai_semconv_trace(project)
    r = _post(client, payload)
    assert r.status_code == 200, r.text
    assert r.json() == {}
    assert r.headers["content-type"].startswith("application/json")

    detail = _detail(client, trace_id)
    assert detail["project"] == project
    assert detail["status"] == "completed"
    assert detail["environment"] == "staging"
    assert detail["case_id"] == "refund-4821"
    assert detail["prompt_name"] == "refund-system"
    assert detail["prompt_version"] == "v3"
    assert detail["total_latency_ms"] == pytest.approx(1200.0)

    raw = detail["raw_trace"]
    assert raw["input"] == {"question": "Refund order 4821"}
    assert raw["output"] == {"answer": "approved"}
    nodes = _nodes_by_name(raw)
    chat = nodes["chat gpt-4o-mini"]
    assert chat["span_kind"] == "llm"
    assert chat["model"] == "gpt-4o-mini-2024-07-18"
    assert chat["provider"] == "openai"
    assert chat["usage"] == {"input_tokens": 42, "output_tokens": 9}
    assert chat["latency_ms"] == pytest.approx(600.0)
    assert chat["llm_prompt"] == "system: You approve refunds.\nuser: Refund order 4821"
    assert chat["llm_response"] == "assistant: Approved."

    # The tool ran directly under the agent (root) span, so it hangs off a node representing the root.
    holder = nodes["invoke_agent refund-agent"]
    assert holder["synthetic"] is True
    (tool,) = holder["tool_calls"]
    assert tool["name"] == "lookup_order"
    assert tool["call_id"] == "call_abc123"
    assert tool["args"] == {"order_id": "4821"}
    assert tool["result"] == {"status": "delivered"}
    assert tool["status"] == "success"
    assert tool["latency_ms"] == pytest.approx(80.0)

    meta = raw["metadata"]
    assert meta["source"] == "otlp"
    assert meta["usage"] == {"input_tokens": 42, "output_tokens": 9}
    assert meta["otel"]["trace_id"] == trace_id
    assert meta["otel"]["service_name"] == "refund-service"
    assert meta["otel"]["span_count"] == 3

    listed = client.get("/v1/traces", params={"project": project}).json()
    assert [t["trace_id"] for t in listed] == [_record_id(trace_id)]


def test_openinference_trace_attaches_tool_to_chain(client, project):
    trace_id, payload = openinference_trace(project)
    assert _post(client, payload).status_code == 200

    raw = _detail(client, trace_id)["raw_trace"]
    assert raw["input"] == {"value": "Refund order 4821"}
    assert raw["output"] == {"value": "Refund approved"}
    nodes = _nodes_by_name(raw)
    assert set(nodes) == {"plan", "ChatCompletion"}
    llm = nodes["ChatCompletion"]
    assert llm["model"] == "gpt-4o-mini-2024-07-18"
    assert llm["provider"] == "openai"
    assert llm["usage"] == {"input_tokens": 42, "output_tokens": 9}
    assert llm["input"]["messages"][1] == {"role": "user", "content": "Refund order 4821"}
    assert llm["llm_response"] == "assistant: Call lookup_order"
    (tool,) = nodes["plan"]["tool_calls"]
    assert tool["name"] == "lookup_order"
    assert tool["args"] == {"order_id": "4821"}
    assert tool["result"] == {"status": "delivered"}


def test_traceloop_trace_maps_entities_and_legacy_prompt_attributes(client, project):
    trace_id, payload = traceloop_trace(project)
    assert _post(client, payload).status_code == 200

    detail = _detail(client, trace_id)
    raw = detail["raw_trace"]
    assert raw["input"] == {"args": ["4821"], "kwargs": {}}
    assert raw["output"] == {"value": "approved"}
    nodes = _nodes_by_name(raw)
    assert nodes["decide.task"]["span_kind"] == "chain"
    assert nodes["decide.task"]["entity_name"] == "decide"
    llm = nodes["openai.chat"]
    assert llm["span_kind"] == "llm"
    assert llm["model"] == "gpt-4o-2024-08-06"
    assert llm["usage"] == {"input_tokens": 12, "output_tokens": 1}
    assert llm["llm_prompt"] == "user: Should order 4821 be refunded?"
    assert llm["llm_response"] == "assistant: Yes"
    (tool,) = nodes["decide.task"]["tool_calls"]
    assert tool["name"] == "lookup_order"
    assert tool["args"] == {"args": [], "kwargs": {"order_id": "4821"}}


def test_logfire_trace_uses_rendered_span_names(client, project):
    trace_id, payload = logfire_trace(project)
    assert _post(client, payload).status_code == 200

    raw = _detail(client, trace_id)["raw_trace"]
    assert raw["metadata"]["otel"]["root"]["name"] == "refund agent 4821"
    (chat,) = raw["nodes"]
    assert chat["node_name"] == "Chat Completion with 'gpt-4o-mini'"
    assert chat["span_kind"] == "llm"
    assert chat["usage"] == {"input_tokens": 42, "output_tokens": 9}
    assert chat["llm_response"] == "assistant: Refund for order 4821 is approved."
    assert "logfire.json_schema" not in chat["attributes"]
    assert chat["attributes"]["logfire.tags"] == ["LLM"]


def test_ingested_trace_can_be_promoted_to_golden_dataset(client, project):
    trace_id, payload = genai_semconv_trace(project)
    assert _post(client, payload).status_code == 200
    ds = client.post("/v1/eval/datasets", json={"name": f"golden-{project}", "cases": [
        {"id": "seed", "input": {"question": "hi"}, "expected_tool_calls": []},
    ]})
    assert ds.status_code in (200, 201), ds.text

    r = client.post(f"/v1/eval/datasets/{ds.json()['id']}/cases/from-trace", json={"trace_id": _record_id(trace_id)})
    assert r.status_code in (200, 201), r.text
    case = r.json()["case"]
    assert case["input"] == {"question": "Refund order 4821"}
    assert case["expected_tool_calls"] == ["lookup_order"]
    assert case["max_latency_ms"] == 1500


def test_indexed_tool_call_messages_are_rendered(client, project):
    trace_id, root, llm = new_trace_id(), new_span_id(), new_span_id()
    payload = export_json({"cortexops.project": project}, [
        span(trace_id, root, "", "agent", {"openinference.span.kind": "AGENT"}, 0, 100),
        span(trace_id, llm, root, "ChatCompletion", {
            "openinference.span.kind": "LLM",
            "llm.input_messages.0.message.role": "user",
            "llm.input_messages.0.message.content": "Refund order 4821",
            "llm.output_messages.0.message.role": "assistant",
            "llm.output_messages.0.message.tool_calls.0.tool_call.id": "call_1",
            "llm.output_messages.0.message.tool_calls.0.tool_call.function.name": "lookup_order",
            "llm.output_messages.0.message.tool_calls.0.tool_call.function.arguments": '{"order_id": "4821"}',
        }, 1, 90),
    ])
    assert _post(client, payload).status_code == 200
    node = _nodes_by_name(_detail(client, trace_id)["raw_trace"])["ChatCompletion"]
    assert node["llm_response"] == 'assistant: tool_call lookup_order({"order_id": "4821"})'


def test_prompt_and_completion_events(client, project):
    trace_id, root, llm = new_trace_id(), new_span_id(), new_span_id()
    payload = export_json({"cortexops.project": project}, [
        span(trace_id, root, "", "agent", {}, 0, 100),
        span(trace_id, llm, root, "chat", {"gen_ai.operation.name": "chat", "gen_ai.system": "anthropic"}, 1, 90,
             events=[
                 {"name": "gen_ai.content.prompt", "attributes": {"gen_ai.prompt": "What is 2+2?"}},
                 {"name": "gen_ai.content.completion", "attributes": {"gen_ai.completion": "4"}},
             ]),
    ])
    assert _post(client, payload).status_code == 200
    node = _nodes_by_name(_detail(client, trace_id)["raw_trace"])["chat"]
    assert node["llm_prompt"] == "What is 2+2?"
    assert node["llm_response"] == "4"
    assert node["provider"] == "anthropic"


def test_error_status_and_exception_events_fail_the_trace(client, project):
    trace_id, root, tool = new_trace_id(), new_span_id(), new_span_id()
    payload = export_json({"cortexops.project": project}, [
        span(trace_id, root, "", "agent", {}, 0, 300),
        span(trace_id, tool, root, "execute_tool refund", {
            "gen_ai.operation.name": "execute_tool", "gen_ai.tool.name": "issue_refund",
        }, 10, 200, error="refund API down", events=[{
            "name": "exception",
            "attributes": {"exception.type": "PaymentTimeout", "exception.message": "gateway timeout after 5s"},
        }]),
    ])
    assert _post(client, payload).status_code == 200

    detail = _detail(client, trace_id)
    assert detail["status"] == "failed"
    assert detail["failure_kind"] == "timeout"
    assert detail["failure_detail"] == "tool issue_refund: PaymentTimeout: gateway timeout after 5s"
    (tool_call,) = detail["raw_trace"]["nodes"][0]["tool_calls"]
    assert tool_call["status"] == "error"
    assert tool_call["error"] == "PaymentTimeout: gateway timeout after 5s"

    failed = client.get("/v1/traces", params={"project": project, "status": "failed"}).json()
    assert [t["trace_id"] for t in failed] == [_record_id(trace_id)]


def test_root_error_status_message_is_failure_detail(client, project):
    trace_id = new_trace_id()
    payload = export_json({"cortexops.project": project}, [
        span(trace_id, new_span_id(), "", "agent", {}, 0, 10, error="context window exceeded"),
    ])
    assert _post(client, payload).status_code == 200
    detail = _detail(client, trace_id)
    assert detail["status"] == "failed"
    assert detail["failure_kind"] == "unknown"
    assert detail["failure_detail"] == "context window exceeded"


# ── Encodings ─────────────────────────────────────────────────────────────

def test_protobuf_body_with_gzip(client, project):
    trace_id, payload = genai_semconv_trace(project)
    r = client.post(URL, content=gzip.compress(to_protobuf(payload)), headers={
        "Content-Type": "application/x-protobuf", "Content-Encoding": "gzip",
    })
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/x-protobuf"
    response = ExportTraceServiceResponse.FromString(r.content)
    assert not response.HasField("partial_success")

    raw = _detail(client, trace_id)["raw_trace"]
    nodes = _nodes_by_name(raw)
    assert nodes["chat gpt-4o-mini"]["usage"] == {"input_tokens": 42, "output_tokens": 9}
    assert nodes["invoke_agent refund-agent"]["tool_calls"][0]["name"] == "lookup_order"
    assert raw["metadata"]["otel"]["trace_id"] == trace_id


def test_malformed_bodies_and_unsupported_types(client, project):
    r = client.post(URL, content=b"not json", headers={"Content-Type": "application/json"})
    assert r.status_code == 400
    assert r.json()["code"] == 3

    r = client.post(URL, content=b"\xff\xff\xff", headers={"Content-Type": "application/x-protobuf"})
    assert r.status_code == 400
    assert r.headers["content-type"] == "application/x-protobuf"

    r = client.post(URL, content=b"{}", headers={"Content-Type": "text/plain"})
    assert r.status_code == 415

    r = client.post(URL, content=b"{}", headers={"Content-Type": "application/json", "Content-Encoding": "br"})
    assert r.status_code == 415

    r = client.post(URL, content=b"{}", headers={"Content-Type": "application/json"})
    assert r.status_code == 200
    assert r.json() == {}


def test_invalid_span_ids_are_reported_as_partial_success(client, project):
    trace_id, payload = genai_semconv_trace(project)
    payload["resourceSpans"][0]["scopeSpans"][0]["spans"].append(
        span("xyz", new_span_id(), "", "bad", {}, 0, 1),
    )
    r = _post(client, payload)
    assert r.status_code == 200
    partial = r.json()["partialSuccess"]
    assert partial["rejectedSpans"] == "1"
    assert "malformed" in partial["errorMessage"]
    assert _detail(client, trace_id)["status"] == "completed"


# ── Batching across requests ──────────────────────────────────────────────

def test_spans_from_later_batches_merge_into_one_trace(client, project):
    trace_id, payload = openinference_trace(project)
    spans = payload["resourceSpans"][0]["scopeSpans"][0]["spans"]
    root, children = spans[0], spans[1:]
    resource = {"service.name": project}

    # BatchSpanProcessor exports finished children before the (longer) root span ends.
    assert _post(client, export_json(resource, children[2:])).status_code == 200
    first = _detail(client, trace_id)["raw_trace"]
    (placeholder,) = first["nodes"]
    assert placeholder["synthetic"] is True and placeholder["tool_calls"][0]["name"] == "lookup_order"

    assert _post(client, export_json(resource, children[:2])).status_code == 200
    assert _post(client, export_json(resource, [root])).status_code == 200
    # exporter retry of an already-ingested batch must not duplicate spans
    assert _post(client, export_json(resource, children)).status_code == 200

    listed = client.get("/v1/traces", params={"project": project}).json()
    assert [t["trace_id"] for t in listed] == [_record_id(trace_id)]
    raw = _detail(client, trace_id)["raw_trace"]
    nodes = _nodes_by_name(raw)
    assert set(nodes) == {"plan", "ChatCompletion"}
    assert [t["name"] for t in nodes["plan"]["tool_calls"]] == ["lookup_order"]
    assert raw["input"] == {"value": "Refund order 4821"}
    assert raw["metadata"]["otel"]["span_count"] == 4
    assert raw["total_latency_ms"] == pytest.approx(900.0)


def test_multiple_traces_in_one_request(client, project):
    t1, p1 = genai_semconv_trace(project)
    t2, p2 = genai_semconv_trace(project)
    payload = {"resourceSpans": p1["resourceSpans"] + p2["resourceSpans"]}
    assert _post(client, payload).status_code == 200
    listed = {t["trace_id"] for t in client.get("/v1/traces", params={"project": project}).json()}
    assert listed == {_record_id(t1), _record_id(t2)}


# ── Project resolution ────────────────────────────────────────────────────

def test_service_name_mismatch_falls_back_to_key_project(client, project):
    trace_id, payload = openinference_trace("some-other-service")
    assert _post(client, payload).status_code == 200
    detail = _detail(client, trace_id)
    assert detail["project"] == project
    assert detail["raw_trace"]["metadata"]["otel"]["service_name"] == "some-other-service"


def test_explicit_project_mismatch_is_forbidden(client, project):
    _, payload = genai_semconv_trace("someone-elses-project")
    r = _post(client, payload)
    assert r.status_code == 403
    assert r.json()["code"] == 7


def test_mixed_projects_return_partial_success(client, project):
    ok_id, ok = genai_semconv_trace(project)
    _, forbidden = genai_semconv_trace("someone-elses-project")
    r = _post(client, {"resourceSpans": ok["resourceSpans"] + forbidden["resourceSpans"]})
    assert r.status_code == 200
    partial = r.json()["partialSuccess"]
    assert partial["rejectedSpans"] == "3"
    assert "your own project" in partial["errorMessage"]
    assert _detail(client, ok_id)["project"] == project


def test_trace_id_reused_by_another_project_is_not_merged(make_client, project):
    trace_id, payload = genai_semconv_trace(project)
    assert _post(make_client(), payload).status_code == 200

    other = f"{project}-b"
    _, payload_b = genai_semconv_trace(other, trace_id=trace_id)
    c = make_client(project=other)
    assert _post(c, payload_b).status_code == 200
    listed_b = c.get("/v1/traces", params={"project": other}).json()
    assert len(listed_b) == 1 and listed_b[0]["trace_id"] != _record_id(trace_id)


# ── Scope, quota, size ────────────────────────────────────────────────────

def test_read_only_key_cannot_ingest(make_client, project):
    _, payload = genai_semconv_trace(project)
    r = _post(make_client(scope="read_only"), payload)
    assert r.status_code == 403
    assert "read_write" in r.json()["message"]


def test_free_tier_quota_is_enforced_per_trace(make_client, project):
    c = make_client(tier="free", monthly_traces=FREE_MONTHLY_TRACE_LIMIT)
    _, payload = genai_semconv_trace(project)
    r = _post(c, payload)
    assert r.status_code == 429
    assert r.json()["code"] == 8

    c = make_client(tier="free", monthly_traces=FREE_MONTHLY_TRACE_LIMIT - 1)
    t1, p1 = genai_semconv_trace(project)
    _, p2 = genai_semconv_trace(project)
    r = _post(c, {"resourceSpans": p1["resourceSpans"] + p2["resourceSpans"]})
    assert r.status_code == 200
    assert r.json()["partialSuccess"]["rejectedSpans"] == "3"
    assert [t["trace_id"] for t in c.get("/v1/traces", params={"project": project}).json()] == [_record_id(t1)]


def test_merging_into_existing_trace_does_not_consume_quota(make_client, project):
    trace_id, payload = openinference_trace(project)
    spans = payload["resourceSpans"][0]["scopeSpans"][0]["spans"]
    resource = {"service.name": project}
    c = make_client(tier="free", monthly_traces=FREE_MONTHLY_TRACE_LIMIT - 1)
    assert _post(c, export_json(resource, spans[1:])).status_code == 200
    c = make_client(tier="free", monthly_traces=FREE_MONTHLY_TRACE_LIMIT)
    assert _post(c, export_json(resource, spans[:1])).status_code == 200
    assert _detail(c, trace_id)["raw_trace"]["input"] == {"value": "Refund order 4821"}


def test_per_trace_size_limit(client, project):
    big_id, root = new_trace_id(), new_span_id()
    big = export_json({"cortexops.project": project}, [
        span(big_id, root, "", "agent", {"input.value": "x" * 140_000}, 0, 10),
    ])
    r = _post(client, big)
    assert r.status_code == 413
    assert "128KB" in r.json()["message"]

    ok_id, ok = genai_semconv_trace(project)
    r = _post(client, {"resourceSpans": big["resourceSpans"] + ok["resourceSpans"]})
    assert r.status_code == 200
    assert r.json()["partialSuccess"]["rejectedSpans"] == "1"
    _detail(client, ok_id)
    assert client.get(f"/v1/traces/{_record_id(big_id)}").status_code == 404


def test_request_body_limit(client, monkeypatch):
    from app.routers import otlp

    monkeypatch.setattr(otlp, "MAX_OTLP_BODY_BYTES", 1000)
    r = client.post(URL, content=gzip.compress(b"{" + b" " * 5000 + b"}"),
                    headers={"Content-Type": "application/json", "Content-Encoding": "gzip"})
    assert r.status_code == 413


# ── Redaction ─────────────────────────────────────────────────────────────

def test_pii_is_redacted_but_span_ids_survive(client, project):
    trace_id, root = new_trace_id(), new_span_id()
    llm, tool = "1234567890123456", "4111111111111111"  # all-digit ids look like card numbers
    payload = export_json({"cortexops.project": project}, [
        span(trace_id, root, "", "agent", {"input.value": "email jane@acme.io"}, 0, 100),
        span(trace_id, llm, root, "chat", {
            "gen_ai.operation.name": "chat",
            "gen_ai.input.messages": json.dumps([{"role": "user", "content": "I am bob@acme.io, card 4242 4242 4242 4242"}]),
        }, 1, 50),
        span(trace_id, tool, llm, "execute_tool email", {
            "gen_ai.operation.name": "execute_tool", "gen_ai.tool.name": "send_email",
            "gen_ai.tool.call.arguments": json.dumps({"to": "carol@acme.io"}),
        }, 51, 60, error="smtp rejected dave@acme.io"),
    ])
    assert _post(client, payload).status_code == 200

    detail = _detail(client, trace_id)
    stored = json.dumps(detail["raw_trace"])
    for secret in ("jane@acme.io", "bob@acme.io", "carol@acme.io", "dave@acme.io", "4242 4242 4242 4242"):
        assert secret not in stored
    assert "dave@acme.io" not in detail["failure_detail"]
    node = detail["raw_trace"]["nodes"][0]
    assert node["node_id"] == node["span_id"] == llm
    assert node["tool_calls"][0]["span_id"] == tool
    assert node["tool_calls"][0]["parent_span_id"] == llm


# ── Auth (real keys, no dependency override) ──────────────────────────────

def _insert_key(project: str, scope: str = "read_write") -> str:
    raw, hashed = generate_api_key()
    db_path = os.environ["DATABASE_URL"].split("///", 1)[1]
    with sqlite3.connect(db_path) as conn:
        conn.execute("INSERT OR IGNORE INTO projects (id, name, description) VALUES (?, ?, '')",
                     (str(uuid.uuid4()), project))
        conn.execute(
            "INSERT INTO api_keys (id, project, key_hash, name, tier, scope, is_active) VALUES (?, ?, ?, 'k', 'free', ?, 1)",
            (str(uuid.uuid4()), project, hashed, scope),
        )
    return raw


@pytest.fixture
def real_client():
    app.dependency_overrides.clear()
    with TestClient(app) as c:
        yield c


@pytest.mark.parametrize("header", ["x-api-key", "bearer"])
def test_api_key_auth_via_either_header(real_client, project, header):
    key = _insert_key(project)
    headers = {"X-API-Key": key} if header == "x-api-key" else {"Authorization": f"Bearer {key}"}
    trace_id, payload = genai_semconv_trace(project)
    r = _post(real_client, payload, **headers)
    assert r.status_code == 200, r.text
    detail = real_client.get(f"/v1/traces/{_record_id(trace_id)}", headers={"X-API-Key": key})
    assert detail.status_code == 200
    assert detail.json()["project"] == project


def test_auth_failures(real_client, project):
    _, payload = genai_semconv_trace(project)
    assert _post(real_client, payload).status_code == 401
    assert _post(real_client, payload, **{"X-API-Key": "cxo-" + "0" * 64}).status_code == 401
    assert _post(real_client, payload, Authorization="Bearer cxo-" + "0" * 64).status_code == 401
    assert _post(real_client, payload, Authorization="Bearer not.a.jwt").status_code == 401

    read_only = _insert_key(project, scope="read_only")
    assert _post(real_client, payload, Authorization=f"Bearer {read_only}").status_code == 403
