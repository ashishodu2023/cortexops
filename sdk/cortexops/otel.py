"""Export CortexOps traces to any OpenTelemetry backend (Jaeger, Tempo, Honeycomb, Datadog, a Collector, ...).

Requires the optional extra:  pip install 'cortexops[otel]'

Usage:
    from cortexops import CortexTracer
    from cortexops.otel import OTelExporter

    tracer = CortexTracer(project="payments-agent", exporters=[OTelExporter(endpoint="http://localhost:4318")])

Each CortexOps trace becomes one OTel trace whose trace id equals the CortexOps trace id
(UUID without dashes): an `invoke_agent` root span, one child span per node and an
`execute_tool` span per tool call, annotated with OpenTelemetry GenAI semantic-convention
attributes. The exporter uses its own TracerProvider, so it never changes the application's
global OpenTelemetry configuration.
"""
from __future__ import annotations

import json
import logging
import threading
import uuid
from datetime import datetime, timezone
from typing import Any

from .models import RunStatus, ToolCallStatus, Trace, TraceNode

_log = logging.getLogger(__name__)

_INSTALL_HINT = "OTelExporter requires OpenTelemetry: pip install 'cortexops[otel]'"
_SCOPE = "cortexops"


def _ns(ts: datetime) -> int:
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return int(ts.timestamp() * 1_000_000_000)


def _ms_to_ns(ms: float) -> int:
    return int(max(ms, 0.0) * 1_000_000)


def _json(value: Any) -> str:
    return value if isinstance(value, str) else json.dumps(value, default=str)


def _messages(role: str, content: str) -> str:
    return json.dumps([{"role": role, "parts": [{"type": "text", "content": content}]}])


def _scalar(value: Any) -> Any:
    return value if isinstance(value, (str, bool, int, float)) else _json(value)


def _traces_endpoint(endpoint: str | None) -> str | None:
    """Accept either an OTLP base URL (http://host:4318) or the full traces URL."""
    if not endpoint:
        return None
    endpoint = endpoint.rstrip("/")
    return endpoint if endpoint.endswith("/v1/traces") else f"{endpoint}/v1/traces"


class OTelExporter:
    """Convert finished CortexOps traces into OpenTelemetry spans and export them.

    Args:
        endpoint: OTLP/HTTP endpoint, either the base (``http://localhost:4318``) or the full
            ``.../v1/traces`` URL. Defaults to the standard ``OTEL_EXPORTER_OTLP_*`` env vars.
        headers: Extra HTTP headers for the OTLP exporter (e.g. vendor API keys).
        service_name: ``service.name`` resource attribute. Defaults to the trace's project.
        span_exporter: Any OpenTelemetry ``SpanExporter`` to use instead of OTLP/HTTP
            (gRPC exporter, ConsoleSpanExporter, InMemorySpanExporter, ...).
        batch: Export through a BatchSpanProcessor (default, non-blocking). ``False`` exports
            synchronously, which is handy in scripts and tests.
        include_content: Record inputs, outputs, prompts, responses and tool arguments/results.
            Set ``False`` when the backend must not receive prompt or user content.
        resource_attributes: Extra resource attributes (e.g. ``{"service.version": "1.2.0"}``).
        timeout: OTLP export timeout in seconds.
    """

    def __init__(
        self,
        endpoint: str | None = None,
        headers: dict[str, str] | None = None,
        *,
        service_name: str | None = None,
        span_exporter: Any = None,
        batch: bool = True,
        include_content: bool = True,
        resource_attributes: dict[str, Any] | None = None,
        timeout: float = 10.0,
    ) -> None:
        try:
            from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor
        except ImportError as exc:
            raise ImportError(_INSTALL_HINT) from exc

        if span_exporter is None:
            try:
                from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
            except ImportError as exc:
                raise ImportError(_INSTALL_HINT) from exc
            span_exporter = OTLPSpanExporter(endpoint=_traces_endpoint(endpoint), headers=headers, timeout=timeout)

        self.span_exporter = span_exporter
        self.service_name = service_name
        self.include_content = include_content
        self.resource_attributes = dict(resource_attributes or {})
        self._processor_cls = BatchSpanProcessor if batch else SimpleSpanProcessor
        self._providers: dict[tuple[str, str | None], Any] = {}
        self._id_generator = _fixed_trace_id_generator()
        self._lock = threading.Lock()

    # ── Exporter protocol used by CortexTracer ───────────────────────────

    def export(self, trace: Trace) -> None:
        """Emit `trace` as OpenTelemetry spans."""
        from opentelemetry import trace as otel_trace
        from opentelemetry.trace import SpanKind, Status, StatusCode

        tracer = self._provider(trace).get_tracer(_SCOPE)
        start = _ns(trace.timestamp)
        end = start + _ms_to_ns(trace.total_latency_ms)

        with self._lock:
            self._id_generator.next_trace_id = _trace_id_int(trace.trace_id)
            try:
                root = tracer.start_span(
                    f"invoke_agent {trace.project}",
                    kind=SpanKind.INTERNAL,
                    attributes=self._root_attributes(trace),
                    start_time=start,
                )
            finally:
                self._id_generator.next_trace_id = None

        if trace.status == RunStatus.FAILED:
            kind = trace.failure_kind.value if trace.failure_kind else "unknown"
            root.set_status(Status(StatusCode.ERROR, trace.failure_detail or None))
            root.set_attribute("error.type", kind)
            event = {"exception.message": trace.failure_detail or kind}
            if kind != "unknown":
                event["exception.type"] = kind
            root.add_event("exception", event, timestamp=end)

        parent_ctx = otel_trace.set_span_in_context(root)
        for node in trace.nodes:
            self._export_node(tracer, node, parent_ctx, default_start=start)
        root.end(end_time=end)

    def force_flush(self, timeout_millis: int = 30_000) -> bool:
        return all(p.force_flush(timeout_millis) for p in list(self._providers.values()))

    def shutdown(self) -> None:
        for provider in list(self._providers.values()):
            provider.shutdown()
        self._providers.clear()

    # ── Internals ────────────────────────────────────────────────────────

    def _provider(self, trace: Trace) -> Any:
        key = (trace.project, trace.environment)
        provider = self._providers.get(key)
        if provider is not None:
            return provider
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider

        with self._lock:
            provider = self._providers.get(key)
            if provider is None:
                attributes: dict[str, Any] = {
                    "service.name": self.service_name or trace.project,
                    "cortexops.project": trace.project,
                }
                if trace.environment:
                    attributes["deployment.environment.name"] = trace.environment
                attributes.update(self.resource_attributes)
                provider = TracerProvider(resource=Resource.create(attributes), id_generator=self._id_generator)
                provider.add_span_processor(self._processor_cls(self.span_exporter))
                self._providers[key] = provider
        return provider

    def _root_attributes(self, trace: Trace) -> dict[str, Any]:
        attrs: dict[str, Any] = {
            "gen_ai.operation.name": "invoke_agent",
            "gen_ai.agent.name": trace.project,
            "cortexops.trace_id": trace.trace_id,
            "cortexops.run_id": trace.run_id,
            "cortexops.status": trace.status.value,
        }
        optional = {
            "cortexops.case_id": trace.case_id,
            "cortexops.prompt.name": trace.prompt_name,
            "cortexops.prompt.version": trace.prompt_version,
            "cortexops.failure_kind": trace.failure_kind.value if trace.failure_kind else None,
        }
        attrs.update({k: v for k, v in optional.items() if v is not None})
        for key, value in trace.metadata.items():
            if value is not None:
                attrs[f"cortexops.metadata.{key}"] = _scalar(value)
        if self.include_content:
            if trace.input:
                attrs["input.value"] = _json(trace.input)
            if trace.output:
                attrs["output.value"] = _json(trace.output)
        return attrs

    def _export_node(self, tracer: Any, node: TraceNode, parent_ctx: Any, *, default_start: int) -> None:
        from opentelemetry import trace as otel_trace
        from opentelemetry.trace import SpanKind, Status, StatusCode

        start = _ns(node.timestamp) if node.timestamp else default_start
        end = start + _ms_to_ns(node.latency_ms)
        is_llm = bool(node.llm_prompt or node.llm_response)
        attrs: dict[str, Any] = {"cortexops.node.id": node.node_id, "cortexops.node.name": node.node_name}
        if is_llm:
            attrs["gen_ai.operation.name"] = "chat"
        if self.include_content:
            if node.input:
                attrs["input.value"] = _json(node.input)
            if node.output:
                attrs["output.value"] = _json(node.output)
            if node.llm_prompt:
                attrs["gen_ai.input.messages"] = _messages("user", node.llm_prompt)
            if node.llm_response:
                attrs["gen_ai.output.messages"] = _messages("assistant", node.llm_response)

        span = tracer.start_span(
            node.node_name,
            context=parent_ctx,
            kind=SpanKind.CLIENT if is_llm else SpanKind.INTERNAL,
            attributes=attrs,
            start_time=start,
        )
        node_ctx = otel_trace.set_span_in_context(span)
        offset = start
        for tc in node.tool_calls:
            tc_end = offset + _ms_to_ns(tc.latency_ms)
            tc_attrs: dict[str, Any] = {
                "gen_ai.operation.name": "execute_tool",
                "gen_ai.tool.name": tc.name,
                "gen_ai.tool.type": "function",
                "cortexops.tool.status": tc.status.value,
            }
            if self.include_content:
                if tc.args:
                    tc_attrs["gen_ai.tool.call.arguments"] = _json(tc.args)
                if tc.result is not None:
                    tc_attrs["gen_ai.tool.call.result"] = _json(tc.result)
            tool_span = tracer.start_span(
                f"execute_tool {tc.name}", context=node_ctx, kind=SpanKind.INTERNAL,
                attributes=tc_attrs, start_time=offset,
            )
            if tc.status != ToolCallStatus.SUCCESS:
                tool_span.set_status(Status(StatusCode.ERROR, tc.error or tc.status.value))
                tool_span.set_attribute("error.type", tc.status.value)
            tool_span.end(end_time=tc_end)
            offset = tc_end
        span.end(end_time=max(end, offset))


def _trace_id_int(trace_id: str) -> int | None:
    try:
        value = uuid.UUID(trace_id).int
    except (ValueError, AttributeError, TypeError):
        return None
    return value or None


def _fixed_trace_id_generator() -> Any:
    """Random ids, except the next root span reuses the CortexOps trace id so both systems share it.

    CortexOps trace ids are UUID4s, whose rightmost 7 bytes are random, so the inherited
    `is_trace_id_random() -> True` (W3C random flag) still holds.
    """
    from opentelemetry.sdk.trace.id_generator import RandomIdGenerator

    class _FixedTraceIdGenerator(RandomIdGenerator):
        next_trace_id: int | None = None

        def generate_trace_id(self) -> int:
            return self.next_trace_id or super().generate_trace_id()

    return _FixedTraceIdGenerator()
