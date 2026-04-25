"""
tests/test_metrics.py -- Tests for MASEV core metrics.
Run: pytest tests/test_metrics.py -v
"""

import sys
from pathlib import Path

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


def make_trace(n_steps=5, n_agents=3, add_messages=True, specialized=False) -> Trace:
    """Build a synthetic trace for testing."""
    agents = [f"agent_{i}" for i in range(n_agents)]
    steps = []

    action_types = list(ActionType)

    for s in range(n_steps):
        step = TraceStep(step_id=s, timestamp=float(s))
        for i, agent_id in enumerate(agents):
            if specialized:
                # Each agent uses only one action type
                at = action_types[i % len(action_types)]
            else:
                at = action_types[s % len(action_types)]

            step.actions.append(Action(
                agent_id=agent_id,
                action_type=at,
                content=f"Agent {i} doing {at.value} at step {s}",
                timestamp=float(s) + i * 0.1,
            ))

        if add_messages and s > 0:
            step.messages.append(Message(
                sender=agents[s % n_agents],
                receiver=agents[(s + 1) % n_agents],
                content=f"Status update from step {s}",
                timestamp=float(s) + 0.5,
            ))
        steps.append(step)

    return Trace(
        agents=agents,
        steps=steps,
        task_description="Test task",
        task_success=True,
    )


class TestCoordination:
    def test_coordination_entropy_specialized(self):
        """Specialized agents should have low entropy = high score."""
        trace = make_trace(n_steps=10, specialized=True)
        evaluator = MASEvaluator(agents=trace.agents)
        evaluator.ingest(trace)
        report = evaluator.evaluate()
        assert report.coordination_entropy > 0.3, \
            f"Specialized agents should score higher, got {report.coordination_entropy}"

    def test_coordination_entropy_uniform(self):
        """Agents all doing the same thing should have higher entropy = lower score."""
        trace = make_trace(n_steps=10, specialized=False)
        evaluator = MASEvaluator(agents=trace.agents)
        evaluator.ingest(trace)
        report = evaluator.evaluate()
        # Not necessarily 0, but should be lower than specialized
        assert report.coordination_entropy >= 0.0

    def test_parallelism_index(self):
        """All agents active at every step should yield parallelism ~1.0."""
        trace = make_trace(n_steps=5, n_agents=3)
        evaluator = MASEvaluator(agents=trace.agents)
        evaluator.ingest(trace)
        report = evaluator.evaluate()
        assert report.parallelism_index == 1.0, \
            f"Expected parallelism 1.0, got {report.parallelism_index}"

    def test_parallelism_sequential(self):
        """Only one agent active per step should yield low parallelism."""
        agents = ["a", "b", "c"]
        steps = []
        for s in range(6):
            step = TraceStep(step_id=s, timestamp=float(s))
            step.actions.append(Action(
                agent_id=agents[s % 3],
                action_type=ActionType.OUTPUT,
                content=f"Solo action at step {s}",
            ))
            steps.append(step)

        trace = Trace(agents=agents, steps=steps, task_success=True)
        evaluator = MASEvaluator(agents=agents)
        evaluator.ingest(trace)
        report = evaluator.evaluate()
        assert report.parallelism_index == 0.0


class TestCommunication:
    def test_mur_with_messages(self):
        """Traces with messages should produce a valid MUR."""
        trace = make_trace(n_steps=5, add_messages=True)
        evaluator = MASEvaluator(agents=trace.agents)
        evaluator.ingest(trace)
        report = evaluator.evaluate()
        assert 0.0 <= report.message_utility_ratio <= 1.0

    def test_mur_no_messages(self):
        """Traces without messages should have MUR = 1.0 (no wasted messages)."""
        trace = make_trace(n_steps=5, add_messages=False)
        evaluator = MASEvaluator(agents=trace.agents)
        evaluator.ingest(trace)
        report = evaluator.evaluate()
        assert report.message_utility_ratio == 1.0

    def test_communication_overhead(self):
        """Communication overhead should be between 0 and 1."""
        trace = make_trace(n_steps=5, add_messages=True)
        evaluator = MASEvaluator(agents=trace.agents)
        evaluator.ingest(trace)
        report = evaluator.evaluate()
        assert 0.0 <= report.communication_overhead <= 1.0


class TestRoleAdherence:
    def test_role_adherence_no_specs(self):
        """Without role specs, adherence should be 1.0."""
        trace = make_trace(n_steps=5)
        evaluator = MASEvaluator(agents=trace.agents)
        evaluator.ingest(trace)
        report = evaluator.evaluate()
        assert report.role_adherence == 1.0

    def test_role_adherence_with_specs(self):
        """With role specs, adherence should be between 0 and 1."""
        trace = make_trace(n_steps=10)
        specs = [
            AgentSpec(
                agent_id="agent_0",
                role_name="Specialist",
                description="Should only do tool calls",
                expected_actions=["tool_call", "tool_call", "tool_call"],
            ),
            AgentSpec(
                agent_id="agent_1",
                role_name="Communicator",
                description="Should send messages",
                expected_actions=["message", "message"],
            ),
        ]
        evaluator = MASEvaluator(agents=trace.agents, role_specs=specs)
        evaluator.ingest(trace)
        report = evaluator.evaluate()
        assert 0.0 <= report.role_adherence <= 1.0


class TestEmergentBehaviors:
    def test_free_riding_detection(self):
        """An idle agent receiving messages should be detected as free-rider."""
        agents = ["worker_a", "worker_b", "freeloader"]
        steps = []
        for s in range(10):
            step = TraceStep(step_id=s, timestamp=float(s))
            # Workers do work
            step.actions.append(Action(
                agent_id="worker_a", action_type=ActionType.TOOL_CALL,
                content=f"Working hard at step {s}",
            ))
            step.actions.append(Action(
                agent_id="worker_b", action_type=ActionType.TOOL_CALL,
                content=f"Also working at step {s}",
            ))
            # Freeloader receives updates but does nothing
            step.messages.append(Message(
                sender="worker_a", receiver="freeloader",
                content=f"Update: step {s} complete",
            ))
            steps.append(step)

        trace = Trace(agents=agents, steps=steps, task_success=True)
        evaluator = MASEvaluator(agents=agents)
        evaluator.ingest(trace)
        report = evaluator.evaluate()
        assert report.emergent_behaviors.free_riding > 0.0, \
            "Should detect free-riding behavior"

    def test_emergent_scores_bounded(self):
        """All emergent behavior scores should be in [0, 1]."""
        trace = make_trace(n_steps=10)
        evaluator = MASEvaluator(agents=trace.agents)
        evaluator.ingest(trace)
        report = evaluator.evaluate()
        for k, v in report.emergent_behaviors.as_dict().items():
            assert 0.0 <= v <= 1.0, f"{k} out of bounds: {v}"


class TestEndToEnd:
    def test_full_evaluation(self):
        """Full evaluation pipeline should produce valid report."""
        traces = [make_trace(n_steps=5) for _ in range(10)]
        evaluator = MASEvaluator(agents=traces[0].agents)
        evaluator.ingest_batch(traces)
        report = evaluator.evaluate()

        assert report.num_traces == 10
        assert report.num_agents == 3
        assert 0.0 <= report.coordination <= 1.0
        assert 0.0 <= report.communication <= 1.0
        assert report.task_success_rate == 1.0

        # Summary should not crash
        summary = report.summary()
        assert "MASEV" in summary
        assert "Coordination" in summary

    def test_evaluate_single(self):
        """evaluate_single should work independently."""
        trace = make_trace(n_steps=5)
        evaluator = MASEvaluator(agents=trace.agents)
        report = evaluator.evaluate_single(trace)
        assert report.num_traces == 1


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
