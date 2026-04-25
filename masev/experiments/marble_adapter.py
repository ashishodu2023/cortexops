"""
experiments/marble_adapter.py

Adapter to convert MultiAgentBench (MARBLE) execution logs
into MASEV-compatible traces for evaluation.

Usage:
    # After running MARBLE scenarios:
    python -m experiments.marble_adapter \
        --marble-log path/to/marble/logs/ \
        --output results/marble_masev.json

See: https://github.com/MultiagentBench/MARBLE
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

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


def parse_marble_log(log_path: str | Path) -> list[Trace]:
    """
    Parse MARBLE execution logs into MASEV traces.

    MARBLE logs are typically JSON files with agent interactions.
    Adjust field names to match the specific MARBLE version you use.
    """
    log_path = Path(log_path)
    traces = []

    if log_path.is_dir():
        log_files = sorted(log_path.glob("*.json"))
    else:
        log_files = [log_path]

    for log_file in log_files:
        with open(log_file) as f:
            data = json.load(f)

        # Adapt based on MARBLE's actual output format
        # The structure below covers the common patterns:
        trace = _convert_single_log(data, source=log_file.name)
        if trace:
            traces.append(trace)

    return traces


def _convert_single_log(data: dict[str, Any], source: str = "") -> Trace | None:
    """Convert a single MARBLE log entry to a MASEV Trace."""

    # Extract agent list
    agents = data.get("agents", [])
    if isinstance(agents, list) and agents and isinstance(agents[0], dict):
        agent_ids = [a.get("name", a.get("id", f"agent_{i}"))
                     for i, a in enumerate(agents)]
    elif isinstance(agents, list):
        agent_ids = [str(a) for a in agents]
    else:
        return None

    trace = Trace(
        agents=agent_ids,
        task_description=data.get("task", data.get("description", source)),
        task_success=data.get("success", data.get("task_success", None)),
        task_score=data.get("score", data.get("task_score", None)),
        metadata={
            "source": source,
            "scenario": data.get("scenario", ""),
            "benchmark": "marble",
        },
    )

    # Parse interaction rounds/steps
    rounds = data.get("rounds", data.get("steps", data.get("interactions", [])))

    for step_idx, round_data in enumerate(rounds):
        step = TraceStep(
            step_id=step_idx,
            timestamp=round_data.get("timestamp", float(step_idx)),
        )

        # Parse actions
        actions = round_data.get("actions", [])
        if isinstance(actions, dict):
            # Some formats use {agent_id: action_data}
            for agent_id, action_data in actions.items():
                step.actions.append(_parse_action(agent_id, action_data, step.timestamp))
        elif isinstance(actions, list):
            for action_data in actions:
                agent_id = action_data.get("agent", action_data.get("agent_id", "unknown"))
                step.actions.append(_parse_action(agent_id, action_data, step.timestamp))

        # Parse messages
        messages = round_data.get("messages", round_data.get("communications", []))
        for msg_data in messages:
            step.messages.append(Message(
                sender=msg_data.get("from", msg_data.get("sender", "unknown")),
                receiver=msg_data.get("to", msg_data.get("receiver", "unknown")),
                content=msg_data.get("content", msg_data.get("message", "")),
                timestamp=msg_data.get("timestamp", step.timestamp),
            ))

        # If no structured actions but there's agent output text
        if not step.actions:
            agent_outputs = round_data.get("outputs", round_data.get("agent_outputs", {}))
            if isinstance(agent_outputs, dict):
                for agent_id, output in agent_outputs.items():
                    content = output if isinstance(output, str) else json.dumps(output)
                    step.actions.append(Action(
                        agent_id=agent_id,
                        action_type=ActionType.OUTPUT,
                        content=content,
                        timestamp=step.timestamp,
                    ))

        trace.steps.append(step)

    return trace


def _parse_action(agent_id: str, action_data: Any, timestamp: float) -> Action:
    """Parse a single action from MARBLE format."""
    if isinstance(action_data, str):
        return Action(
            agent_id=agent_id,
            action_type=ActionType.OUTPUT,
            content=action_data,
            timestamp=timestamp,
        )

    # Determine action type
    action_type_str = action_data.get("type", action_data.get("action_type", "output"))
    type_map = {
        "tool_call": ActionType.TOOL_CALL,
        "function_call": ActionType.TOOL_CALL,
        "message": ActionType.MESSAGE,
        "reasoning": ActionType.REASONING,
        "thought": ActionType.REASONING,
        "output": ActionType.OUTPUT,
        "response": ActionType.OUTPUT,
        "delegation": ActionType.DELEGATION,
    }
    action_type = type_map.get(action_type_str.lower(), ActionType.OUTPUT)

    return Action(
        agent_id=agent_id,
        action_type=action_type,
        content=action_data.get("content", action_data.get("output", str(action_data))),
        tool_name=action_data.get("tool", action_data.get("function_name", None)),
        tool_args=action_data.get("args", action_data.get("parameters", None)),
        timestamp=timestamp,
    )


def evaluate_marble_logs(
    log_path: str,
    output_path: str | None = None,
) -> dict:
    """Run MASEV evaluation on MARBLE logs."""
    traces = parse_marble_log(log_path)
    print(f"Parsed {len(traces)} traces from {log_path}")

    if not traces:
        print("No traces found.")
        return {}

    # Infer agents from first trace
    agents = traces[0].agents

    evaluator = MASEvaluator(agents=agents, config=MetricConfig())
    evaluator.ingest_batch(traces)
    report = evaluator.evaluate()

    print()
    print(report.summary())

    output = {
        "benchmark": "marble",
        "source": log_path,
        "n_traces": len(traces),
        "report": {
            "coordination": report.coordination,
            "communication": report.communication,
            "role_adherence": report.role_adherence,
            "task_success_rate": report.task_success_rate,
            "emergent_behaviors": report.emergent_behaviors.as_dict(),
        },
    }

    if output_path:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w") as f:
            json.dump(output, f, indent=2)
        print(f"\nResults saved to {output_path}")

    return output


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--marble-log", required=True)
    parser.add_argument("--output", default=None)
    args = parser.parse_args()
    evaluate_marble_logs(args.marble_log, args.output)
