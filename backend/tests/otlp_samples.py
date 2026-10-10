"""OTLP export payloads shaped like real instrumentations emit them (attribute names verified against
openinference-instrumentation-openai 0.1.x, opentelemetry-instrumentation-openai 0.62.x and traceloop-sdk)."""
from __future__ import annotations

import json
import secrets
from typing import Any

from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
from opentelemetry.proto.common.v1.common_pb2 import AnyValue, KeyValue
from opentelemetry.proto.trace.v1.trace_pb2 import Span, Status

T0 = 1_760_000_000_000_000_000  # ns
MS = 1_000_000


def new_trace_id() -> str:
    return secrets.token_hex(16)


def new_span_id() -> str:
    return secrets.token_hex(8)


def any_value(value: Any) -> dict[str, Any]:
    if isinstance(value, bool):
        return {"boolValue": value}
    if isinstance(value, int):
        return {"intValue": str(value)}
    if isinstance(value, float):
        return {"doubleValue": value}
    if isinstance(value, (list, tuple)):
        return {"arrayValue": {"values": [any_value(v) for v in value]}}
    return {"stringValue": str(value)}


def kv(attrs: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"key": k, "value": any_value(v)} for k, v in attrs.items()]


def span(
    trace_id: str, span_id: str, parent: str, name: str, attrs: dict[str, Any], start_ms: float, end_ms: float,
    *, error: str | None = None, events: list[dict[str, Any]] | None = None, kind: int = 1,
) -> dict[str, Any]:
    raw: dict[str, Any] = {
        "traceId": trace_id,
        "spanId": span_id,
        "name": name,
        "kind": kind,
        "startTimeUnixNano": str(T0 + int(start_ms * MS)),
        "endTimeUnixNano": str(T0 + int(end_ms * MS)),
        "attributes": kv(attrs),
        "status": {"code": 2, "message": error} if error else {},
    }
    if parent:
        raw["parentSpanId"] = parent
    if events:
        raw["events"] = [
            {"name": e["name"], "timeUnixNano": str(T0 + int(e.get("at_ms", start_ms) * MS)),
             "attributes": kv(e.get("attributes", {}))}
            for e in events
        ]
    return raw


def export_json(resource: dict[str, Any], spans: list[dict[str, Any]], scope: str = "test") -> dict[str, Any]:
    return {"resourceSpans": [{
        "resource": {"attributes": kv(resource)},
        "scopeSpans": [{"scope": {"name": scope}, "spans": spans}],
    }]}


def to_protobuf(payload: dict[str, Any]) -> bytes:
    """Encode an OTLP JSON payload (hex ids) as a protobuf ExportTraceServiceRequest."""
    def _kvs(items):
        return [KeyValue(key=i["key"], value=_av(i["value"])) for i in items]

    def _av(v):
        if "stringValue" in v:
            return AnyValue(string_value=v["stringValue"])
        if "boolValue" in v:
            return AnyValue(bool_value=v["boolValue"])
        if "intValue" in v:
            return AnyValue(int_value=int(v["intValue"]))
        if "doubleValue" in v:
            return AnyValue(double_value=v["doubleValue"])
        out = AnyValue()
        out.array_value.values.extend(_av(x) for x in v["arrayValue"]["values"])
        return out

    msg = ExportTraceServiceRequest()
    for rs in payload["resourceSpans"]:
        out_rs = msg.resource_spans.add()
        out_rs.resource.attributes.extend(_kvs(rs["resource"]["attributes"]))
        for ss in rs["scopeSpans"]:
            out_ss = out_rs.scope_spans.add()
            out_ss.scope.name = ss["scope"]["name"]
            for s in ss["spans"]:
                out = Span(
                    trace_id=bytes.fromhex(s["traceId"]),
                    span_id=bytes.fromhex(s["spanId"]),
                    parent_span_id=bytes.fromhex(s.get("parentSpanId", "")),
                    name=s["name"],
                    kind=s["kind"],
                    start_time_unix_nano=int(s["startTimeUnixNano"]),
                    end_time_unix_nano=int(s["endTimeUnixNano"]),
                )
                out.attributes.extend(_kvs(s["attributes"]))
                if s["status"]:
                    out.status.CopyFrom(Status(code=s["status"]["code"], message=s["status"].get("message", "")))
                for e in s.get("events", []):
                    ev = out.events.add()
                    ev.name = e["name"]
                    ev.time_unix_nano = int(e["timeUnixNano"])
                    ev.attributes.extend(_kvs(e["attributes"]))
                out_ss.spans.append(out)
    return msg.SerializeToString()


# ── Convention samples ────────────────────────────────────────────────────

def genai_semconv_trace(project: str, trace_id: str | None = None) -> tuple[str, dict[str, Any]]:
    """Agent run per the OTel GenAI semantic conventions: invoke_agent -> chat, execute_tool."""
    trace_id = trace_id or new_trace_id()
    root, chat, tool = new_span_id(), new_span_id(), new_span_id()
    spans = [
        span(trace_id, root, "", "invoke_agent refund-agent", {
            "gen_ai.operation.name": "invoke_agent",
            "gen_ai.agent.name": "refund-agent",
            "gen_ai.provider.name": "openai",
            "cortexops.case_id": "refund-4821",
            "input.value": json.dumps({"question": "Refund order 4821"}),
            "output.value": json.dumps({"answer": "approved"}),
        }, 0, 1200),
        span(trace_id, chat, root, "chat gpt-4o-mini", {
            "gen_ai.operation.name": "chat",
            "gen_ai.provider.name": "openai",
            "gen_ai.request.model": "gpt-4o-mini",
            "gen_ai.response.model": "gpt-4o-mini-2024-07-18",
            "gen_ai.usage.input_tokens": 42,
            "gen_ai.usage.output_tokens": 9,
            "gen_ai.response.finish_reasons": ["stop"],
            "gen_ai.input.messages": json.dumps([
                {"role": "system", "parts": [{"type": "text", "content": "You approve refunds."}]},
                {"role": "user", "parts": [{"type": "text", "content": "Refund order 4821"}]},
            ]),
            "gen_ai.output.messages": json.dumps([
                {"role": "assistant", "parts": [{"type": "text", "content": "Approved."}], "finish_reason": "stop"},
            ]),
        }, 10, 610, kind=3),
        span(trace_id, tool, root, "execute_tool lookup_order", {
            "gen_ai.operation.name": "execute_tool",
            "gen_ai.tool.name": "lookup_order",
            "gen_ai.tool.call.id": "call_abc123",
            "gen_ai.tool.call.arguments": json.dumps({"order_id": "4821"}),
            "gen_ai.tool.call.result": json.dumps({"status": "delivered"}),
        }, 620, 700),
    ]
    resource = {
        "service.name": "refund-service",
        "cortexops.project": project,
        "deployment.environment.name": "staging",
        "cortexops.prompt.name": "refund-system",
        "cortexops.prompt.version": "v3",
    }
    return trace_id, export_json(resource, spans, scope="opentelemetry.instrumentation.openai_v2")


def openinference_trace(project: str) -> tuple[str, dict[str, Any]]:
    """Arize OpenInference: AGENT -> CHAIN -> (LLM, TOOL)."""
    trace_id = new_trace_id()
    agent, chain, llm, tool = new_span_id(), new_span_id(), new_span_id(), new_span_id()
    spans = [
        span(trace_id, agent, "", "RefundAgent.run", {
            "openinference.span.kind": "AGENT",
            "input.value": "Refund order 4821",
            "input.mime_type": "text/plain",
            "output.value": "Refund approved",
        }, 0, 900),
        span(trace_id, chain, agent, "plan", {"openinference.span.kind": "CHAIN"}, 5, 880),
        span(trace_id, llm, chain, "ChatCompletion", {
            "openinference.span.kind": "LLM",
            "llm.system": "openai",
            "llm.model_name": "gpt-4o-mini-2024-07-18",
            "llm.invocation_parameters": json.dumps({"model": "gpt-4o-mini"}),
            "llm.input_messages.0.message.role": "system",
            "llm.input_messages.0.message.content": "You approve refunds.",
            "llm.input_messages.1.message.role": "user",
            "llm.input_messages.1.message.content": "Refund order 4821",
            "llm.output_messages.0.message.role": "assistant",
            "llm.output_messages.0.message.content": "Call lookup_order",
            "llm.token_count.prompt": 42,
            "llm.token_count.completion": 9,
            "llm.token_count.total": 51,
        }, 10, 400),
        span(trace_id, tool, chain, "lookup_order", {
            "openinference.span.kind": "TOOL",
            "tool.name": "lookup_order",
            "input.value": json.dumps({"order_id": "4821"}),
            "output.value": json.dumps({"status": "delivered"}),
        }, 410, 450),
    ]
    resource = {"service.name": project, "openinference.project.name": "default"}
    return trace_id, export_json(resource, spans, scope="openinference.instrumentation.openai")


def logfire_trace(project: str) -> tuple[str, dict[str, Any]]:
    """Pydantic Logfire 5.x: logfire.span(...) wrapping logfire.instrument_openai() (GenAI semconv)."""
    trace_id = new_trace_id()
    root, chat = new_span_id(), new_span_id()
    spans = [
        span(trace_id, root, "", "refund agent {order}", {
            "code.filepath": "agent.py",
            "order": "4821",
            "logfire.msg_template": "refund agent {order}",
            "logfire.msg": "refund agent 4821",
            "logfire.json_schema": json.dumps({"type": "object", "properties": {"order": {}}}),
            "logfire.span_type": "span",
        }, 0, 700),
        span(trace_id, chat, root, "Chat Completion with {request_data[model]!r}", {
            "request_data": json.dumps({"model": "gpt-4o-mini"}),
            "gen_ai.system": "openai",
            "gen_ai.provider.name": "openai",
            "gen_ai.request.model": "gpt-4o-mini",
            "gen_ai.operation.name": "chat",
            "gen_ai.input.messages": json.dumps([
                {"role": "system", "parts": [{"type": "text", "content": "You approve refunds."}]},
                {"role": "user", "parts": [{"type": "text", "content": "Refund order 4821"}]},
            ]),
            "logfire.msg_template": "Chat Completion with {request_data[model]!r}",
            "logfire.msg": "Chat Completion with 'gpt-4o-mini'",
            "logfire.tags": ["LLM"],
            "logfire.span_type": "span",
            "gen_ai.response.model": "gpt-4o-mini-2024-07-18",
            "gen_ai.usage.input_tokens": 42,
            "gen_ai.usage.output_tokens": 9,
            "gen_ai.output.messages": json.dumps([
                {"role": "assistant", "parts": [{"type": "text", "content": "Refund for order 4821 is approved."}],
                 "finish_reason": "stop"},
            ]),
            "logfire.json_schema": json.dumps({"type": "object", "properties": {"request_data": {"type": "object"}}}),
        }, 10, 650, kind=3),
    ]
    resource = {"service.name": project, "telemetry.sdk.language": "python", "logfire.version": "5.1.1"}
    return trace_id, export_json(resource, spans, scope="logfire.openai")


def traceloop_trace(project: str) -> tuple[str, dict[str, Any]]:
    """Traceloop / OpenLLMetry decorators: workflow -> task -> (openai.chat, tool)."""
    trace_id = new_trace_id()
    workflow, task, llm, tool = new_span_id(), new_span_id(), new_span_id(), new_span_id()
    spans = [
        span(trace_id, workflow, "", "refund_workflow.workflow", {
            "traceloop.span.kind": "workflow",
            "traceloop.entity.name": "refund_workflow",
            "traceloop.workflow.name": "refund_workflow",
            "traceloop.entity.input": json.dumps({"args": ["4821"], "kwargs": {}}),
            "traceloop.entity.output": json.dumps("approved"),
        }, 0, 1500),
        span(trace_id, task, workflow, "decide.task", {
            "traceloop.span.kind": "task",
            "traceloop.entity.name": "decide",
        }, 20, 1400),
        span(trace_id, llm, task, "openai.chat", {
            "llm.request.type": "chat",
            "gen_ai.system": "openai",
            "gen_ai.request.model": "gpt-4o",
            "gen_ai.response.model": "gpt-4o-2024-08-06",
            "gen_ai.prompt.0.role": "user",
            "gen_ai.prompt.0.content": "Should order 4821 be refunded?",
            "gen_ai.completion.0.role": "assistant",
            "gen_ai.completion.0.content": "Yes",
            "gen_ai.usage.prompt_tokens": 12,
            "gen_ai.usage.completion_tokens": 1,
        }, 30, 900, kind=3),
        span(trace_id, tool, task, "lookup_order.tool", {
            "traceloop.span.kind": "tool",
            "traceloop.entity.name": "lookup_order",
            "traceloop.entity.input": json.dumps({"args": [], "kwargs": {"order_id": "4821"}}),
            "traceloop.entity.output": json.dumps({"status": "delivered"}),
        }, 910, 980),
    ]
    resource = {"service.name": project}
    return trace_id, export_json(resource, spans, scope="traceloop.tracer")
