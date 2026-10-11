"""CortexOps — Reliability infrastructure for AI agents.

Quickstart:
    from cortexops import CortexTracer, EvalSuite

    tracer = CortexTracer(project="my-agent")
    graph  = tracer.wrap(your_langgraph_app)

    results = EvalSuite.run(dataset="golden_v1.yaml", agent=graph)
    print(results.summary())
"""

from .auth import cmd_login, cmd_logout, cmd_whoami, load_credentials, save_credentials
from .client import CortexClient
from .eval import EvalSuite, EvalThresholdError
from .judge import LLMJudgeMetric
from .metrics import (
    HallucinationMetric,
    LatencyMetric,
    Metric,
    PromptInjectionMetric,
    TaskCompletionMetric,
    ToolAccuracyMetric,
    ToolMisuseMetric,
)
from .models import (
    CaseResult,
    EvalCase,
    EvalDataset,
    EvalSummary,
    FailureKind,
    RunStatus,
    ThresholdResult,
    ToolCall,
    Trace,
    TraceNode,
)
from .pytest_plugin import eval_gate
from .tracer import CortexTracer

__version__ = "0.6.0"

__all__ = [
    "CortexTracer",
    "EvalSuite",
    "EvalThresholdError",
    "eval_gate",
    "CortexClient",
    "Metric",
    "TaskCompletionMetric",
    "ToolAccuracyMetric",
    "LatencyMetric",
    "HallucinationMetric",
    "LLMJudgeMetric",
    "PromptInjectionMetric",
    "ToolMisuseMetric",
    "Trace",
    "TraceNode",
    "ToolCall",
    "EvalCase",
    "EvalDataset",
    "EvalSummary",
    "CaseResult",
    "FailureKind",
    "RunStatus",
    "ThresholdResult",
    "cmd_login",
    "cmd_logout",
    "cmd_whoami",
    "save_credentials",
    "load_credentials",
]