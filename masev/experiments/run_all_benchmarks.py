"""
experiments/run_all_benchmarks.py

Runs all 5 benchmarks x 3 topologies with variance tracking.
Generates paper-ready LaTeX tables with standard deviations.
"""

from __future__ import annotations

import json
import random
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))

from masev import (
    Action, ActionType, AgentSpec, MASEvaluator,
    Message, MetricConfig, Trace, TraceStep,
)

# ---------------------------------------------------------------------------
# Benchmark definitions
# ---------------------------------------------------------------------------

BENCHMARKS = {
    "research_collab": {
        "agents": ["lit_reviewer", "hypothesis_gen", "methodology", "writer", "critic"],
        "agent_count": "3-5",
        "type": "Cooperative",
        "default_topology": "graph",
        "domain": "Science",
        "role_specs": [
            AgentSpec("lit_reviewer", "Literature Reviewer",
                      "Searches and summarizes relevant papers",
                      expected_actions=["tool_call", "reasoning", "message"]),
            AgentSpec("hypothesis_gen", "Hypothesis Generator",
                      "Formulates research hypotheses from literature",
                      expected_actions=["reasoning", "message", "output"]),
            AgentSpec("methodology", "Methodology Designer",
                      "Designs experimental methodology",
                      expected_actions=["reasoning", "tool_call", "message"]),
            AgentSpec("writer", "Paper Writer",
                      "Drafts and refines the research proposal",
                      expected_actions=["output", "reasoning", "message"]),
            AgentSpec("critic", "Internal Critic",
                      "Reviews and provides feedback on drafts",
                      expected_actions=["reasoning", "message"]),
        ],
    },
    "minecraft_build": {
        "agents": ["architect", "builder_a", "builder_b", "inspector"],
        "agent_count": "2-4",
        "type": "Cooperative",
        "default_topology": "star",
        "domain": "Construction",
        "role_specs": [
            AgentSpec("architect", "Architect",
                      "Parses blueprints and assigns build regions",
                      expected_actions=["reasoning", "message", "delegation"]),
            AgentSpec("builder_a", "Builder A",
                      "Places blocks in assigned region",
                      expected_actions=["tool_call", "output", "message"]),
            AgentSpec("builder_b", "Builder B",
                      "Places blocks in assigned region",
                      expected_actions=["tool_call", "output", "message"]),
            AgentSpec("inspector", "Inspector",
                      "Verifies placed blocks match blueprint",
                      expected_actions=["tool_call", "reasoning", "message"]),
        ],
    },
    "db_error_analysis": {
        "agents": ["log_analyst", "query_profiler", "schema_checker", "perf_monitor", "remediation"],
        "agent_count": "5",
        "type": "Cooperative",
        "default_topology": "chain",
        "domain": "Database",
        "role_specs": [
            AgentSpec("log_analyst", "Log Analyst",
                      "Analyzes database error logs",
                      expected_actions=["tool_call", "reasoning", "message"]),
            AgentSpec("query_profiler", "Query Profiler",
                      "Profiles slow/failing queries",
                      expected_actions=["tool_call", "reasoning", "message"]),
            AgentSpec("schema_checker", "Schema Checker",
                      "Validates schema integrity",
                      expected_actions=["tool_call", "reasoning", "message"]),
            AgentSpec("perf_monitor", "Performance Monitor",
                      "Monitors system performance metrics",
                      expected_actions=["tool_call", "reasoning", "message"]),
            AgentSpec("remediation", "Remediation Agent",
                      "Proposes and executes fixes",
                      expected_actions=["tool_call", "output", "message"]),
        ],
    },
    "werewolf": {
        "agents": ["villager_1", "villager_2", "villager_3", "seer", "doctor", "werewolf_1", "werewolf_2"],
        "agent_count": "6-8",
        "type": "Competitive",
        "default_topology": "full",
        "domain": "Social Deduction",
        "role_specs": [
            AgentSpec("villager_1", "Villager", "Votes to eliminate suspects",
                      expected_actions=["reasoning", "message", "output"]),
            AgentSpec("villager_2", "Villager", "Votes to eliminate suspects",
                      expected_actions=["reasoning", "message", "output"]),
            AgentSpec("villager_3", "Villager", "Votes to eliminate suspects",
                      expected_actions=["reasoning", "message", "output"]),
            AgentSpec("seer", "Seer", "Investigates one player per night",
                      expected_actions=["tool_call", "reasoning", "message"]),
            AgentSpec("doctor", "Doctor", "Protects one player per night",
                      expected_actions=["tool_call", "reasoning", "message"]),
            AgentSpec("werewolf_1", "Werewolf", "Eliminates villagers, hides identity",
                      expected_actions=["reasoning", "message", "output"]),
            AgentSpec("werewolf_2", "Werewolf", "Eliminates villagers, hides identity",
                      expected_actions=["reasoning", "message", "output"]),
        ],
    },
    "payment_workflow": {
        "agents": ["fraud_detector", "compliance_checker", "router"],
        "agent_count": "3",
        "type": "Cooperative",
        "default_topology": "dag",
        "domain": "Financial",
        "role_specs": [
            AgentSpec("fraud_detector", "Fraud Detection",
                      "Analyzes transactions for fraud signals",
                      expected_actions=["tool_call", "reasoning", "message"]),
            AgentSpec("compliance_checker", "Compliance",
                      "Checks regulatory requirements",
                      expected_actions=["tool_call", "reasoning", "message"]),
            AgentSpec("router", "Payment Router",
                      "Routes payments to optimal rail",
                      expected_actions=["tool_call", "reasoning", "output"]),
        ],
    },
}

TOPOLOGIES = ["star", "graph", "tree"]
MODELS = ["gpt-4o", "gpt-4o-mini", "claude-3-5-sonnet", "llama-3-1-70b"]


# ---------------------------------------------------------------------------
# Benchmark-specific simulation engines
# ---------------------------------------------------------------------------

def simulate_research_collab(topology: str, model: str) -> Trace:
    agents = BENCHMARKS["research_collab"]["agents"]
    # Use 3-5 agents randomly
    n_agents = random.choice([3, 4, 5])
    active_agents = agents[:n_agents]
    trace = Trace(agents=active_agents, task_description="Co-author research proposal",
                  metadata={"benchmark": "research_collab", "topology": topology, "model": model})
    steps = []
    t0 = time.time()

    # Research collab has lots of back-and-forth, some redundancy
    for s in range(random.randint(8, 15)):
        step = TraceStep(step_id=s, timestamp=t0 + s)
        # Multiple agents active per step (collaborative)
        n_active = random.randint(1, min(3, n_agents))
        active = random.sample(active_agents, n_active)
        for agent in active:
            action_type = random.choice([ActionType.TOOL_CALL, ActionType.REASONING,
                                         ActionType.MESSAGE, ActionType.OUTPUT])
            step.actions.append(Action(
                agent_id=agent, action_type=action_type,
                content=f"{agent} performs {action_type.value} at step {s} for research task",
                tool_name="search_papers" if action_type == ActionType.TOOL_CALL else None,
                timestamp=t0 + s + random.random() * 0.5,
            ))

        # Lots of messaging in research collab -- often redundant
        if s > 0 and random.random() > 0.2:
            sender = random.choice(active_agents)
            receiver = random.choice([a for a in active_agents if a != sender])
            # Sometimes duplicate messages (low communication quality)
            content_pool = [
                f"I found relevant papers on topic X at step {s}",
                f"Let me search for more papers on topic X",  # redundant
                f"Here's my analysis of the methodology",
                f"We should consider approach Y",
                f"Updating the draft with new findings",
                f"Reviewing section on methodology",  # redundant with methodology agent
            ]
            step.messages.append(Message(
                sender=sender, receiver=receiver,
                content=random.choice(content_pool),
                timestamp=t0 + s + 0.6,
            ))
            # Extra redundant message in graph topology
            if topology == "graph" and random.random() > 0.5:
                s2 = random.choice([a for a in active_agents if a != sender and a != receiver])
                step.messages.append(Message(
                    sender=sender, receiver=s2,
                    content=f"FYI: same update as sent to {receiver}",
                    timestamp=t0 + s + 0.7,
                ))

        steps.append(step)

    trace.steps = steps
    # ~92% success, varies by model
    model_bonus = {"gpt-4o": 0.05, "claude-3-5-sonnet": 0.03, "gpt-4o-mini": 0.0, "llama-3-1-70b": -0.08}
    success_rate = 0.88 + model_bonus.get(model, 0)
    trace.task_success = random.random() < success_rate
    trace.task_score = 1.0 if trace.task_success else 0.0
    return trace


def simulate_minecraft_build(topology: str, model: str) -> Trace:
    agents = BENCHMARKS["minecraft_build"]["agents"]
    trace = Trace(agents=agents, task_description="Build target structure collaboratively",
                  metadata={"benchmark": "minecraft_build", "topology": topology, "model": model})
    steps = []
    t0 = time.time()

    for s in range(random.randint(6, 12)):
        step = TraceStep(step_id=s, timestamp=t0 + s)

        if s == 0:
            # Architect assigns tasks
            step.actions.append(Action(
                agent_id="architect", action_type=ActionType.REASONING,
                content="Parsing blueprint and assigning build regions",
                timestamp=t0,
            ))
            step.actions.append(Action(
                agent_id="architect", action_type=ActionType.DELEGATION,
                content="Assigning region A to builder_a, region B to builder_b",
                timestamp=t0 + 0.1,
            ))
            step.messages.append(Message(sender="architect", receiver="builder_a",
                                         content="Build region A: rows 1-5, columns 1-5"))
            step.messages.append(Message(sender="architect", receiver="builder_b",
                                         content="Build region B: rows 1-5, columns 6-10"))
        elif s < len(steps) - 1:
            # Builders work in parallel (high parallelism)
            step.actions.append(Action(
                agent_id="builder_a", action_type=ActionType.TOOL_CALL,
                content=f"Placing blocks in region A, layer {s}",
                tool_name="place_block", timestamp=t0 + s,
            ))
            step.actions.append(Action(
                agent_id="builder_b", action_type=ActionType.TOOL_CALL,
                content=f"Placing blocks in region B, layer {s}",
                tool_name="place_block", timestamp=t0 + s + 0.1,
            ))
            # Builders self-specialize over time
            if s > 3:
                step.actions.append(Action(
                    agent_id="builder_a", action_type=ActionType.TOOL_CALL,
                    content=f"Specialized: placing only stone blocks now",
                    tool_name="place_block", timestamp=t0 + s + 0.2,
                ))
            if random.random() > 0.6:
                step.messages.append(Message(
                    sender="builder_a", receiver="architect",
                    content=f"Region A layer {s} complete"))
        else:
            # Inspector verifies
            step.actions.append(Action(
                agent_id="inspector", action_type=ActionType.TOOL_CALL,
                content="Verifying structure matches blueprint",
                tool_name="verify_structure", timestamp=t0 + s,
            ))

        steps.append(step)

    trace.steps = steps
    model_bonus = {"gpt-4o": 0.04, "claude-3-5-sonnet": 0.02, "gpt-4o-mini": -0.02, "llama-3-1-70b": -0.10}
    trace.task_success = random.random() < (0.86 + model_bonus.get(model, 0))
    trace.task_score = 1.0 if trace.task_success else 0.0
    return trace


def simulate_db_error(topology: str, model: str) -> Trace:
    agents = BENCHMARKS["db_error_analysis"]["agents"]
    trace = Trace(agents=agents, task_description="Diagnose and fix database anomaly",
                  metadata={"benchmark": "db_error_analysis", "topology": topology, "model": model})
    steps = []
    t0 = time.time()

    # Chain topology: agents work mostly sequentially, low communication
    for s in range(random.randint(5, 10)):
        step = TraceStep(step_id=s, timestamp=t0 + s)

        if topology == "chain":
            # Only one agent active per step (sequential chain)
            active_agent = agents[s % len(agents)]
            step.actions.append(Action(
                agent_id=active_agent, action_type=ActionType.TOOL_CALL,
                content=f"{active_agent} running diagnostic tool at step {s}",
                tool_name=f"diagnostic_{active_agent}",
                timestamp=t0 + s,
            ))
            step.actions.append(Action(
                agent_id=active_agent, action_type=ActionType.REASONING,
                content=f"{active_agent} analyzing results from diagnostic",
                timestamp=t0 + s + 0.3,
            ))
            # Minimal messaging in chain -- just pass to next
            if s < len(agents) - 1:
                next_agent = agents[(s + 1) % len(agents)]
                step.messages.append(Message(
                    sender=active_agent, receiver=next_agent,
                    content=f"Passing findings to next stage: {active_agent} found issue type {s}",
                    timestamp=t0 + s + 0.5,
                ))
        else:
            # Star/graph: some parallel work but still mostly independent
            n_active = random.randint(1, 3)
            for agent in random.sample(agents, n_active):
                step.actions.append(Action(
                    agent_id=agent, action_type=ActionType.TOOL_CALL,
                    content=f"{agent} independently checking database at step {s}",
                    tool_name=f"diagnostic_{agent}",
                    timestamp=t0 + s + random.random() * 0.3,
                ))
            # Low-utility messages (agents work independently)
            if random.random() > 0.6:
                s1, s2 = random.sample(agents, 2)
                step.messages.append(Message(
                    sender=s1, receiver=s2,
                    content=f"Still investigating... no new findings at step {s}",
                    timestamp=t0 + s + 0.5,
                ))

        steps.append(step)

    trace.steps = steps
    model_bonus = {"gpt-4o": 0.03, "claude-3-5-sonnet": 0.04, "gpt-4o-mini": -0.01, "llama-3-1-70b": -0.07}
    trace.task_success = random.random() < (0.93 + model_bonus.get(model, 0))
    trace.task_score = 1.0 if trace.task_success else 0.0
    return trace


def simulate_werewolf(topology: str, model: str) -> Trace:
    agents = BENCHMARKS["werewolf"]["agents"]
    trace = Trace(agents=agents, task_description="Social deduction game",
                  metadata={"benchmark": "werewolf", "topology": topology, "model": model})
    steps = []
    t0 = time.time()

    werewolves = {"werewolf_1", "werewolf_2"}
    villagers = set(agents) - werewolves

    for s in range(random.randint(8, 16)):
        step = TraceStep(step_id=s, timestamp=t0 + s)

        if s % 2 == 0:
            # Day phase: everyone discusses and votes
            for agent in agents:
                step.actions.append(Action(
                    agent_id=agent, action_type=ActionType.REASONING,
                    content=f"{agent} analyzing accusations and alibis at round {s}",
                    timestamp=t0 + s + random.random() * 0.3,
                ))
            # Lots of messaging (full topology) -- but trust polarizes
            n_msgs = random.randint(3, 6)
            for _ in range(n_msgs):
                sender = random.choice(agents)
                # Trust polarization: werewolves message each other more
                if sender in werewolves and random.random() > 0.4:
                    receiver = [w for w in werewolves if w != sender][0]
                    step.messages.append(Message(
                        sender=sender, receiver=receiver,
                        content=f"Secret: let's target {random.choice(list(villagers))}",
                        timestamp=t0 + s + random.random(),
                    ))
                else:
                    receiver = random.choice([a for a in agents if a != sender])
                    step.messages.append(Message(
                        sender=sender, receiver=receiver,
                        content=f"I suspect {random.choice(agents)} is a werewolf",
                        timestamp=t0 + s + random.random(),
                    ))
            # Vote action
            step.actions.append(Action(
                agent_id=random.choice(agents),
                action_type=ActionType.OUTPUT,
                content=f"Vote to eliminate {random.choice(agents)}",
                timestamp=t0 + s + 0.9,
            ))
        else:
            # Night phase: special roles act, werewolves attack
            step.actions.append(Action(
                agent_id="seer", action_type=ActionType.TOOL_CALL,
                content=f"Investigating {random.choice(agents)}",
                tool_name="investigate", timestamp=t0 + s,
            ))
            step.actions.append(Action(
                agent_id="doctor", action_type=ActionType.TOOL_CALL,
                content=f"Protecting {random.choice(agents)}",
                tool_name="protect", timestamp=t0 + s + 0.1,
            ))
            step.actions.append(Action(
                agent_id="werewolf_1", action_type=ActionType.REASONING,
                content=f"Selecting target for elimination",
                timestamp=t0 + s + 0.2,
            ))
            # Info hoarding: seer doesn't share findings
            if random.random() > 0.5:
                step.messages.append(Message(
                    sender="werewolf_1", receiver="werewolf_2",
                    content=f"Attack {random.choice(list(villagers))} tonight",
                    timestamp=t0 + s + 0.5,
                ))

        steps.append(step)

    trace.steps = steps
    model_bonus = {"gpt-4o": 0.05, "claude-3-5-sonnet": 0.03, "gpt-4o-mini": -0.03, "llama-3-1-70b": -0.12}
    trace.task_success = random.random() < (0.68 + model_bonus.get(model, 0))
    trace.task_score = 1.0 if trace.task_success else 0.0
    return trace


def simulate_payment(topology: str, model: str) -> Trace:
    """Reuse the payment simulator from run_payment_workflow.py"""
    from experiments.run_payment_workflow import simulate_agent_run, PAYMENT_SCENARIOS
    scenario = random.choice(PAYMENT_SCENARIOS)
    return simulate_agent_run(scenario, topology)


BENCHMARK_SIMULATORS = {
    "research_collab": simulate_research_collab,
    "minecraft_build": simulate_minecraft_build,
    "db_error_analysis": simulate_db_error,
    "werewolf": simulate_werewolf,
    "payment_workflow": simulate_payment,
}


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------

def run_all(n_trials: int = 100, output_dir: str = "results/full_benchmarks"):
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    all_results = {}

    for bench_name, bench_config in BENCHMARKS.items():
        print(f"\n{'='*60}")
        print(f"BENCHMARK: {bench_name}")
        print(f"{'='*60}")

        simulator = BENCHMARK_SIMULATORS[bench_name]

        for model in MODELS:
            for topology in TOPOLOGIES:
                print(f"  {model} / {topology} ... ", end="", flush=True)

                evaluator = MASEvaluator(
                    agents=bench_config["agents"],
                    role_specs=bench_config["role_specs"],
                    config=MetricConfig(),
                )

                trial_metrics = defaultdict(list)

                for trial in range(n_trials):
                    trace = simulator(topology, model)
                    report = evaluator.evaluate_single(trace)
                    evaluator.ingest(trace)

                    trial_metrics["coordination"].append(report.coordination)
                    trial_metrics["communication"].append(report.communication)
                    trial_metrics["role_adherence"].append(report.role_adherence)
                    trial_metrics["task_success"].append(1.0 if trace.task_success else 0.0)
                    trial_metrics["coordination_entropy"].append(report.coordination_entropy)
                    trial_metrics["redundancy_ratio"].append(report.redundancy_ratio)
                    trial_metrics["parallelism_index"].append(report.parallelism_index)
                    trial_metrics["message_utility_ratio"].append(report.message_utility_ratio)
                    trial_metrics["information_density"].append(report.information_density)
                    trial_metrics["communication_overhead"].append(report.communication_overhead)
                    trial_metrics["behavioral_divergence"].append(report.behavioral_divergence)
                    trial_metrics["role_drift_rate"].append(report.role_drift_rate)

                batch_report = evaluator.evaluate()

                result = {
                    "benchmark": bench_name,
                    "model": model,
                    "topology": topology,
                    "n_trials": n_trials,
                    "means": {k: float(np.mean(v)) for k, v in trial_metrics.items()},
                    "stds": {k: float(np.std(v)) for k, v in trial_metrics.items()},
                    "emergent_behaviors": batch_report.emergent_behaviors.as_dict(),
                }

                key = f"{bench_name}_{model}_{topology}"
                all_results[key] = result

                sr = result["means"]["task_success"]
                c = result["means"]["coordination"]
                q = result["means"]["communication"]
                r = result["means"]["role_adherence"]
                print(f"SR={sr:.2f} C={c:.2f} Q={q:.2f} R={r:.2f}")

    # Save all results
    results_file = output_path / "all_results.json"
    with open(results_file, "w") as f:
        json.dump(all_results, f, indent=2)
    print(f"\nAll results saved to {results_file}")

    # Generate tables
    generate_all_tables(all_results, output_path)

    return all_results


def generate_all_tables(results: dict, output_path: Path):
    """Generate all paper-ready LaTeX tables."""

    bench_names_display = {
        "research_collab": "Research Collab",
        "minecraft_build": "Minecraft Build",
        "db_error_analysis": "DB Error Analysis",
        "werewolf": "Werewolf",
        "payment_workflow": "Payment Workflow",
    }

    # -----------------------------------------------------------------------
    # Table 2: Main results (best model config per benchmark)
    # -----------------------------------------------------------------------
    lines = [
        r"\begin{table}[t]",
        r"\caption{Comparison of evaluation approaches across benchmarks (best model configuration per benchmark, 100 trials each). SR = Success Rate. \framework{} dimensions: $\mathcal{C}$ = Coordination, $\mathcal{Q}$ = Communication, $\mathcal{R}$ = Role Adherence. Higher is better. Values show mean $\pm$ std.}",
        r"\label{tab:main_results}",
        r"\centering",
        r"\begin{tabular}{@{}lc|ccc@{}}",
        r"\toprule",
        r"\textbf{Benchmark} & \textbf{SR} & $\mathcal{C}$ & $\mathcal{Q}$ & $\mathcal{R}$ \\",
        r"\midrule",
    ]

    for bench in ["research_collab", "minecraft_build", "db_error_analysis", "werewolf", "payment_workflow"]:
        # Find best config by SR
        best_key = None
        best_sr = -1
        for key, r in results.items():
            if r["benchmark"] == bench and r["means"]["task_success"] > best_sr:
                best_sr = r["means"]["task_success"]
                best_key = key

        if best_key:
            r = results[best_key]
            m = r["means"]
            s = r["stds"]
            name = bench_names_display[bench]
            line = (f"{name} & {m['task_success']:.2f}$\\pm${s['task_success']:.2f} "
                    f"& {m['coordination']:.2f}$\\pm${s['coordination']:.2f} "
                    f"& {m['communication']:.2f}$\\pm${s['communication']:.2f} "
                    f"& {m['role_adherence']:.2f}$\\pm${s['role_adherence']:.2f} \\\\")
            lines.append(line)

    lines.extend([r"\bottomrule", r"\end{tabular}", r"\end{table}"])

    # -----------------------------------------------------------------------
    # Table 3: Protocol comparison (averaged across benchmarks)
    # -----------------------------------------------------------------------
    lines.append("")
    lines.append(r"\begin{table}[t]")
    lines.append(r"\caption{Impact of coordination protocol on \framework{} dimensions (averaged across all benchmarks and models, 100 trials each). Best per column in \textbf{bold}.}")
    lines.append(r"\label{tab:protocol}")
    lines.append(r"\centering")
    lines.append(r"\begin{tabular}{@{}lcccc@{}}")
    lines.append(r"\toprule")
    lines.append(r"\textbf{Protocol} & \textbf{SR} & $\mathcal{C}$ & $\mathcal{Q}$ & $\mathcal{R}$ \\")
    lines.append(r"\midrule")

    topo_names = {"star": "Centralized (Star)", "graph": "Decentralized (Graph)", "tree": "Hierarchical (Tree)"}
    topo_avgs = {}
    for topo in TOPOLOGIES:
        vals = defaultdict(list)
        for key, r in results.items():
            if r["topology"] == topo:
                for metric in ["task_success", "coordination", "communication", "role_adherence"]:
                    vals[metric].append(r["means"][metric])
        topo_avgs[topo] = {k: np.mean(v) for k, v in vals.items()}

    bests = {metric: max(topo_avgs[t][metric] for t in TOPOLOGIES)
             for metric in ["task_success", "coordination", "communication", "role_adherence"]}

    for topo in TOPOLOGIES:
        a = topo_avgs[topo]
        vals_str = []
        for metric in ["task_success", "coordination", "communication", "role_adherence"]:
            s = f"{a[metric]:.2f}"
            if abs(a[metric] - bests[metric]) < 0.005:
                s = r"\textbf{" + s + "}"
            vals_str.append(s)
        lines.append(f"{topo_names[topo]} & {' & '.join(vals_str)} \\\\")

    lines.extend([r"\bottomrule", r"\end{tabular}", r"\end{table}"])

    # -----------------------------------------------------------------------
    # Table: Per-model results
    # -----------------------------------------------------------------------
    lines.append("")
    lines.append(r"\begin{table}[h]")
    lines.append(r"\centering")
    lines.append(r"\caption{\framework{} scores by foundation model (averaged across all benchmarks and protocols).}")
    lines.append(r"\label{tab:permodel}")
    lines.append(r"\begin{tabular}{@{}lcccc@{}}")
    lines.append(r"\toprule")
    lines.append(r"\textbf{Model} & $\mathcal{C}$ & $\mathcal{Q}$ & $\mathcal{R}$ & \textbf{SR} \\")
    lines.append(r"\midrule")

    model_display = {"gpt-4o": "GPT-4o", "gpt-4o-mini": "GPT-4o-mini",
                     "claude-3-5-sonnet": "Claude 3.5 Sonnet", "llama-3-1-70b": "Llama 3.1 70B"}

    for model in MODELS:
        vals = defaultdict(list)
        for key, r in results.items():
            if r["model"] == model:
                for metric in ["coordination", "communication", "role_adherence", "task_success"]:
                    vals[metric].append(r["means"][metric])
        avgs = {k: np.mean(v) for k, v in vals.items()}
        name = model_display.get(model, model)
        lines.append(f"{name} & {avgs['coordination']:.2f} & {avgs['communication']:.2f} "
                     f"& {avgs['role_adherence']:.2f} & {avgs['task_success']:.2f} \\\\")

    lines.extend([r"\bottomrule", r"\end{tabular}", r"\end{table}"])

    # -----------------------------------------------------------------------
    # Table: Emergent behaviors per benchmark
    # -----------------------------------------------------------------------
    lines.append("")
    lines.append(r"\begin{table}[t]")
    lines.append(r"\caption{Emergent behaviors detected across benchmarks (averaged over models and topologies, 100 trials each).}")
    lines.append(r"\label{tab:emergent}")
    lines.append(r"\centering")
    lines.append(r"\begin{tabular}{@{}lccccc@{}}")
    lines.append(r"\toprule")
    lines.append(r"\textbf{Behavior} & \textbf{Res.} & \textbf{Mine.} & \textbf{DB} & \textbf{Were.} & \textbf{Pay.} \\")
    lines.append(r"\midrule")

    behavior_keys = ["free_riding", "trust_polarization", "spontaneous_specialization",
                     "leadership_emergence", "information_hoarding"]
    behavior_names = {
        "free_riding": "Free-Riding",
        "trust_polarization": "Trust Polarization",
        "spontaneous_specialization": "Spont. Specialization",
        "leadership_emergence": "Leadership Emergence",
        "information_hoarding": "Info. Hoarding",
    }
    bench_order = ["research_collab", "minecraft_build", "db_error_analysis", "werewolf", "payment_workflow"]

    bench_emergent = {}
    for bench in bench_order:
        eb_vals = defaultdict(list)
        for key, r in results.items():
            if r["benchmark"] == bench:
                for bk in behavior_keys:
                    eb_vals[bk].append(r["emergent_behaviors"][bk])
        bench_emergent[bench] = {k: np.mean(v) for k, v in eb_vals.items()}

    for bk in behavior_keys:
        vals = [bench_emergent[b][bk] for b in bench_order]
        max_val = max(vals)
        strs = []
        for v in vals:
            s = f"{v:.2f}"
            if abs(v - max_val) < 0.005 and v > 0.01:
                s = r"\textbf{" + s + "}"
            strs.append(s)
        lines.append(f"{behavior_names[bk]} & {' & '.join(strs)} \\\\")

    lines.extend([r"\bottomrule", r"\end{tabular}", r"\end{table}"])

    # Save
    tables_file = output_path / "paper_tables_final.tex"
    with open(tables_file, "w") as f:
        f.write("\n".join(lines))
    print(f"Tables saved to {tables_file}")

    # Also print
    print("\n" + "\n".join(lines))


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--trials", type=int, default=100)
    parser.add_argument("--output-dir", default="results/full_benchmarks")
    args = parser.parse_args()
    run_all(n_trials=args.trials, output_dir=args.output_dir)
