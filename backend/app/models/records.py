from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    eval_runs: Mapped[list["EvalRun"]] = relationship("EvalRun", back_populates="project_rel", lazy="select")
    traces: Mapped[list["TraceRecord"]] = relationship("TraceRecord", back_populates="project_rel", lazy="select")
    api_keys: Mapped[list["ApiKey"]] = relationship("ApiKey", back_populates="project_rel", lazy="select")
    prompt_versions: Mapped[list["PromptVersion"]] = relationship("PromptVersion", back_populates="project_rel", lazy="select")


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    project: Mapped[str] = mapped_column(String(255), ForeignKey("projects.name"), nullable=False, index=True)
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), default="default")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    project_rel: Mapped["Project"] = relationship("Project", back_populates="api_keys")


class EvalRun(Base):
    __tablename__ = "eval_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    project: Mapped[str] = mapped_column(String(255), ForeignKey("projects.name"), nullable=False, index=True)
    dataset_version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    total_cases: Mapped[int] = mapped_column(Integer, default=0)
    passed: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    warnings: Mapped[int] = mapped_column(Integer, default=0)
    task_completion_rate: Mapped[float] = mapped_column(Float, default=0.0)
    tool_accuracy: Mapped[float] = mapped_column(Float, default=0.0)
    latency_p50_ms: Mapped[float] = mapped_column(Float, default=0.0)
    latency_p95_ms: Mapped[float] = mapped_column(Float, default=0.0)
    regressions: Mapped[int] = mapped_column(Integer, default=0)
    baseline_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    project_rel: Mapped["Project"] = relationship("Project", back_populates="eval_runs")
    case_results: Mapped[list["CaseResultRecord"]] = relationship("CaseResultRecord", back_populates="run", lazy="select")


class CaseResultRecord(Base):
    __tablename__ = "case_results"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    run_id: Mapped[str] = mapped_column(String(36), ForeignKey("eval_runs.id"), nullable=False, index=True)
    case_id: Mapped[str] = mapped_column(String(255), nullable=False)
    passed: Mapped[bool] = mapped_column(default=False)
    score: Mapped[float] = mapped_column(Float, default=0.0)
    task_completion: Mapped[bool] = mapped_column(default=False)
    tool_accuracy: Mapped[float] = mapped_column(Float, default=0.0)
    latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
    failure_kind: Mapped[str | None] = mapped_column(String(50), nullable=True)
    failure_detail: Mapped[str | None] = mapped_column(Text, nullable=True)

    run: Mapped["EvalRun"] = relationship("EvalRun", back_populates="case_results")


class TraceRecord(Base):
    __tablename__ = "traces"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    project: Mapped[str] = mapped_column(String(255), ForeignKey("projects.name"), nullable=False, index=True)
    case_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="completed")
    total_latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
    failure_kind: Mapped[str | None] = mapped_column(String(50), nullable=True)
    failure_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_trace: Mapped[str] = mapped_column(Text, nullable=False)
    environment: Mapped[str] = mapped_column(String(50), default="development")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)

    project_rel: Mapped["Project"] = relationship("Project", back_populates="traces")


class PromptVersion(Base):
    __tablename__ = "prompt_versions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    project: Mapped[str] = mapped_column(String(255), ForeignKey("projects.name"), nullable=False, index=True)
    prompt_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(String(100), default="")
    temperature: Mapped[float] = mapped_column(Float, default=0.7)
    parent_version_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("prompt_versions.id"), nullable=True)
    commit_message: Mapped[str] = mapped_column(Text, default="")
    author: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)

    project_rel: Mapped["Project"] = relationship("Project", back_populates="prompt_versions")
    parent: Mapped["PromptVersion | None"] = relationship("PromptVersion", remote_side=[id], lazy="select")
