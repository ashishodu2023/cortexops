from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ProjectCreate(BaseModel):
    name: str
    description: str = ""


class ProjectResponse(BaseModel):
    id: str
    name: str
    description: str
    created_at: datetime

    model_config = {"from_attributes": True}


class EvalRunRequest(BaseModel):
    project: str
    dataset: str | dict = Field(..., description="YAML path or inline dict dataset")
    baseline_run_id: str | None = None
    fail_on: str | None = None


class EvalRunResponse(BaseModel):
    run_id: str
    project: str
    status: str
    task_id: str | None = None
    message: str = ""

    model_config = {"from_attributes": True}


class CaseResultResponse(BaseModel):
    case_id: str
    passed: bool
    score: float
    task_completion: bool
    tool_accuracy: float
    latency_ms: float
    failure_kind: str | None
    failure_detail: str | None

    model_config = {"from_attributes": True}


class EvalSummaryResponse(BaseModel):
    run_id: str
    project: str
    status: str
    dataset_version: int
    total_cases: int
    passed: int
    failed: int
    warnings: int
    task_completion_rate: float
    tool_accuracy: float
    latency_p50_ms: float
    latency_p95_ms: float
    regressions: int
    baseline_run_id: str | None
    case_results: list[CaseResultResponse] = []
    created_at: datetime
    completed_at: datetime | None

    model_config = {"from_attributes": True}


class EvalDiffResponse(BaseModel):
    run_id_a: str
    run_id_b: str
    task_completion_delta: float
    tool_accuracy_delta: float
    latency_p95_delta_ms: float
    regressions: list[str]  # case_ids that regressed
    improvements: list[str]  # case_ids that improved


class TraceIngest(BaseModel):
    project: str
    case_id: str | None = None
    input: dict[str, Any] = {}
    output: dict[str, Any] = {}
    total_latency_ms: float = 0.0
    status: str = "completed"
    failure_kind: str | None = None
    failure_detail: str | None = None
    nodes: list[dict[str, Any]] = []
    environment: str = "development"


class TraceResponse(BaseModel):
    trace_id: str
    project: str
    case_id: str | None
    status: str
    total_latency_ms: float
    failure_kind: str | None
    failure_detail: str | None
    environment: str
    created_at: datetime

    model_config = {"from_attributes": True}


class TraceDetailResponse(TraceResponse):
    raw_trace: dict[str, Any]


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str
    environment: str
