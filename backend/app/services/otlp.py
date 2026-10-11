"""Decode OTLP trace exports and map OpenTelemetry spans onto CortexOps traces.

Understands three attribute conventions that LLM instrumentations emit:
  - OpenTelemetry GenAI semantic conventions (`gen_ai.*`)
  - Arize OpenInference (`openinference.span.kind`, `llm.*`, `input.value`, ...)
  - Traceloop / OpenLLMetry (`traceloop.span.kind`, `traceloop.entity.*`)

One OTel trace becomes one CortexOps trace: the root span describes the run, other
spans become nodes, and tool spans become tool calls on their nearest ancestor node.
Spans of one trace may arrive over several export requests, so `build_trace_payload`
merges new spans into a previously stored payload.
"""
from __future__ import annotations

import base64
import binascii
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from google.protobuf.json_format import MessageToDict
from google.protobuf.message import DecodeError
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest

STATUS_CODE_ERROR = 2

_HEX_TRACE_ID = re.compile(r"^[0-9a-f]{32}$")
_HEX_SPAN_ID = re.compile(r"^[0-9a-f]{16}$")

_LLM_OPERATIONS = {"chat", "text_completion", "completion", "generate_content", "embeddings", "embedding"}
_AGENT_OPERATIONS = {"invoke_agent", "create_agent"}
_OPENINFERENCE_KINDS = {"LLM": "llm", "EMBEDDING": "llm", "TOOL": "tool", "AGENT": "agent", "CHAIN": "chain",
                        "RETRIEVER": "retriever", "RERANKER": "retriever", "GUARDRAIL": "guardrail",
                        "EVALUATOR": "evaluator"}
_TRACELOOP_KINDS = {"tool": "tool", "agent": "agent", "workflow": "chain", "task": "chain"}

_PROMPT_EVENTS = {"gen_ai.system.message", "gen_ai.user.message", "gen_ai.assistant.message", "gen_ai.tool.message"}
_CONTENT_PREFIXES = ("gen_ai.prompt", "gen_ai.completion", "llm.input_messages", "llm.output_messages",
                     "llm.prompts", "llm.completions", "llm.prompt_template")
_CONTENT_KEYS = {"input.value", "output.value", "traceloop.entity.input", "traceloop.entity.output",
                 "gen_ai.input.messages", "gen_ai.output.messages", "gen_ai.system_instructions",
                 "gen_ai.tool.call.arguments", "gen_ai.tool.call.result", "logfire.json_schema"}
_MAX_ATTRIBUTES = 64
_MAX_ATTRIBUTE_CHARS = 1024


class OTLPDecodeError(ValueError):
    """The request body is not a valid OTLP ExportTraceServiceRequest."""


@dataclass
class OTelSpan:
    trace_id: str
    span_id: str
    parent_span_id: str
    name: str
    kind: int
    start_ns: int
    end_ns: int
    attributes: dict[str, Any]
    events: list[dict[str, Any]]
    status_code: int
    status_message: str
    resource: dict[str, Any] = field(default_factory=dict)
    scope: str = ""

    @property
    def is_error(self) -> bool:
        return self.status_code == STATUS_CODE_ERROR or any(e["name"] == "exception" for e in self.events)

    @property
    def latency_ms(self) -> float:
        return max(self.end_ns - self.start_ns, 0) / 1_000_000


# ── Decoding ──────────────────────────────────────────────────────────────

def decode_export_request(body: bytes, encoding: str) -> tuple[list[OTelSpan], int]:
    """Decode an OTLP/HTTP trace export body. Returns (valid spans, count of invalid spans)."""
    if encoding == "protobuf":
        message = ExportTraceServiceRequest()
        try:
            message.ParseFromString(body)
        except DecodeError as exc:
            raise OTLPDecodeError("Body is not a valid protobuf ExportTraceServiceRequest") from exc
        data = MessageToDict(message, use_integers_for_enums=True)
        return _flatten(data, _b64_to_hex)
    try:
        data = json.loads(body or b"{}")
    except (ValueError, UnicodeDecodeError) as exc:
        raise OTLPDecodeError("Body is not valid JSON") from exc
    if not isinstance(data, dict):
        raise OTLPDecodeError("OTLP JSON body must be an object")
    return _flatten(data, _normalize_hex)


def _b64_to_hex(value: Any) -> str:
    if not value:
        return ""
    try:
        return base64.b64decode(value, validate=True).hex()
    except (binascii.Error, ValueError, TypeError):
        return "!invalid"


def _normalize_hex(value: Any) -> str:
    return value.lower() if isinstance(value, str) else ""


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _any_value(value: Any) -> Any:
    if not isinstance(value, dict):
        return value
    if "stringValue" in value:
        return value["stringValue"]
    if "boolValue" in value:
        return bool(value["boolValue"])
    if "intValue" in value:
        return _int(value["intValue"])
    if "doubleValue" in value:
        try:
            return float(value["doubleValue"])
        except (TypeError, ValueError):
            return None
    if "arrayValue" in value:
        return [_any_value(v) for v in (value["arrayValue"] or {}).get("values", [])]
    if "kvlistValue" in value:
        return _attributes((value["kvlistValue"] or {}).get("values", []))
    if "bytesValue" in value:
        return value["bytesValue"]
    return None


def _attributes(items: Any) -> dict[str, Any]:
    if not isinstance(items, list):
        return {}
    return {
        item["key"]: _any_value(item.get("value"))
        for item in items
        if isinstance(item, dict) and isinstance(item.get("key"), str)
    }


def _flatten(data: dict[str, Any], decode_id) -> tuple[list[OTelSpan], int]:
    spans: list[OTelSpan] = []
    invalid = 0
    for resource_spans in data.get("resourceSpans") or []:
        if not isinstance(resource_spans, dict):
            continue
        resource = _attributes((resource_spans.get("resource") or {}).get("attributes"))
        for scope_spans in resource_spans.get("scopeSpans") or []:
            if not isinstance(scope_spans, dict):
                continue
            scope = str((scope_spans.get("scope") or {}).get("name") or "")
            for raw in scope_spans.get("spans") or []:
                span = _parse_span(raw, resource, scope, decode_id)
                if span is None:
                    invalid += 1
                else:
                    spans.append(span)
    return spans, invalid


def _parse_span(raw: Any, resource: dict[str, Any], scope: str, decode_id) -> OTelSpan | None:
    if not isinstance(raw, dict):
        return None
    trace_id = decode_id(raw.get("traceId"))
    span_id = decode_id(raw.get("spanId"))
    parent_span_id = decode_id(raw.get("parentSpanId"))
    if not _HEX_TRACE_ID.match(trace_id) or trace_id == "0" * 32:
        return None
    if not _HEX_SPAN_ID.match(span_id) or span_id == "0" * 16:
        return None
    if parent_span_id and not _HEX_SPAN_ID.match(parent_span_id):
        return None
    if parent_span_id == "0" * 16:
        parent_span_id = ""
    status = raw.get("status") or {}
    events = [
        {
            "name": str(e.get("name") or ""),
            "time_unix_nano": _int(e.get("timeUnixNano")),
            "attributes": _attributes(e.get("attributes")),
        }
        for e in raw.get("events") or []
        if isinstance(e, dict)
    ]
    start_ns = _int(raw.get("startTimeUnixNano"))
    attributes = _attributes(raw.get("attributes"))
    # Logfire span names are message templates; `logfire.msg` holds the rendered, readable text.
    name = attributes.get("logfire.msg") or raw.get("name") or "span"
    return OTelSpan(
        trace_id=trace_id,
        span_id=span_id,
        parent_span_id=parent_span_id,
        name=str(name)[:255],
        kind=_int(raw.get("kind")),
        start_ns=start_ns,
        end_ns=_int(raw.get("endTimeUnixNano"), start_ns),
        attributes=attributes,
        events=events,
        status_code=_int(status.get("code")) if isinstance(status, dict) else 0,
        status_message=str(status.get("message") or "") if isinstance(status, dict) else "",
        resource=resource,
        scope=scope,
    )


def group_by_trace(spans: list[OTelSpan]) -> dict[str, list[OTelSpan]]:
    groups: dict[str, list[OTelSpan]] = {}
    for span in spans:
        groups.setdefault(span.trace_id, []).append(span)
    return groups


def trace_record_id(trace_id: str) -> str:
    """CortexOps trace id for an OTel trace: the same 128 bits, formatted as a UUID."""
    t = trace_id
    return f"{t[:8]}-{t[8:12]}-{t[12:16]}-{t[16:20]}-{t[20:]}"


# ── Attribute helpers ─────────────────────────────────────────────────────

def _first(attrs: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = attrs.get(key)
        if value not in (None, ""):
            return value
    return None


def _maybe_json(value: Any) -> Any:
    if isinstance(value, str) and (value[:1] in ("{", "[") or (len(value) > 1 and value[0] == value[-1] == '"')):
        try:
            return json.loads(value)
        except ValueError:
            return value
    return value


def _as_dict(value: Any, key: str = "value") -> dict[str, Any]:
    value = _maybe_json(value)
    if value in (None, ""):
        return {}
    return value if isinstance(value, dict) else {key: value}


def _text(value: Any) -> str:
    value = _maybe_json(value)
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = [_text(p) for p in value]
        return "\n".join(p for p in parts if p)
    if isinstance(value, dict):
        for key in ("content", "text", "message"):
            if key in value:
                return _text(value[key])
    return "" if value is None else json.dumps(value, default=str)


def _message(role: Any, content: Any) -> dict[str, str]:
    return {"role": str(role or ""), "content": _text(content)}


def _semconv_messages(value: Any) -> list[dict[str, str]]:
    value = _maybe_json(value)
    if isinstance(value, dict):
        value = [value]
    if not isinstance(value, list):
        return [_message("", value)] if value else []
    messages = []
    for item in value:
        if isinstance(item, dict):
            content = item.get("parts", item.get("content", item.get("message")))
            messages.append(_message(item.get("role"), content))
        else:
            messages.append(_message("", item))
    return messages


_TOOL_CALL_FIELD = re.compile(r"tool_calls\.(\d+)\.(?:tool_call\.)?(?:function\.)?(name|arguments)$")


def _indexed_messages(attrs: dict[str, Any], prefix: str, role_key: str, content_key: str) -> list[dict[str, str]]:
    """Flattened messages like `llm.input_messages.0.message.content`, including indexed tool calls."""
    pattern = re.compile(rf"^{re.escape(prefix)}\.(\d+)\.(.+)$")
    by_index: dict[int, dict[str, Any]] = {}
    for key, value in attrs.items():
        match = pattern.match(key)
        if match:
            by_index.setdefault(int(match.group(1)), {})[match.group(2)] = value
    messages = []
    for _, fields in sorted(by_index.items()):
        calls: dict[int, dict[str, Any]] = {}
        for key, value in fields.items():
            call = _TOOL_CALL_FIELD.search(key)
            if call:
                calls.setdefault(int(call.group(1)), {})[call.group(2)] = value
        content = fields.get(content_key)
        rendered_calls = [f"tool_call {c.get('name', '')}({c.get('arguments', '')})" for _, c in sorted(calls.items())]
        if content is None and not rendered_calls:
            continue
        parts = ([_text(content)] if content is not None else []) + rendered_calls
        messages.append({"role": str(fields.get(role_key) or ""), "content": "\n".join(parts)})
    return messages


def _prompt_messages(span: OTelSpan) -> list[dict[str, str]]:
    attrs = span.attributes
    if "gen_ai.input.messages" in attrs:
        return _semconv_messages(attrs["gen_ai.input.messages"])
    for prefix, role_key, content_key in (("gen_ai.prompt", "role", "content"),
                                          ("llm.input_messages", "message.role", "message.content")):
        messages = _indexed_messages(attrs, prefix, role_key, content_key)
        if messages:
            return messages
    from_events: list[dict[str, str]] = []
    for event in span.events:
        event_attrs = event["attributes"]
        if "gen_ai.prompt" in event_attrs:
            from_events.extend(_semconv_messages(event_attrs["gen_ai.prompt"]))
        elif event["name"] in _PROMPT_EVENTS:
            role = event_attrs.get("role") or event["name"].split(".")[1]
            from_events.append(_message(role, event_attrs.get("content", event_attrs.get("message"))))
    if from_events:
        return from_events
    if "gen_ai.prompt" in attrs:
        return _semconv_messages(attrs["gen_ai.prompt"])
    return []


def _completion_messages(span: OTelSpan) -> list[dict[str, str]]:
    attrs = span.attributes
    if "gen_ai.output.messages" in attrs:
        return _semconv_messages(attrs["gen_ai.output.messages"])
    for prefix, role_key, content_key in (("gen_ai.completion", "role", "content"),
                                          ("llm.output_messages", "message.role", "message.content")):
        messages = _indexed_messages(attrs, prefix, role_key, content_key)
        if messages:
            return messages
    from_events: list[dict[str, str]] = []
    for event in span.events:
        event_attrs = event["attributes"]
        if "gen_ai.completion" in event_attrs:
            from_events.extend(_semconv_messages(event_attrs["gen_ai.completion"]))
        elif event["name"] == "gen_ai.choice":
            message = _maybe_json(event_attrs.get("message", event_attrs.get("content")))
            role = message.get("role", "assistant") if isinstance(message, dict) else "assistant"
            from_events.append(_message(role, message))
    if from_events:
        return from_events
    if "gen_ai.completion" in attrs:
        return _semconv_messages(attrs["gen_ai.completion"])
    return []


def _render(messages: list[dict[str, str]]) -> str | None:
    if not messages:
        return None
    return "\n".join(f"{m['role']}: {m['content']}" if m["role"] else m["content"] for m in messages)


def classify(attrs: dict[str, Any]) -> str:
    """Span category: llm | tool | agent | chain | retriever | guardrail | evaluator | span."""
    operation = str(attrs.get("gen_ai.operation.name") or "").lower()
    if operation == "execute_tool":
        return "tool"
    if operation in _LLM_OPERATIONS:
        return "llm"
    if operation in _AGENT_OPERATIONS:
        return "agent"
    oi_kind = str(attrs.get("openinference.span.kind") or "").upper()
    if oi_kind in _OPENINFERENCE_KINDS:
        return _OPENINFERENCE_KINDS[oi_kind]
    tl_kind = str(attrs.get("traceloop.span.kind") or "").lower()
    if tl_kind in _TRACELOOP_KINDS:
        return _TRACELOOP_KINDS[tl_kind]
    if attrs.get("llm.request.type"):
        return "llm"
    if attrs.get("gen_ai.tool.name"):
        return "tool"
    if _first(attrs, "gen_ai.request.model", "gen_ai.response.model", "llm.model_name"):
        return "llm"
    return "span"


def _usage(attrs: dict[str, Any]) -> dict[str, int]:
    usage = {}
    input_tokens = _first(attrs, "gen_ai.usage.input_tokens", "gen_ai.usage.prompt_tokens", "llm.token_count.prompt")
    output_tokens = _first(attrs, "gen_ai.usage.output_tokens", "gen_ai.usage.completion_tokens",
                           "llm.token_count.completion")
    if input_tokens is not None:
        usage["input_tokens"] = _int(input_tokens)
    if output_tokens is not None:
        usage["output_tokens"] = _int(output_tokens)
    return usage


def _error_message(span: OTelSpan) -> str | None:
    if not span.is_error:
        return None
    for event in span.events:
        if event["name"] == "exception":
            exc_type = event["attributes"].get("exception.type")
            exc_message = event["attributes"].get("exception.message")
            text = ": ".join(str(p) for p in (exc_type, exc_message) if p)
            if text:
                return text
    return span.status_message or str(span.attributes.get("error.type") or "") or "error"


def _iso(ns: int) -> str:
    return datetime.fromtimestamp(ns / 1e9, tz=timezone.utc).replace(tzinfo=None).isoformat()


def _passthrough_attributes(attrs: dict[str, Any]) -> dict[str, Any]:
    kept: dict[str, Any] = {}
    for key, value in attrs.items():
        if key in _CONTENT_KEYS or key.startswith(_CONTENT_PREFIXES):
            continue
        if isinstance(value, str) and len(value) > _MAX_ATTRIBUTE_CHARS:
            value = value[:_MAX_ATTRIBUTE_CHARS] + "..."
        kept[key] = value
        if len(kept) >= _MAX_ATTRIBUTES:
            break
    return kept


def _span_input(span: OTelSpan, category: str) -> dict[str, Any]:
    attrs = span.attributes
    if category == "llm":
        messages = _prompt_messages(span)
        if messages:
            return {"messages": messages}
    if category == "tool" and "gen_ai.tool.call.arguments" in attrs:
        return _as_dict(attrs["gen_ai.tool.call.arguments"])
    return _as_dict(_first(attrs, "input.value", "traceloop.entity.input"))


def _span_output(span: OTelSpan, category: str) -> dict[str, Any]:
    attrs = span.attributes
    if category == "llm":
        messages = _completion_messages(span)
        if messages:
            return {"messages": messages}
    if category == "tool" and "gen_ai.tool.call.result" in attrs:
        return _as_dict(attrs["gen_ai.tool.call.result"])
    return _as_dict(_first(attrs, "output.value", "traceloop.entity.output"))


# ── Span -> node / tool call ──────────────────────────────────────────────

def span_to_node(span: OTelSpan, category: str) -> dict[str, Any]:
    attrs = span.attributes
    node: dict[str, Any] = {
        "node_id": span.span_id,
        "node_name": span.name,
        "input": _span_input(span, category),
        "output": _span_output(span, category),
        "tool_calls": [],
        "llm_prompt": None,
        "llm_response": None,
        "latency_ms": span.latency_ms,
        "timestamp": _iso(span.start_ns),
        "span_id": span.span_id,
        "parent_span_id": span.parent_span_id,
        "span_kind": category,
        "start_time_unix_nano": span.start_ns,
        "status": "error" if span.is_error else "ok",
    }
    if category == "llm":
        node["llm_prompt"] = _render(_prompt_messages(span))
        node["llm_response"] = _render(_completion_messages(span))
    optional = {
        "error": _error_message(span),
        "operation": attrs.get("gen_ai.operation.name"),
        "model": _first(attrs, "gen_ai.response.model", "gen_ai.request.model", "llm.model_name",
                        "llm.request.model"),
        "provider": _first(attrs, "gen_ai.provider.name", "gen_ai.system", "llm.provider", "llm.system"),
        "entity_name": _first(attrs, "traceloop.entity.name", "gen_ai.agent.name"),
        "usage": _usage(attrs),
        "attributes": _passthrough_attributes(attrs),
    }
    node.update({k: v for k, v in optional.items() if v})
    return node


def span_to_tool_call(span: OTelSpan) -> dict[str, Any]:
    attrs = span.attributes
    result = _first(attrs, "gen_ai.tool.call.result", "output.value", "traceloop.entity.output")
    tool: dict[str, Any] = {
        "name": str(_first(attrs, "gen_ai.tool.name", "tool.name", "traceloop.entity.name") or span.name),
        "args": _span_input(span, "tool"),
        "result": _maybe_json(result),
        "status": "error" if span.is_error else "success",
        "latency_ms": span.latency_ms,
        "error": _error_message(span),
        "span_id": span.span_id,
        "parent_span_id": span.parent_span_id,
        "start_time_unix_nano": span.start_ns,
        "timestamp": _iso(span.start_ns),
    }
    call_id = attrs.get("gen_ai.tool.call.id")
    if call_id:
        tool["call_id"] = str(call_id)
    return tool


# ── Trace assembly ────────────────────────────────────────────────────────

def _root_summary(span: OTelSpan, category: str) -> dict[str, Any]:
    return {
        "span_id": span.span_id,
        "name": span.name,
        "kind": category,
        "start_time_unix_nano": span.start_ns,
        "end_time_unix_nano": span.end_ns,
        "status": "error" if span.is_error else "ok",
        "error": _error_message(span),
    }


def _root_latency_ms(root: dict[str, Any]) -> float:
    return max(root["end_time_unix_nano"] - root["start_time_unix_nano"], 0) / 1_000_000


def _environment(attrs: dict[str, Any]) -> str | None:
    value = _first(attrs, "deployment.environment.name", "deployment.environment")
    return str(value)[:50] if value is not None else None


def _failure_kind(message: str) -> str:
    return "timeout" if "timeout" in message.lower() else "unknown"


def _holder_node(holder: str, root: dict[str, Any] | None, tool: dict[str, Any]) -> dict[str, Any]:
    """Placeholder node for tool calls whose parent is the (non-node) root span or has not arrived yet."""
    is_root = root is not None and holder == root["span_id"]
    start_ns = root["start_time_unix_nano"] if is_root else tool["start_time_unix_nano"]
    return {
        "node_id": holder,
        "node_name": root["name"] if is_root else f"span {holder}",
        "input": {},
        "output": {},
        "tool_calls": [],
        "llm_prompt": None,
        "llm_response": None,
        "latency_ms": _root_latency_ms(root) if is_root else 0.0,
        "timestamp": _iso(start_ns),
        "span_id": holder,
        "parent_span_id": "",
        "span_kind": root["kind"] if is_root else "unknown",
        "start_time_unix_nano": start_ns,
        "status": "ok",
        "synthetic": True,
    }


def _tool_holder(tool: dict[str, Any], nodes: dict[str, dict[str, Any]], tools: dict[str, dict[str, Any]]) -> str:
    """Span id of the node a tool call belongs to: nearest ancestor node, else the top of its known chain."""
    current = tool
    seen = {tool["span_id"]}
    while True:
        parent = current.get("parent_span_id") or ""
        if not parent:
            return current["span_id"]
        if parent in nodes:
            return parent
        if parent in tools and parent not in seen:
            seen.add(parent)
            current = tools[parent]
            continue
        return parent


def build_trace_payload(
    trace_id: str,
    spans: list[OTelSpan],
    project: str,
    existing: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a TraceIngest-shaped payload, merging into an `existing` stored payload if given.

    Spans are keyed by span id, so re-sent spans (exporter retries) replace rather than duplicate.
    """
    existing = existing or {}
    old_meta = existing.get("metadata") or {}
    old_otel = old_meta.get("otel") or {}

    # Rebuild the flat span state from what is already stored, then overlay the new spans.
    nodes: dict[str, dict[str, Any]] = {}
    tools: dict[str, dict[str, Any]] = {}
    for node in existing.get("nodes") or []:
        for tool in node.get("tool_calls") or []:
            if tool.get("span_id"):
                tools[tool["span_id"]] = dict(tool)
        if node.get("span_id") and not node.get("synthetic"):
            nodes[node["span_id"]] = {**node, "tool_calls": []}

    root: dict[str, Any] | None = old_otel.get("root")
    root_span: OTelSpan | None = None
    for span in sorted(spans, key=lambda s: s.start_ns):
        category = classify(span.attributes)
        if not span.parent_span_id and root_span is None:
            root_span = span
            root = _root_summary(span, category)
            if category not in ("llm", "tool"):
                continue
        if category == "tool":
            tools[span.span_id] = span_to_tool_call(span)
        else:
            nodes[span.span_id] = span_to_node(span, category)
    root_id = root["span_id"] if root else ""

    ordered_tools = sorted(tools.values(), key=lambda t: t["start_time_unix_nano"])
    for tool in ordered_tools:
        holder = _tool_holder(tool, nodes, tools)
        if holder not in nodes:
            nodes[holder] = _holder_node(holder, root, tool)
        nodes[holder]["tool_calls"].append(tool)
    ordered = sorted(nodes.values(), key=lambda n: n["start_time_unix_nano"])
    real_nodes = [n for n in ordered if not n.get("synthetic")]

    if root:
        total_latency_ms = _root_latency_ms(root)
    elif real_nodes or ordered_tools:
        items = real_nodes + ordered_tools
        start = min(i["start_time_unix_nano"] for i in items)
        end = max(i["start_time_unix_nano"] + int(i["latency_ms"] * 1_000_000) for i in items)
        total_latency_ms = max(end - start, 0) / 1_000_000
    else:
        total_latency_ms = 0.0

    errors: list[str] = []
    if root and root["status"] == "error":
        errors.append(root["error"] or "error")
    errors += [f"{n['node_name']}: {n.get('error') or 'error'}"
               for n in real_nodes if n["status"] == "error" and n["span_id"] != root_id]
    errors += [f"tool {t['name']}: {t.get('error') or 'error'}"
               for t in ordered_tools if t["status"] == "error" and t["span_id"] != root_id]
    failure_detail = errors[0] if errors else None

    usage: dict[str, int] = {}
    models: list[str] = []
    for node in real_nodes:
        for key, value in (node.get("usage") or {}).items():
            usage[key] = usage.get(key, 0) + value
        if node.get("model") and str(node["model"]) not in models:
            models.append(str(node["model"]))

    root_attrs = root_span.attributes if root_span else {}
    resource = root_span.resource if root_span else (spans[0].resource if spans else {})

    case_id = existing.get("case_id")
    if root_attrs.get("cortexops.case_id"):
        case_id = str(root_attrs["cortexops.case_id"])

    prompt_name, prompt_version = existing.get("prompt_name"), existing.get("prompt_version")
    if root_span or not prompt_name:
        for attrs in [root_attrs, resource, *(s.attributes for s in spans)]:
            if attrs.get("cortexops.prompt.name"):
                prompt_name = str(attrs["cortexops.prompt.name"])
                version = attrs.get("cortexops.prompt.version")
                prompt_version = str(version) if version is not None else None
                break

    environment = _environment(resource) or _environment(root_attrs) or existing.get("environment") or "development"

    root_in_spans = root_id and (root_id in tools or any(n["span_id"] == root_id for n in real_nodes))
    otel_meta: dict[str, Any] = {
        **old_otel,
        "trace_id": trace_id,
        "root": root,
        "span_count": len(real_nodes) + len(tools) + (1 if root and not root_in_spans else 0),
    }
    if resource.get("service.name") and (root_span or "service_name" not in old_otel):
        otel_meta["service_name"] = str(resource["service.name"])
    scopes = sorted({*old_otel.get("scopes", []), *(s.scope for s in spans if s.scope)})
    if scopes:
        otel_meta["scopes"] = scopes

    metadata = {**old_meta, "source": "otlp", "otel": otel_meta}
    if usage:
        metadata["usage"] = usage
    if models:
        metadata["models"] = models

    if root_span:
        root_category = root["kind"]
        trace_input = _span_input(root_span, root_category)
        trace_output = _span_output(root_span, root_category)
    else:
        trace_input, trace_output = existing.get("input") or {}, existing.get("output") or {}

    return {
        "project": project,
        "case_id": case_id,
        "input": trace_input,
        "output": trace_output,
        "total_latency_ms": total_latency_ms,
        "status": "failed" if errors else "completed",
        "failure_kind": _failure_kind(failure_detail) if failure_detail else None,
        "failure_detail": failure_detail,
        "nodes": ordered,
        "environment": environment,
        "prompt_name": prompt_name,
        "prompt_version": prompt_version,
        "metadata": metadata,
    }


def resource_project(spans: list[OTelSpan]) -> tuple[str | None, str | None]:
    """(explicit cortexops.project, service.name) from the root span's resource, else the first span's."""
    root = next((s for s in spans if not s.parent_span_id), spans[0] if spans else None)
    if root is None:
        return None, None
    explicit = root.resource.get("cortexops.project")
    service = root.resource.get("service.name")
    return (str(explicit) if explicit else None), (str(service) if service else None)

