"""
examples/langgraph_integration.py

Shows how to wrap a real LangGraph multi-agent workflow
to capture MASEV-compatible traces.

This is the template to follow when replacing the simulated
experiment with your actual LangGraph payments agent.
"""

from __future__ import annotations

import time
from typing import Any

# -- MASEV imports --
from masev import (
    Action,
    ActionType,
    AgentSpec,
    MASEvaluator,
    Message,
    MetricConfig,
    Trace,
    TraceStep,
)

# -- Your LangGraph imports (uncomment when ready) --
# from langgraph.graph import StateGraph, END
# from langchain_openai import ChatOpenAI


# ---------------------------------------------------------------------------
# Step 1: Define a trace-capturing callback
# ---------------------------------------------------------------------------

class MASEVTraceCallback:
    """
    Drop-in callback that captures LangGraph node executions
    as MASEV trace steps.

    Usage with LangGraph:
        callback = MASEVTraceCallback(agents=["fraud", "compliance", "router"])
        # Pass to your graph execution
        result = graph.invoke(input_state, config={"callbacks": [callback]})
        trace = callback.to_trace(task_success=True)
    """

    def __init__(self, agents: list[str]):
        self.agents = agents
        self.steps: list[TraceStep] = []
        self._current_step_id = 0
        self._start_time = time.time()

    def on_node_start(self, node_name: str, inputs: dict[str, Any]) -> None:
        """Call at the start of each LangGraph node execution."""
        step = TraceStep(
            step_id=self._current_step_id,
            timestamp=time.time(),
        )
        # Map node_name to agent_id
        agent_id = node_name  # or use a mapping dict

        step.actions.append(Action(
            agent_id=agent_id,
            action_type=ActionType.REASONING,
            content=f"Processing: {str(inputs)[:200]}",
            timestamp=time.time(),
        ))
        self.steps.append(step)

    def on_tool_call(
        self,
        agent_id: str,
        tool_name: str,
        tool_args: dict[str, Any],
        result: str,
    ) -> None:
        """Call when an agent invokes a tool."""
        if not self.steps:
            self.on_node_start(agent_id, {})

        self.steps[-1].actions.append(Action(
            agent_id=agent_id,
            action_type=ActionType.TOOL_CALL,
            content=f"Tool result: {result[:200]}",
            tool_name=tool_name,
            tool_args=tool_args,
            timestamp=time.time(),
        ))

    def on_message(self, sender: str, receiver: str, content: str) -> None:
        """Call when an agent sends a message to another agent."""
        if not self.steps:
            self.on_node_start(sender, {})

        self.steps[-1].messages.append(Message(
            sender=sender,
            receiver=receiver,
            content=content[:500],
            timestamp=time.time(),
        ))

    def on_node_end(self, node_name: str, outputs: dict[str, Any]) -> None:
        """Call at the end of each node execution."""
        if self.steps:
            self.steps[-1].actions.append(Action(
                agent_id=node_name,
                action_type=ActionType.OUTPUT,
                content=f"Output: {str(outputs)[:200]}",
                timestamp=time.time(),
            ))
        self._current_step_id += 1

    def to_trace(
        self,
        task_description: str = "",
        task_success: bool | None = None,
    ) -> Trace:
        """Convert captured data to a MASEV Trace."""
        return Trace(
            agents=self.agents,
            steps=self.steps,
            task_description=task_description,
            task_success=task_success,
            task_score=1.0 if task_success else 0.0,
        )


# ---------------------------------------------------------------------------
# Step 2: Example integration pattern
# ---------------------------------------------------------------------------

def example_usage():
    """
    Shows the full pattern for instrumenting a LangGraph workflow.
    Replace the pseudo-code with your actual LangGraph setup.
    """

    # Define your agents and roles
    agents = ["fraud_detector", "compliance_checker", "router"]
    role_specs = [
        AgentSpec("fraud_detector", "Fraud Detection",
                  "Analyzes transactions for fraud signals",
                  expected_actions=["tool_call", "reasoning", "message"]),
        AgentSpec("compliance_checker", "Compliance",
                  "Checks regulatory requirements",
                  expected_actions=["tool_call", "reasoning", "message"]),
        AgentSpec("router", "Payment Router",
                  "Routes payments to optimal rail",
                  expected_actions=["tool_call", "reasoning", "output"]),
    ]

    # Create evaluator
    evaluator = MASEvaluator(
        agents=agents,
        role_specs=role_specs,
        config=MetricConfig(redundancy_threshold=0.85),
    )

    # Run multiple trials
    scenarios = [
        {"id": "test_001", "amount": 500, "type": "ach"},
        {"id": "test_002", "amount": 15000, "type": "wire"},
    ]

    for scenario in scenarios:
        # Create callback
        callback = MASEVTraceCallback(agents=agents)

        # --- Replace this block with your actual LangGraph execution ---
        # graph = create_payment_graph(model="gpt-4o")
        # result = graph.invoke(
        #     {"transaction": scenario},
        #     config={"callbacks": [callback]}
        # )

        # Simulated execution for demo:
        callback.on_node_start("fraud_detector", scenario)
        callback.on_tool_call("fraud_detector", "check_amount", {"amount": scenario["amount"]}, "CLEAR")
        callback.on_message("fraud_detector", "compliance_checker", f"Fraud check clear for ${scenario['amount']}")
        callback.on_node_end("fraud_detector", {"fraud_status": "clear"})

        callback.on_node_start("compliance_checker", {"fraud_status": "clear"})
        callback.on_tool_call("compliance_checker", "check_aml", {"amount": scenario["amount"]}, "PASS")
        callback.on_message("compliance_checker", "router", "Compliance approved")
        callback.on_node_end("compliance_checker", {"compliance_status": "approved"})

        callback.on_node_start("router", {"compliance_status": "approved"})
        callback.on_tool_call("router", "select_rail", {"type": scenario["type"]}, "ACH_STANDARD")
        callback.on_node_end("router", {"route": "ach_standard"})
        # --- End simulated block ---

        # Convert to trace and ingest
        trace = callback.to_trace(
            task_description=f"Process {scenario['type']} payment ${scenario['amount']}",
            task_success=True,
        )
        evaluator.ingest(trace)

    # Evaluate
    report = evaluator.evaluate()
    print(report.summary())

    return report


if __name__ == "__main__":
    example_usage()
