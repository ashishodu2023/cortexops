"""
CortexOps example — LangGraph payments agent
=============================================

A minimal but realistic multi-node LangGraph agent that handles:
  - Refund status lookup
  - Dispute classification
  - Escalation routing

Run with:
    pip install cortexops langgraph langchain-openai
    export OPENAI_API_KEY=sk-...
    python agent.py
"""

from __future__ import annotations

import json
import os
import random
from typing import Annotated, Any, TypedDict

# ---------------------------------------------------------------------------
# Tool definitions (pure functions — no external calls in this demo)
# ---------------------------------------------------------------------------

MOCK_REFUNDS: dict[str, dict] = {
    "REF-8821": {"status": "approved", "amount": 49.99, "days_remaining": 3},
    "REF-9902": {"status": "pending", "amount": 120.00, "days_remaining": 7},
    "REF-1044": {"status": "rejected", "amount": 19.99, "reason": "outside return window"},
}

MOCK_DISPUTES: dict[str, str] = {
    "duplicate_charge": "billing_error",
    "item_not_received": "fulfillment",
    "unauthorized": "fraud",
    "not_as_described": "product_quality",
}


def lookup_refund(refund_id: str) -> dict[str, Any]:
    """Look up the status of a refund by ID."""
    refund = MOCK_REFUNDS.get(refund_id)
    if not refund:
        return {"error": f"Refund {refund_id} not found"}
    return {"refund_id": refund_id, **refund}


def classify_dispute(description: str) -> dict[str, Any]:
    """Classify a dispute based on the customer description."""
    description_lower = description.lower()
    for keyword, category in MOCK_DISPUTES.items():
        if keyword.replace("_", " ") in description_lower:
            return {"category": category, "confidence": 0.92, "keyword_matched": keyword}
    return {"category": "general_inquiry", "confidence": 0.55, "keyword_matched": None}


def route_escalation(category: str, urgency: str = "normal") -> dict[str, Any]:
    """Route a classified dispute to the appropriate team."""
    routing = {
        "fraud": {"team": "fraud_prevention", "sla_hours": 2, "priority": "critical"},
        "billing_error": {"team": "billing_ops", "sla_hours": 24, "priority": "high"},
        "fulfillment": {"team": "fulfillment_ops", "sla_hours": 48, "priority": "normal"},
        "product_quality": {"team": "quality_assurance", "sla_hours": 72, "priority": "normal"},
        "general_inquiry": {"team": "tier1_support", "sla_hours": 96, "priority": "low"},
    }
    route = routing.get(category, routing["general_inquiry"])
    return {"routed_to": route["team"], "sla_hours": route["sla_hours"], "priority": route["priority"]}


TOOLS = {
    "lookup_refund": lookup_refund,
    "classify_dispute": classify_dispute,
    "route_escalation": route_escalation,
}


# ---------------------------------------------------------------------------
# LangGraph-compatible agent (mock LLM, real graph structure)
# ---------------------------------------------------------------------------
# This uses a deterministic routing agent so the example runs without
# an OpenAI key. To swap in a real LLM, replace _mock_llm_decision
# with a LangChain ChatOpenAI call.

class AgentState(TypedDict):
    input: str
    tool_calls_made: list[str]
    tool_results: dict[str, Any]
    output: str
    next: str


def _mock_llm_decision(state: AgentState) -> dict[str, Any]:
    """Simulate an LLM deciding which tool to call next."""
    user_input = state["input"].lower()
    already_called = set(state.get("tool_calls_made", []))

    if "REF-" in state["input"] and "lookup_refund" not in already_called:
        import re
        ref_match = re.search(r"REF-\d+", state["input"])
        ref_id = ref_match.group(0) if ref_match else "REF-0000"
        return {"tool": "lookup_refund", "args": {"refund_id": ref_id}}

    if any(kw in user_input for kw in ["dispute", "charge", "wrong", "error", "unauthorized", "not received", "item"]):
        if "classify_dispute" not in already_called:
            return {"tool": "classify_dispute", "args": {"description": state["input"]}}
        if "route_escalation" not in already_called:
            category = state["tool_results"].get("classify_dispute", {}).get("category", "general_inquiry")
            return {"tool": "route_escalation", "args": {"category": category}}

    return {"tool": None, "args": {}}


def router_node(state: AgentState) -> AgentState:
    """Decide next tool or finish."""
    decision = _mock_llm_decision(state)
    if decision["tool"] is None:
        return {**state, "next": "responder"}
    return {**state, "next": decision["tool"], "_pending_tool": decision}


def tool_node(state: AgentState) -> AgentState:
    """Execute the selected tool."""
    pending = state.get("_pending_tool", {})
    tool_name = pending.get("tool")
    tool_args = pending.get("args", {})

    if not tool_name or tool_name not in TOOLS:
        return {**state, "next": "responder"}

    result = TOOLS[tool_name](**tool_args)
    return {
        **state,
        "tool_calls_made": [*state.get("tool_calls_made", []), tool_name],
        "tool_results": {**state.get("tool_results", {}), tool_name: result},
        "next": "router",
    }


def responder_node(state: AgentState) -> AgentState:
    """Generate a final response from accumulated tool results."""
    results = state.get("tool_results", {})
    parts: list[str] = []

    if "lookup_refund" in results:
        r = results["lookup_refund"]
        if "error" in r:
            parts.append(r["error"])
        elif r["status"] == "approved":
            parts.append(f"Refund {r['refund_id']} is approved. Expect credit in {r['days_remaining']} business days.")
        elif r["status"] == "pending":
            parts.append(f"Refund {r['refund_id']} is pending review ({r['days_remaining']} days remaining).")
        else:
            parts.append(f"Refund {r['refund_id']} was {r['status']}. {r.get('reason', '')}")

    if "route_escalation" in results:
        r = results["route_escalation"]
        parts.append(f"Your case has been escalated to {r['routed_to']} (SLA: {r['sla_hours']}h, priority: {r['priority']}).")

    if not parts:
        parts.append(f"Thank you for contacting support regarding: {state['input']}")

    return {**state, "output": " ".join(parts), "tool_calls_made": state.get("tool_calls_made", []), "next": "__end__"}


# ---------------------------------------------------------------------------
# Build the graph
# ---------------------------------------------------------------------------

def build_agent():
    """Build and compile the LangGraph payments agent.

    Returns a simple callable that mimics the LangGraph .invoke() interface
    without requiring langgraph to be installed for the demo.
    """
    try:
        from langgraph.graph import END, StateGraph

        g = StateGraph(AgentState)
        g.add_node("router", router_node)
        g.add_node("tool", tool_node)
        g.add_node("responder", responder_node)

        g.set_entry_point("router")
        g.add_conditional_edges(
            "router",
            lambda s: s["next"],
            {"lookup_refund": "tool", "classify_dispute": "tool", "route_escalation": "tool", "responder": "responder"},
        )
        g.add_conditional_edges("tool", lambda s: s["next"], {"router": "router", "responder": "responder"})
        g.add_edge("responder", END)
        return g.compile()

    except ImportError:
        # Fallback: plain callable that runs the same logic without LangGraph
        class FallbackGraph:
            def invoke(self, inp: dict) -> dict:
                state: AgentState = {
                    "input": inp.get("input", ""),
                    "tool_calls_made": [],
                    "tool_results": {},
                    "output": "",
                    "next": "router",
                }
                for _ in range(10):  # max iterations
                    if state["next"] == "router":
                        state = router_node(state)
                    elif state["next"] in TOOLS:
                        state = tool_node(state)
                    elif state["next"] == "responder":
                        state = responder_node(state)
                    elif state["next"] == "__end__":
                        break
                return {"output": state["output"], "tool_calls_made": state["tool_calls_made"]}

        return FallbackGraph()


# ---------------------------------------------------------------------------
# Standalone demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from cortexops import CortexTracer

    tracer = CortexTracer(project="payments-agent")
    agent = tracer.wrap(build_agent())

    test_inputs = [
        "What is the status of refund REF-8821?",
        "I was charged twice on my credit card — this is unauthorized",
        "My item REF-9902 still hasn't arrived",
    ]

    print("CortexOps — payments agent demo\n" + "=" * 40)
    for q in test_inputs:
        print(f"\nInput : {q}")
        result = agent.invoke({"input": q})
        print(f"Output: {result.get('output', result)}")

    trace = tracer.last_trace()
    print(f"\nLast trace: {trace.trace_id}")
    print(f"Latency   : {trace.total_latency_ms:.1f}ms")
    print(f"Status    : {trace.status}")
