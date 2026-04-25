"""
masev.models -- Data models for multi-agent traces and evaluation reports.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class ActionType(str, Enum):
    TOOL_CALL = "tool_call"
    MESSAGE = "message"
    REASONING = "reasoning"
    OUTPUT = "output"
    DELEGATION = "delegation"
    IDLE = "idle"


@dataclass
class Message:
    """A single inter-agent message."""
    sender: str
    receiver: str
    content: str
    timestamp: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Action:
    """A single agent action/output at a timestep."""
    agent_id: str
    action_type: ActionType
    content: str
    timestamp: float = field(default_factory=time.time)
    tool_name: Optional[str] = None
    tool_args: Optional[dict[str, Any]] = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class TraceStep:
    """A single timestep in a multi-agent trace."""
    step_id: int
    timestamp: float
    actions: list[Action] = field(default_factory=list)
    messages: list[Message] = field(default_factory=list)


@dataclass
class AgentSpec:
    """Role specification for an agent."""
    agent_id: str
    role_name: str
    description: str
    expected_actions: list[str] = field(default_factory=list)
    expected_tools: list[str] = field(default_factory=list)


@dataclass
class Trace:
    """Complete multi-agent execution trace."""
    trace_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    agents: list[str] = field(default_factory=list)
    steps: list[TraceStep] = field(default_factory=list)
    task_description: str = ""
    task_success: Optional[bool] = None
    task_score: Optional[float] = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def total_actions(self) -> int:
        return sum(len(s.actions) for s in self.steps)

    @property
    def total_messages(self) -> int:
        return sum(len(s.messages) for s in self.steps)

    @property
    def duration(self) -> float:
        if not self.steps:
            return 0.0
        return self.steps[-1].timestamp - self.steps[0].timestamp

    def actions_by_agent(self, agent_id: str) -> list[Action]:
        result = []
        for step in self.steps:
            result.extend(a for a in step.actions if a.agent_id == agent_id)
        return result

    def messages_by_sender(self, agent_id: str) -> list[Message]:
        result = []
        for step in self.steps:
            result.extend(m for m in step.messages if m.sender == agent_id)
        return result

    def messages_to_receiver(self, agent_id: str) -> list[Message]:
        result = []
        for step in self.steps:
            result.extend(m for m in step.messages if m.receiver == agent_id)
        return result


@dataclass
class EmergentBehaviors:
    """Detected emergent behaviors with frequencies."""
    free_riding: float = 0.0
    trust_polarization: float = 0.0
    spontaneous_specialization: float = 0.0
    leadership_emergence: float = 0.0
    information_hoarding: float = 0.0
    details: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, float]:
        return {
            "free_riding": self.free_riding,
            "trust_polarization": self.trust_polarization,
            "spontaneous_specialization": self.spontaneous_specialization,
            "leadership_emergence": self.leadership_emergence,
            "information_hoarding": self.information_hoarding,
        }


@dataclass
class EvaluationReport:
    """Complete MASEV evaluation report for a set of traces."""
    coordination: float = 0.0
    communication: float = 0.0
    role_adherence: float = 0.0
    emergent_behaviors: EmergentBehaviors = field(default_factory=EmergentBehaviors)
    task_success_rate: float = 0.0

    # Sub-metric breakdowns
    coordination_entropy: float = 0.0
    redundancy_ratio: float = 0.0
    parallelism_index: float = 0.0
    message_utility_ratio: float = 0.0
    information_density: float = 0.0
    communication_overhead: float = 0.0
    behavioral_divergence: float = 0.0
    role_drift_rate: float = 0.0

    num_traces: int = 0
    num_agents: int = 0

    def summary(self) -> str:
        lines = [
            "MASEV Evaluation Report",
            "=" * 50,
            f"Traces evaluated: {self.num_traces}",
            f"Agents: {self.num_agents}",
            f"Task Success Rate: {self.task_success_rate:.3f}",
            "",
            "Dimension Scores (0-1, higher is better):",
            f"  Coordination Efficiency: {self.coordination:.3f}",
            f"    - Entropy:    {self.coordination_entropy:.3f}",
            f"    - Redundancy: {self.redundancy_ratio:.3f}",
            f"    - Parallelism:{self.parallelism_index:.3f}",
            f"  Communication Quality:   {self.communication:.3f}",
            f"    - MUR:        {self.message_utility_ratio:.3f}",
            f"    - Density:    {self.information_density:.3f}",
            f"    - Overhead:   {self.communication_overhead:.3f}",
            f"  Role Adherence:          {self.role_adherence:.3f}",
            f"    - Divergence: {self.behavioral_divergence:.3f}",
            f"    - Drift:      {self.role_drift_rate:.3f}",
            "",
            "Emergent Behaviors:",
        ]
        for k, v in self.emergent_behaviors.as_dict().items():
            lines.append(f"  {k}: {v:.3f}")
        return "\n".join(lines)
