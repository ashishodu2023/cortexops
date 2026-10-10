"""Send OpenTelemetry traces from an instrumented OpenAI app to CortexOps (no CortexOps SDK needed).

    pip install -r requirements.txt
    export CORTEXOPS_API_KEY=cxo-...
    python app.py --instrumentation openllmetry      # or: openinference

Configuration is the standard OpenTelemetry environment:
    OTEL_EXPORTER_OTLP_ENDPOINT   default https://api.getcortexops.com/v1/otlp
    OTEL_EXPORTER_OTLP_HEADERS    default Authorization=Bearer <CORTEXOPS_API_KEY>
    OTEL_SERVICE_NAME             default refund-service

Without OPENAI_API_KEY (or with --mock) the OpenAI API is replaced by a canned local response,
so the example runs anywhere. The instrumentation still records real spans.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import uuid

import httpx
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

TOOLS = [{
    "type": "function",
    "function": {
        "name": "lookup_order",
        "description": "Look up an order by id",
        "parameters": {"type": "object", "properties": {"order_id": {"type": "string"}}, "required": ["order_id"]},
    },
}]


def configure_otel() -> TracerProvider:
    os.environ.setdefault("OTEL_EXPORTER_OTLP_ENDPOINT", "https://api.getcortexops.com/v1/otlp")
    api_key = os.getenv("CORTEXOPS_API_KEY")
    if "OTEL_EXPORTER_OTLP_HEADERS" not in os.environ:
        if not api_key:
            sys.exit("Set CORTEXOPS_API_KEY (or OTEL_EXPORTER_OTLP_HEADERS).")
        os.environ["OTEL_EXPORTER_OTLP_HEADERS"] = f"Authorization=Bearer {api_key}"

    resource = Resource.create({
        "service.name": os.getenv("OTEL_SERVICE_NAME", "refund-service"),
        "deployment.environment.name": os.getenv("DEPLOY_ENV", "development"),
        # Optional: route to a specific CortexOps project. Defaults to the API key's project.
        **({"cortexops.project": os.environ["CORTEXOPS_PROJECT"]} if os.getenv("CORTEXOPS_PROJECT") else {}),
        # Optional: tag traces with the prompt version under test.
        "cortexops.prompt.name": "refund-system",
        "cortexops.prompt.version": "v3",
    })
    provider = TracerProvider(resource=resource)
    # Reads OTEL_EXPORTER_OTLP_ENDPOINT / _HEADERS and appends /v1/traces.
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(provider)
    return provider


def instrument(kind: str, provider: TracerProvider) -> None:
    if kind == "openllmetry":
        from opentelemetry.instrumentation.openai import OpenAIInstrumentor
    else:
        from openinference.instrumentation.openai import OpenAIInstrumentor
    OpenAIInstrumentor().instrument(tracer_provider=provider)


def mock_openai_transport() -> httpx.MockTransport:
    """Canned Chat Completions: first a tool call, then the final answer."""
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        has_tool_result = any(m.get("role") == "tool" for m in body["messages"])
        message = (
            {"role": "assistant", "content": "Order 4821 was delivered, so the refund is approved."}
            if has_tool_result else
            {"role": "assistant", "content": None, "tool_calls": [{
                "id": "call_1", "type": "function",
                "function": {"name": "lookup_order", "arguments": json.dumps({"order_id": "4821"})},
            }]}
        )
        return httpx.Response(200, json={
            "id": "chatcmpl-mock", "object": "chat.completion", "created": 0, "model": "gpt-4o-mini-2024-07-18",
            "choices": [{"index": 0, "message": message,
                         "finish_reason": "stop" if has_tool_result else "tool_calls"}],
            "usage": {"prompt_tokens": 57, "completion_tokens": 14, "total_tokens": 71},
        })
    return httpx.MockTransport(handler)


def lookup_order(order_id: str) -> dict:
    return {"order_id": order_id, "status": "delivered"}


def run_agent(client, tracer: trace.Tracer, question: str) -> tuple[str, int]:
    # The root span becomes the CortexOps trace; its input/output become the trace input/output.
    with tracer.start_as_current_span("invoke_agent refund-agent", attributes={
        "gen_ai.operation.name": "invoke_agent",
        "gen_ai.agent.name": "refund-agent",
        "input.value": question,
    }) as agent_span:
        messages = [{"role": "system", "content": "You approve refunds for delivered orders."},
                    {"role": "user", "content": question}]
        reply = client.chat.completions.create(model="gpt-4o-mini", messages=messages, tools=TOOLS)
        call = reply.choices[0].message.tool_calls[0]
        args = json.loads(call.function.arguments)

        # Tool execution span per the GenAI semantic conventions -> a CortexOps tool call.
        with tracer.start_as_current_span(f"execute_tool {call.function.name}", attributes={
            "gen_ai.operation.name": "execute_tool",
            "gen_ai.tool.name": call.function.name,
            "gen_ai.tool.call.id": call.id,
            "gen_ai.tool.call.arguments": call.function.arguments,
        }) as tool_span:
            result = lookup_order(**args)
            tool_span.set_attribute("gen_ai.tool.call.result", json.dumps(result))

        messages += [reply.choices[0].message.model_dump(exclude_none=True),
                     {"role": "tool", "tool_call_id": call.id, "content": json.dumps(result)}]
        final = client.chat.completions.create(model="gpt-4o-mini", messages=messages, tools=TOOLS)
        answer = final.choices[0].message.content
        agent_span.set_attribute("output.value", answer)
        return answer, agent_span.get_span_context().trace_id


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--instrumentation", choices=["openllmetry", "openinference"], default="openllmetry")
    parser.add_argument("--mock", action="store_true", help="use a canned OpenAI response instead of the API")
    args = parser.parse_args()

    provider = configure_otel()
    instrument(args.instrumentation, provider)

    import openai

    mock = args.mock or not os.getenv("OPENAI_API_KEY")
    if mock:
        print("Using a mocked OpenAI API (pass OPENAI_API_KEY and omit --mock for real calls).")
        client = openai.OpenAI(api_key="sk-mock", base_url="http://mock.openai.local/v1",
                               http_client=httpx.Client(transport=mock_openai_transport()))
    else:
        client = openai.OpenAI()

    tracer = trace.get_tracer("refund-agent")
    answer, trace_id = run_agent(client, tracer, "Please refund order 4821")
    print(f"agent answer: {answer}")
    provider.shutdown()  # flush spans before exit
    # CortexOps stores the OTel trace under the same 128-bit id, formatted as a UUID.
    print(f"exported to {os.environ['OTEL_EXPORTER_OTLP_ENDPOINT']}; CortexOps trace id {uuid.UUID(int=trace_id)}")


if __name__ == "__main__":
    main()
