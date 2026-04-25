"""
MASEV -- Multi-Agent System Evaluation Framework
Beyond Task Completion: Coordination, Communication, Role Adherence, Emergent Behavior

https://github.com/cortexops/masev
"""

from .evaluator import MASEvaluator
from .models import (
    Action,
    ActionType,
    AgentSpec,
    EmergentBehaviors,
    EvaluationReport,
    Message,
    Trace,
    TraceStep,
)
from .metrics import MetricConfig

__version__ = "0.1.0"
__all__ = [
    "MASEvaluator",
    "MetricConfig",
    "Action",
    "ActionType",
    "AgentSpec",
    "EmergentBehaviors",
    "EvaluationReport",
    "Message",
    "Trace",
    "TraceStep",
]
