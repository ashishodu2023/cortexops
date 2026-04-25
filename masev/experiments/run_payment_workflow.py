"""
experiments/run_payment_workflow.py

Experiment runner for the Payment Workflow benchmark.
Instruments a 3-agent LangGraph payment processing pipeline
(fraud_detector, compliance_checker, router) and captures
MASEV-compatible traces.

Usage:
    # Set OPENAI_API_KEY before running
    python -m experiments.run_payment_workflow \
        --model gpt-4o \
        --trials 50 \
        --topology star \
        --output results/payment_gpt4o_star.json

Requirements:
    pip install langgraph langchain-openai masev
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from pathlib import Path
from typing import Any

# Add parent to path for local dev
sys.path.insert(0, str(Path(__file__).parent.parent))

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

# ---------------------------------------------------------------------------
# Golden dataset: payment scenarios with expected outcomes
# ---------------------------------------------------------------------------

PAYMENT_SCENARIOS = [
    {
        "id": "pay_001",
        "description": "Domestic ACH transfer $500 to known payee",
        "amount": 500,
        "currency": "USD",
        "type": "ach",
        "destination": "domestic",
        "payee_known": True,
        "expected_fraud": False,
        "expected_compliance": "approved",
        "expected_route": "ach_standard",
    },
    {
        "id": "pay_002",
        "description": "International wire $15,000 to new payee in high-risk country",
        "amount": 15000,
        "currency": "USD",
        "type": "wire",
        "destination": "international_high_risk",
        "payee_known": False,
        "expected_fraud": True,
        "expected_compliance": "review",
        "expected_route": "wire_enhanced_dd",
    },
    {
        "id": "pay_003",
        "description": "Recurring payment $99.99 subscription renewal",
        "amount": 99.99,
        "currency": "USD",
        "type": "card",
        "destination": "domestic",
        "payee_known": True,
        "expected_fraud": False,
        "expected_compliance": "approved",
        "expected_route": "card_network",
    },
    {
        "id": "pay_004",
        "description": "Large corporate wire $250,000 cross-border",
        "amount": 250000,
        "currency": "USD",
        "type": "wire",
        "destination": "international",
        "payee_known": True,
        "expected_fraud": False,
        "expected_compliance": "review",
        "expected_route": "wire_correspondent",
    },
    {
        "id": "pay_005",
        "description": "Rapid successive small transfers totaling $9,500 (structuring pattern)",
        "amount": 9500,
        "currency": "USD",
        "type": "ach",
        "destination": "domestic",
        "payee_known": False,
        "expected_fraud": True,
        "expected_compliance": "blocked",
        "expected_route": "hold",
    },
    {
        "id": "pay_006",
        "description": "Peer-to-peer $50 to friend",
        "amount": 50,
        "currency": "USD",
        "type": "p2p",
        "destination": "domestic",
        "payee_known": True,
        "expected_fraud": False,
        "expected_compliance": "approved",
        "expected_route": "instant",
    },
    {
        "id": "pay_007",
        "description": "Crypto withdrawal $5,000 to external wallet",
        "amount": 5000,
        "currency": "USD",
        "type": "crypto",
        "destination": "external",
        "payee_known": False,
        "expected_fraud": False,
        "expected_compliance": "review",
        "expected_route": "crypto_compliance",
    },
    {
        "id": "pay_008",
        "description": "Refund $1,200 disputed transaction",
        "amount": 1200,
        "currency": "USD",
        "type": "refund",
        "destination": "domestic",
        "payee_known": True,
        "expected_fraud": False,
        "expected_compliance": "approved",
        "expected_route": "refund_original_method",
    },
    {
        "id": "pay_009",
        "description": "Velocity anomaly: 20 transactions in 5 minutes from same account",
        "amount": 200,
        "currency": "USD",
        "type": "card",
        "destination": "domestic",
        "payee_known": False,
        "expected_fraud": True,
        "expected_compliance": "blocked",
        "expected_route": "hold",
    },
    {
        "id": "pay_010",
        "description": "Cross-border payroll batch $45,000 to 30 employees",
        "amount": 45000,
        "currency": "USD",
        "type": "batch_ach",
        "destination": "international",
        "payee_known": True,
        "expected_fraud": False,
        "expected_compliance": "approved",
        "expected_route": "batch_international",
    },
]

# ---------------------------------------------------------------------------
# Role specifications for the 3 agents
# ---------------------------------------------------------------------------

ROLE_SPECS = [
    AgentSpec(
        agent_id="fraud_detector",
        role_name="Fraud Detection Agent",
        description="Analyzes transaction patterns, velocity, amount, destination risk to flag potential fraud.",
        expected_actions=["tool_call", "reasoning", "message"],
        expected_tools=["check_velocity", "check_amount_threshold", "check_destination_risk", "check_payee_history"],
    ),
    AgentSpec(
        agent_id="compliance_checker",
        role_name="Compliance Agent",
        description="Checks regulatory requirements, AML/KYC status, sanctions screening, reporting thresholds.",
        expected_actions=["tool_call", "reasoning", "message"],
        expected_tools=["check_aml", "check_sanctions", "check_reporting_threshold", "check_kyc_status"],
    ),
    AgentSpec(
        agent_id="router",
        role_name="Payment Router Agent",
        description="Determines optimal payment rail based on fraud/compliance signals, amount, speed, and cost.",
        expected_actions=["tool_call", "reasoning", "output"],
        expected_tools=["select_rail", "calculate_fees", "check_rail_availability"],
    ),
]

AGENT_IDS = [s.agent_id for s in ROLE_SPECS]


# ---------------------------------------------------------------------------
# Simulated agent execution (replace with real LangGraph calls)
# ---------------------------------------------------------------------------

def simulate_agent_run(scenario: dict, topology: str = "star") -> Trace:
    """
    Simulate a 3-agent payment workflow and return a MASEV trace.

    Replace this function with actual LangGraph execution when ready.
    The trace format stays the same -- just swap the internals.
    """
    trace = Trace(
        agents=AGENT_IDS,
        task_description=scenario["description"],
        metadata={"scenario_id": scenario["id"], "topology": topology},
    )

    t0 = time.time()
    steps = []

    # Step 1: Fraud detector analyzes the transaction
    step1 = TraceStep(step_id=0, timestamp=t0)
    fraud_result = "flagged" if scenario["expected_fraud"] else "clear"
    step1.actions.append(Action(
        agent_id="fraud_detector",
        action_type=ActionType.TOOL_CALL,
        content=f"Checking transaction: {scenario['type']} ${scenario['amount']} to {scenario['destination']}",
        tool_name="check_amount_threshold",
        tool_args={"amount": scenario["amount"]},
        timestamp=t0,
    ))
    step1.actions.append(Action(
        agent_id="fraud_detector",
        action_type=ActionType.REASONING,
        content=f"Transaction analysis: amount=${scenario['amount']}, type={scenario['type']}, "
                f"destination={scenario['destination']}, payee_known={scenario['payee_known']}. "
                f"Risk assessment: {fraud_result}",
        timestamp=t0 + 0.5,
    ))

    # In star topology, fraud detector also messages compliance
    if topology in ("star", "dag"):
        step1.messages.append(Message(
            sender="fraud_detector",
            receiver="compliance_checker",
            content=f"Fraud screening result: {fraud_result}. "
                    f"Amount: ${scenario['amount']}, Type: {scenario['type']}, "
                    f"Destination: {scenario['destination']}",
            timestamp=t0 + 0.6,
        ))
    steps.append(step1)

    # Step 2: Compliance checker reviews
    step2 = TraceStep(step_id=1, timestamp=t0 + 1.0)
    compliance_result = scenario["expected_compliance"]
    step2.actions.append(Action(
        agent_id="compliance_checker",
        action_type=ActionType.TOOL_CALL,
        content=f"Running AML/sanctions check for {scenario['type']} transaction",
        tool_name="check_aml",
        tool_args={"amount": scenario["amount"], "destination": scenario["destination"]},
        timestamp=t0 + 1.0,
    ))
    step2.actions.append(Action(
        agent_id="compliance_checker",
        action_type=ActionType.REASONING,
        content=f"Compliance review: {compliance_result}. "
                f"AML threshold: {'exceeded' if scenario['amount'] > 10000 else 'within limits'}. "
                f"Sanctions: clear. KYC: {'verified' if scenario['payee_known'] else 'pending'}",
        timestamp=t0 + 1.5,
    ))

    # Compliance messages router with combined signals
    step2.messages.append(Message(
        sender="compliance_checker",
        receiver="router",
        content=f"Compliance: {compliance_result}. Fraud: {fraud_result}. "
                f"Proceed with {'standard' if compliance_result == 'approved' else 'enhanced'} routing.",
        timestamp=t0 + 1.6,
    ))

    # In graph topology, also message back to fraud detector
    if topology == "graph":
        step2.messages.append(Message(
            sender="compliance_checker",
            receiver="fraud_detector",
            content=f"FYI: compliance status is {compliance_result}",
            timestamp=t0 + 1.7,
        ))

    # Simulate some redundancy in graph topology
    if topology == "graph":
        step2.actions.append(Action(
            agent_id="fraud_detector",
            action_type=ActionType.REASONING,
            content=f"Re-checking transaction risk after compliance feedback: {fraud_result}",
            timestamp=t0 + 1.8,
        ))
    steps.append(step2)

    # Step 3: Router makes final decision
    step3 = TraceStep(step_id=2, timestamp=t0 + 2.0)
    route = scenario["expected_route"]
    step3.actions.append(Action(
        agent_id="router",
        action_type=ActionType.TOOL_CALL,
        content=f"Selecting payment rail for {scenario['type']} transaction",
        tool_name="select_rail",
        tool_args={"type": scenario["type"], "amount": scenario["amount"], "compliance": compliance_result},
        timestamp=t0 + 2.0,
    ))
    step3.actions.append(Action(
        agent_id="router",
        action_type=ActionType.OUTPUT,
        content=f"Payment routed via {route}. Status: {'processing' if compliance_result != 'blocked' else 'held'}",
        timestamp=t0 + 2.5,
    ))

    # Router confirms back in star topology
    if topology == "star":
        step3.messages.append(Message(
            sender="router",
            receiver="fraud_detector",
            content=f"Payment processed via {route}",
            timestamp=t0 + 2.6,
        ))
        step3.messages.append(Message(
            sender="router",
            receiver="compliance_checker",
            content=f"Payment processed via {route}",
            timestamp=t0 + 2.7,
        ))
    steps.append(step3)

    # Add some noise / variation
    noise = random.random()
    if noise > 0.85:
        # Simulate an extra deliberation step (adds realism)
        step4 = TraceStep(step_id=3, timestamp=t0 + 3.0)
        step4.actions.append(Action(
            agent_id="compliance_checker",
            action_type=ActionType.REASONING,
            content="Double-checking reporting requirements for this transaction type",
            timestamp=t0 + 3.0,
        ))
        step4.messages.append(Message(
            sender="compliance_checker",
            receiver="router",
            content="Confirmed: no additional reporting needed",
            timestamp=t0 + 3.1,
        ))
        steps.append(step4)

    trace.steps = steps

    # Determine task success (simulate ~94% success rate with some failures)
    if compliance_result == "blocked" and route == "hold":
        trace.task_success = True
    elif compliance_result != "blocked" and route != "hold":
        trace.task_success = random.random() > 0.06  # ~94% success
    else:
        trace.task_success = random.random() > 0.3

    trace.task_score = 1.0 if trace.task_success else 0.0

    return trace


# ---------------------------------------------------------------------------
# LangGraph integration (scaffold -- fill in with your actual agent)
# ---------------------------------------------------------------------------

def run_langgraph_payment_agent(scenario: dict, model: str, topology: str) -> Trace:
    """
    Run the actual LangGraph payments agent and capture a MASEV trace.

    TODO: Replace the simulation below with your real LangGraph workflow.
    Wrap each agent node's execution to emit Action and Message objects.
    """
    # For now, delegate to simulation
    # When ready, replace with:
    #
    #   from your_langgraph_app import create_payment_graph
    #   graph = create_payment_graph(model=model, topology=topology)
    #   result = graph.invoke({"transaction": scenario})
    #   trace = convert_langgraph_result_to_trace(result)
    #   return trace

    return simulate_agent_run(scenario, topology)


# ---------------------------------------------------------------------------
# Experiment runner
# ---------------------------------------------------------------------------

def run_experiment(
    model: str = "gpt-4o",
    topology: str = "star",
    n_trials: int = 50,
    output_path: str | None = None,
) -> dict:
    """
    Run the payment workflow experiment and evaluate with MASEV.

    Args:
        model: Foundation model name
        topology: Coordination protocol (star, graph, tree)
        n_trials: Number of trials to run
        output_path: Optional path to save results JSON

    Returns:
        Dict with evaluation report and per-trial data
    """
    print(f"Running experiment: model={model}, topology={topology}, trials={n_trials}")
    print("=" * 60)

    evaluator = MASEvaluator(
        agents=AGENT_IDS,
        role_specs=ROLE_SPECS,
        config=MetricConfig(),
    )

    trial_results = []

    for trial in range(n_trials):
        # Pick a random scenario (or cycle through)
        scenario = PAYMENT_SCENARIOS[trial % len(PAYMENT_SCENARIOS)]

        # Run the agent
        trace = run_langgraph_payment_agent(scenario, model, topology)

        # Evaluate this single trace
        single_report = evaluator.evaluate_single(trace)

        # Store per-trial data
        trial_results.append({
            "trial": trial,
            "scenario_id": scenario["id"],
            "task_success": trace.task_success,
            "coordination": single_report.coordination,
            "communication": single_report.communication,
            "role_adherence": single_report.role_adherence,
            "n_actions": trace.total_actions,
            "n_messages": trace.total_messages,
        })

        # Ingest into batch evaluator
        evaluator.ingest(trace)

        if (trial + 1) % 10 == 0:
            print(f"  Completed {trial + 1}/{n_trials} trials")

    # Final batch evaluation
    report = evaluator.evaluate()
    print()
    print(report.summary())

    # Build output
    output = {
        "experiment": {
            "model": model,
            "topology": topology,
            "n_trials": n_trials,
            "benchmark": "payment_workflow",
        },
        "report": {
            "coordination": report.coordination,
            "communication": report.communication,
            "role_adherence": report.role_adherence,
            "task_success_rate": report.task_success_rate,
            "sub_metrics": {
                "coordination_entropy": report.coordination_entropy,
                "redundancy_ratio": report.redundancy_ratio,
                "parallelism_index": report.parallelism_index,
                "message_utility_ratio": report.message_utility_ratio,
                "information_density": report.information_density,
                "communication_overhead": report.communication_overhead,
                "behavioral_divergence": report.behavioral_divergence,
                "role_drift_rate": report.role_drift_rate,
            },
            "emergent_behaviors": report.emergent_behaviors.as_dict(),
        },
        "trials": trial_results,
    }

    if output_path:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w") as f:
            json.dump(output, f, indent=2)
        print(f"\nResults saved to {output_path}")

    return output


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="MASEV Payment Workflow Experiment")
    parser.add_argument("--model", default="gpt-4o", help="Model name")
    parser.add_argument("--topology", default="star", choices=["star", "graph", "tree"])
    parser.add_argument("--trials", type=int, default=50, help="Number of trials")
    parser.add_argument("--output", default=None, help="Output JSON path")
    args = parser.parse_args()

    if args.output is None:
        args.output = f"results/payment_{args.model.replace('-', '')}_{args.topology}.json"

    run_experiment(
        model=args.model,
        topology=args.topology,
        n_trials=args.trials,
        output_path=args.output,
    )


if __name__ == "__main__":
    main()
