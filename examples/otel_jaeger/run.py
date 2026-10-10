"""Export CortexOps traces to Jaeger over OTLP/HTTP.

    docker compose up -d                 # Jaeger UI on http://localhost:16686
    pip install 'cortexops[otel]'
    python run.py

Runs a small simulated refund agent (no LLM key needed) and prints a Jaeger link per trace.
Set OTEL_EXPORTER_OTLP_ENDPOINT to export somewhere other than http://localhost:4318.
Set CORTEXOPS_API_KEY to also send the same traces to CortexOps.
"""
from __future__ import annotations

import os
import time
import uuid

from cortexops import CortexTracer
from cortexops.otel import OTelExporter

JAEGER_UI = os.getenv("JAEGER_UI", "http://localhost:16686")
ENDPOINT = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318")

exporter = OTelExporter(endpoint=ENDPOINT, service_name="refund-agent")
tracer = CortexTracer(project="payments-agent", environment="development", exporters=[exporter])
tracer.set_prompt("refund-system", "v3")


def lookup_order(order_id: str) -> dict:
    time.sleep(0.03)
    return {"order_id": order_id, "status": "delivered", "amount": 129.0}


def refund_agent(request: dict) -> dict:
    order_id = request["order_id"]

    with tracer.trace_node("classify") as node:
        time.sleep(0.05)
        node.llm_prompt = f"Classify the customer request: {request['message']}"
        node.llm_response = "intent=refund"
        node.output = {"intent": "refund"}

    with tracer.trace_node("check_order") as node:
        t0 = time.perf_counter()
        order = lookup_order(order_id)
        node.output = order
    tracer.record_tool_call("lookup_order", args={"order_id": order_id}, result=order,
                            latency_ms=(time.perf_counter() - t0) * 1000)

    with tracer.trace_node("decide") as node:
        time.sleep(0.04)
        if order_id == "9999":
            raise RuntimeError("refund policy service timeout")
        node.llm_prompt = f"Order {order_id} is {order['status']}. Approve refund?"
        node.llm_response = "Approve the refund."

    return {"decision": "approved", "order_id": order_id}


def main() -> None:
    agent = tracer.wrap(refund_agent)
    for order_id in ("4821", "9999"):
        try:
            agent({"order_id": order_id, "message": f"Please refund order {order_id}"})
        except RuntimeError as exc:
            print(f"order {order_id}: agent failed ({exc})")
        trace = tracer.last_trace()
        print(f"order {order_id}: {trace.status.value:9s} {JAEGER_UI}/trace/{uuid.UUID(trace.trace_id).hex}")

    exporter.shutdown()  # flush the batch processor before exit
    print(f"\nOpen {JAEGER_UI}/search?service=refund-agent to browse all traces.")


if __name__ == "__main__":
    main()
