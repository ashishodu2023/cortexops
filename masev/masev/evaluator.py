"""
masev.evaluator -- Main evaluation interface.

Usage:
    from masev import MASEvaluator

    evaluator = MASEvaluator(
        agents=["fraud_detector", "compliance", "router"],
        role_specs=[...],
    )

    for trace in traces:
        evaluator.ingest(trace)

    report = evaluator.evaluate()
    print(report.summary())
"""

from __future__ import annotations

from typing import Optional

import numpy as np

from .metrics import (
    MetricConfig,
    compute_communication,
    compute_coordination,
    compute_role_adherence,
    detect_emergent_behaviors,
)
from .models import AgentSpec, EmergentBehaviors, EvaluationReport, Trace


class MASEvaluator:
    """
    Multi-Agent System Evaluator.

    Ingests execution traces and computes MASEV metrics across
    four dimensions: coordination, communication, role adherence,
    and emergent behavior detection.
    """

    def __init__(
        self,
        agents: list[str],
        role_specs: Optional[list[AgentSpec]] = None,
        config: Optional[dict | MetricConfig] = None,
    ):
        self.agents = agents
        self.role_specs = role_specs or []
        self.traces: list[Trace] = []

        if config is None:
            self.config = MetricConfig()
        elif isinstance(config, dict):
            self.config = MetricConfig(**config)
        else:
            self.config = config

    def ingest(self, trace: Trace) -> None:
        """Add a trace to the evaluation set."""
        if not trace.agents:
            trace.agents = self.agents
        self.traces.append(trace)

    def ingest_batch(self, traces: list[Trace]) -> None:
        """Add multiple traces."""
        for t in traces:
            self.ingest(t)

    def evaluate(self) -> EvaluationReport:
        """
        Compute all MASEV metrics across ingested traces.
        Returns an EvaluationReport with aggregated scores.
        """
        if not self.traces:
            return EvaluationReport(num_agents=len(self.agents))

        # Per-trace metrics
        coord_scores = []
        coord_entropy_scores = []
        redundancy_scores = []
        parallelism_scores = []

        comm_scores = []
        mur_scores = []
        density_scores = []
        overhead_scores = []

        role_scores = []
        div_scores = []
        drift_scores = []

        emergent_all = []
        task_successes = []

        for trace in self.traces:
            # Coordination
            c, c_ent, c_red, c_par = compute_coordination(trace, self.config)
            coord_scores.append(c)
            coord_entropy_scores.append(c_ent)
            redundancy_scores.append(c_red)
            parallelism_scores.append(c_par)

            # Communication
            q, mur, dens, over = compute_communication(trace, self.config)
            comm_scores.append(q)
            mur_scores.append(mur)
            density_scores.append(dens)
            overhead_scores.append(over)

            # Role adherence
            r, div, drift = compute_role_adherence(trace, self.role_specs, self.config)
            role_scores.append(r)
            div_scores.append(div)
            drift_scores.append(drift)

            # Emergent behaviors
            eb = detect_emergent_behaviors(trace, self.config)
            emergent_all.append(eb)

            # Task success
            if trace.task_success is not None:
                task_successes.append(1.0 if trace.task_success else 0.0)

        # Aggregate emergent behaviors
        agg_emergent = EmergentBehaviors(
            free_riding=np.mean([e.free_riding for e in emergent_all]),
            trust_polarization=np.mean([e.trust_polarization for e in emergent_all]),
            spontaneous_specialization=np.mean([e.spontaneous_specialization for e in emergent_all]),
            leadership_emergence=np.mean([e.leadership_emergence for e in emergent_all]),
            information_hoarding=np.mean([e.information_hoarding for e in emergent_all]),
        )

        return EvaluationReport(
            coordination=np.mean(coord_scores),
            communication=np.mean(comm_scores),
            role_adherence=np.mean(role_scores),
            emergent_behaviors=agg_emergent,
            task_success_rate=np.mean(task_successes) if task_successes else 0.0,

            coordination_entropy=np.mean(coord_entropy_scores),
            redundancy_ratio=np.mean(redundancy_scores),
            parallelism_index=np.mean(parallelism_scores),
            message_utility_ratio=np.mean(mur_scores),
            information_density=np.mean(density_scores),
            communication_overhead=np.mean(overhead_scores),
            behavioral_divergence=np.mean(div_scores),
            role_drift_rate=np.mean(drift_scores),

            num_traces=len(self.traces),
            num_agents=len(self.agents),
        )

    def evaluate_single(self, trace: Trace) -> EvaluationReport:
        """Evaluate a single trace without adding it to the batch."""
        temp = MASEvaluator(
            agents=self.agents,
            role_specs=self.role_specs,
            config=self.config,
        )
        temp.ingest(trace)
        return temp.evaluate()

    def reset(self) -> None:
        """Clear all ingested traces."""
        self.traces = []
