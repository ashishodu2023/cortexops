from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class RunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class ToolCallStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"
    TIMEOUT = "timeout"


class FailureKind(str, Enum):
    TOOL_CALL_MISMATCH = "tool_call_mismatch"
    HALLUCINATION = "hallucination"
    PLAN_DEVIATION = "plan_deviation"
    TIMEOUT = "timeout"
    CONTEXT_OVERFLOW = "context_overflow"
    OUTPUT_FORMAT = "output_format"
    UNKNOWN = "unknown"


class ToolCall(BaseModel):
    name: str
    args: dict[str, Any] = Field(default_factory=dict)
    result: Any = None
    status: ToolCallStatus = ToolCallStatus.SUCCESS
    latency_ms: float = 0.0
    error: str | None = None


class TraceNode(BaseModel):
    node_id: str
    node_name: str
    input: dict[str, Any] = Field(default_factory=dict)
    output: dict[str, Any] = Field(default_factory=dict)
    tool_calls: list[ToolCall] = Field(default_factory=list)
    llm_prompt: str | None = None
    llm_response: str | None = None
    latency_ms: float = 0.0
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class Trace(BaseModel):
    trace_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    project: str
    run_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    case_id: str | None = None
    nodes: list[TraceNode] = Field(default_factory=list)
    input: dict[str, Any] = Field(default_factory=dict)
    output: dict[str, Any] = Field(default_factory=dict)
    total_latency_ms: float = 0.0
    status: RunStatus = RunStatus.COMPLETED
    failure_kind: FailureKind | None = None
    failure_detail: str | None = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    def tool_calls(self) -> list[ToolCall]:
        return [tc for node in self.nodes for tc in node.tool_calls]

    def total_tool_calls(self) -> int:
        return len(self.tool_calls())


class EvalCase(BaseModel):
    id: str
    input: str | dict[str, Any]
    expected_tool_calls: list[str] = Field(default_factory=list)
    expected_output_contains: list[str] = Field(default_factory=list)
    expected_output_not_contains: list[str] = Field(default_factory=list)
    max_latency_ms: float | None = None
    judge: str = "rule"  # "rule" | "llm"
    judge_criteria: str | None = None
    tags: list[str] = Field(default_factory=list)


class EvalDataset(BaseModel):
    version: int = 1
    project: str
    description: str = ""
    cases: list[EvalCase] = Field(default_factory=list)


class CaseResult(BaseModel):
    case_id: str
    passed: bool
    score: float  # 0.0 - 100.0
    task_completion: bool
    tool_accuracy: float
    latency_ms: float
    latency_ok: bool
    failure_kind: FailureKind | None = None
    failure_detail: str | None = None
    trace: Trace | None = None


class EvalSummary(BaseModel):
    run_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    project: str
    dataset_version: int
    total_cases: int
    passed: int
    failed: int
    warnings: int
    task_completion_rate: float
    tool_accuracy: float
    latency_p50_ms: float
    latency_p95_ms: float
    regressions: int = 0
    baseline_run_id: str | None = None
    case_results: list[CaseResult] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    def summary(self) -> str:
        lines = [
            f"CortexOps eval — {self.project}",
            f"  Run ID          : {self.run_id}",
            f"  Cases           : {self.total_cases}  ({self.passed} passed, {self.failed} failed)",
            f"  Task completion : {self.task_completion_rate:.1%}",
            f"  Tool accuracy   : {self.tool_accuracy:.1f}/100",
            f"  Latency p50/p95 : {self.latency_p50_ms:.0f}ms / {self.latency_p95_ms:.0f}ms",
        ]
        if self.regressions:
            lines.append(f"  Regressions     : {self.regressions}  (vs baseline {self.baseline_run_id})")
        failing = [r for r in self.case_results if not r.passed]
        if failing:
            lines.append("  Failed cases:")
            for r in failing:
                lines.append(f"    - {r.case_id}: {r.failure_kind or 'unknown'} (score {r.score:.0f})")
        return "\n".join(lines)

    def __str__(self) -> str:
        return self.summary()
