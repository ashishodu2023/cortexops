"""cortexops.otel.OTelExporter: CortexOps traces -> OpenTelemetry spans (GenAI semantic conventions)."""

from __future__ import annotations

import json
import sys
import uuid

import pytest

pytest.importorskip("opentelemetry.sdk")

from opentelemetry import trace as otel_trace  # noqa: E402
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter  # noqa: E402
from opentelemetry.trace import SpanKind, StatusCode  # noqa: E402

from cortexops import CortexTracer  # noqa: E402
from cortexops.models import FailureKind, RunStatus, ToolCall, ToolCallStatus, Trace, TraceNode  # noqa: E402
from cortexops.otel import OTelExporter, _traces_endpoint  # noqa: E402


@pytest.fixture
def memory():
    return InMemorySpanExporter()


@pytest.fixture
def exporter(memory):
    exp = OTelExporter(span_exporter=memory, batch=False)
    yield exp
    exp.shutdown()


def _by_name(spans):
    return {s.name: s for s in spans}


def _agent_tracer(exporter, **kwargs):
    tracer = CortexTracer(project="payments-agent", environment="staging", exporters=[exporter], **kwargs)

    def agent(inp: dict) -> dict:
        with tracer.trace_node("plan") as node:
            node.llm_prompt = "Refund order 4821?"
            node.llm_response = "Look up the order first."
        with tracer.trace_node("act"):
            pass
        tracer.record_tool_call("lookup_order", args={"order_id": "4821"}, result={"status": "delivered"},
                                latency_ms=5.0)
        return {"answer": "approved"}

    return tracer, tracer.wrap(agent)


def test_tracer_exports_trace_as_genai_spans(exporter, memory):
    tracer, agent = _agent_tracer(exporter)
    tracer.set_prompt("refund-system", "v3")
    agent({"question": "Refund order 4821"})
    trace = tracer.last_trace()

    spans = _by_name(memory.get_finished_spans())
    assert set(spans) == {"invoke_agent payments-agent", "plan", "act", "execute_tool lookup_order"}
    root, plan, act, tool = (spans[n] for n in ("invoke_agent payments-agent", "plan", "act",
                                                "execute_tool lookup_order"))

    # Same trace id in CortexOps and the OTel backend
    assert format(root.context.trace_id, "032x") == uuid.UUID(trace.trace_id).hex
    assert {s.context.trace_id for s in spans.values()} == {root.context.trace_id}
    assert root.parent is None
    assert plan.parent.span_id == act.parent.span_id == root.context.span_id
    assert tool.parent.span_id == act.context.span_id

    assert root.attributes["gen_ai.operation.name"] == "invoke_agent"
    assert root.attributes["gen_ai.agent.name"] == "payments-agent"
    assert root.attributes["cortexops.trace_id"] == trace.trace_id
    assert root.attributes["cortexops.prompt.name"] == "refund-system"
    assert root.attributes["cortexops.prompt.version"] == "v3"
    assert root.attributes["cortexops.metadata.sampled"] is True
    assert json.loads(root.attributes["output.value"]) == {"answer": "approved"}
    assert root.status.status_code == StatusCode.UNSET

    assert plan.kind == SpanKind.CLIENT
    assert plan.attributes["gen_ai.operation.name"] == "chat"
    assert json.loads(plan.attributes["gen_ai.input.messages"])[0]["parts"][0]["content"] == "Refund order 4821?"
    assert json.loads(plan.attributes["gen_ai.output.messages"])[0]["role"] == "assistant"
    assert act.kind == SpanKind.INTERNAL
    assert "gen_ai.operation.name" not in act.attributes

    assert tool.attributes["gen_ai.operation.name"] == "execute_tool"
    assert tool.attributes["gen_ai.tool.name"] == "lookup_order"
    assert json.loads(tool.attributes["gen_ai.tool.call.arguments"]) == {"order_id": "4821"}
    assert json.loads(tool.attributes["gen_ai.tool.call.result"]) == {"status": "delivered"}
    assert (tool.end_time - tool.start_time) == 5_000_000

    resource = root.resource.attributes
    assert resource["service.name"] == "payments-agent"
    assert resource["cortexops.project"] == "payments-agent"
    assert resource["deployment.environment.name"] == "staging"


def test_root_duration_matches_trace_latency(exporter, memory):
    trace = Trace(project="p", total_latency_ms=250.0, nodes=[TraceNode(node_id="n", node_name="step", latency_ms=40)])
    exporter.export(trace)
    root = _by_name(memory.get_finished_spans())["invoke_agent p"]
    assert root.end_time - root.start_time == 250_000_000


def test_failed_run_sets_error_status_and_exception_event(exporter, memory):
    tracer = CortexTracer(project="payments-agent", exporters=[exporter])

    def boom(inp: dict) -> dict:
        raise RuntimeError("payment gateway timeout")

    with pytest.raises(RuntimeError):
        tracer.wrap(boom)({"q": "x"})

    root = memory.get_finished_spans()[0]
    assert root.status.status_code == StatusCode.ERROR
    assert root.status.description == "payment gateway timeout"
    assert root.attributes["error.type"] == "unknown"
    (event,) = root.events
    assert event.name == "exception"
    assert event.attributes["exception.message"] == "payment gateway timeout"
    assert "exception.type" not in event.attributes


def test_unsampled_errors_are_exported(exporter, memory):
    tracer = CortexTracer(project="p", sample_rate=0.0, sample_errors=True, exporters=[exporter])

    def boom(inp: dict) -> dict:
        raise ValueError("bad input")

    with pytest.raises(ValueError):
        tracer.wrap(boom)({})
    (root,) = memory.get_finished_spans()
    assert root.attributes["cortexops.metadata.captured_reason"] == "error"
    assert root.status.status_code == StatusCode.ERROR


def test_tool_error_marks_tool_span(exporter, memory):
    trace = Trace(project="p", status=RunStatus.FAILED, failure_kind=FailureKind.TOOL_CALL_MISMATCH,
                  failure_detail="refund rejected", nodes=[TraceNode(
                      node_id="n1", node_name="act",
                      tool_calls=[ToolCall(name="issue_refund", status=ToolCallStatus.TIMEOUT, error="timed out")],
                  )])
    exporter.export(trace)
    spans = _by_name(memory.get_finished_spans())
    tool = spans["execute_tool issue_refund"]
    assert tool.status.status_code == StatusCode.ERROR
    assert tool.status.description == "timed out"
    assert tool.attributes["error.type"] == "timeout"
    assert spans["invoke_agent p"].attributes["cortexops.failure_kind"] == "tool_call_mismatch"


def test_include_content_false_drops_payloads(memory):
    exp = OTelExporter(span_exporter=memory, batch=False, include_content=False)
    tracer, agent = _agent_tracer(exp)
    agent({"question": "my email is jane@acme.io"})
    exp.shutdown()
    content_keys = {"input.value", "output.value", "gen_ai.input.messages", "gen_ai.output.messages",
                    "gen_ai.tool.call.arguments", "gen_ai.tool.call.result"}
    for span in memory.get_finished_spans():
        assert not content_keys & set(span.attributes)
    assert "gen_ai.tool.name" in _by_name(memory.get_finished_spans())["execute_tool lookup_order"].attributes


def test_service_name_and_resource_attributes(memory):
    exp = OTelExporter(span_exporter=memory, batch=False, service_name="refund-svc",
                       resource_attributes={"service.version": "1.2.0"})
    exp.export(Trace(project="payments-agent", environment="production"))
    exp.shutdown()
    resource = memory.get_finished_spans()[0].resource.attributes
    assert resource["service.name"] == "refund-svc"
    assert resource["service.version"] == "1.2.0"
    assert resource["deployment.environment.name"] == "production"


def test_does_not_touch_global_tracer_provider(exporter):
    before = otel_trace.get_tracer_provider()
    exporter.export(Trace(project="p"))
    assert otel_trace.get_tracer_provider() is before


def test_failing_exporter_never_breaks_the_agent():
    class Broken:
        def export(self, trace):
            raise RuntimeError("collector down")

    tracer = CortexTracer(project="p", exporters=[Broken()])
    assert tracer.wrap(lambda inp: {"ok": True})({"x": 1}) == {"ok": True}
    assert tracer.last_trace().status == RunStatus.COMPLETED


def test_otlp_http_exporter_endpoint_normalization():
    assert _traces_endpoint("http://localhost:4318") == "http://localhost:4318/v1/traces"
    assert _traces_endpoint("http://localhost:4318/") == "http://localhost:4318/v1/traces"
    assert _traces_endpoint("https://api.getcortexops.com/v1/otlp/v1/traces") == (
        "https://api.getcortexops.com/v1/otlp/v1/traces"
    )
    assert _traces_endpoint(None) is None

    pytest.importorskip("opentelemetry.exporter.otlp.proto.http")
    exp = OTelExporter(endpoint="http://collector:4318", headers={"x-honeycomb-team": "k"})
    assert exp.span_exporter._endpoint == "http://collector:4318/v1/traces"
    exp.shutdown()


def test_missing_opentelemetry_raises_helpful_error(monkeypatch):
    monkeypatch.setitem(sys.modules, "opentelemetry.sdk.trace.export", None)
    with pytest.raises(ImportError, match=r"cortexops\[otel\]"):
        OTelExporter()
