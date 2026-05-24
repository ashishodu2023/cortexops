# ══════════════════════════════════════════════════════════════════
# GOLDEN DATASET — Build, version, and run eval datasets
# ══════════════════════════════════════════════════════════════════

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


@dataclass
class EvalCase:
    """A single evaluation test case."""
    id: str
    input: str | dict
    expected: str | None = None
    context: str | None = None
    tags: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> EvalCase:
        return cls(
            id=str(d.get("id", uuid.uuid4().hex[:8])),
            input=d["input"],
            expected=d.get("expected"),
            context=d.get("context"),
            tags=d.get("tags", []),
            metadata=d.get("metadata", {}),
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "input": self.input,
            "expected": self.expected,
            "context": self.context,
            "tags": self.tags,
            "metadata": self.metadata,
        }


@dataclass
class GoldenDataset:
    """
    A versioned collection of evaluation test cases.

    Usage:
        # Build a dataset
        ds = GoldenDataset(name="refund-agent-v1")
        ds.add(input="Process refund for order #4821", expected="refund_approved")
        ds.add(input="Cancel subscription for user@example.com", expected="subscription_cancelled")
        ds.save("datasets/refund_agent.yaml")

        # Load and run
        ds = GoldenDataset.load("datasets/refund_agent.yaml")
        results = ds.run(agent=your_agent, fail_on="task_completion < 0.90")
    """

    name: str
    version: str = "1.0.0"
    description: str = ""
    cases: list[EvalCase] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: dict = field(default_factory=dict)

    def add(
        self,
        input: str | dict,
        expected: str | None = None,
        context: str | None = None,
        tags: list[str] | None = None,
        id: str | None = None,
    ) -> GoldenDataset:
        """Add a test case. Returns self for chaining."""
        self.cases.append(EvalCase(
            id=id or f"case-{len(self.cases)+1:03d}",
            input=input,
            expected=expected,
            context=context,
            tags=tags or [],
        ))
        return self

    def add_from_trace(self, trace: dict, expected: str | None = None) -> GoldenDataset:
        """
        Seed a dataset case from a production trace.
        The trace input becomes the test input.
        """
        self.cases.append(EvalCase(
            id=f"trace-{trace.get('trace_id', uuid.uuid4().hex[:8])[:12]}",
            input=trace.get("input", {}),
            expected=expected,
            context=f"Seeded from production trace {trace.get('trace_id', '')}",
            metadata={"source": "production_trace", "project": trace.get("project", "")},
        ))
        return self

    def filter(self, tag: str) -> GoldenDataset:
        """Return a new dataset with only cases matching a tag."""
        filtered = GoldenDataset(
            name=f"{self.name}[{tag}]",
            version=self.version,
            cases=[c for c in self.cases if tag in c.tags],
        )
        return filtered

    def save(self, path: str | Path) -> None:
        """Save dataset to YAML."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "created_at": self.created_at,
            "metadata": self.metadata,
            "cases": [c.to_dict() for c in self.cases],
        }
        with open(path, "w") as f:
            yaml.dump(data, f, allow_unicode=True, sort_keys=False)

    @classmethod
    def load(cls, path: str | Path) -> GoldenDataset:
        """Load dataset from YAML or JSON."""
        path = Path(path)
        with open(path) as f:
            if path.suffix in (".yaml", ".yml"):
                data = yaml.safe_load(f)
            else:
                data = json.load(f)

        ds = cls(
            name=data["name"],
            version=data.get("version", "1.0.0"),
            description=data.get("description", ""),
            created_at=data.get("created_at", ""),
            metadata=data.get("metadata", {}),
        )
        for case_dict in data.get("cases", []):
            ds.cases.append(EvalCase.from_dict(case_dict))
        return ds

    def run(
        self,
        agent: Any,
        *,
        metrics: list[str] | None = None,
        fail_on: str | None = None,
        verbose: bool = True,
        use_judge: bool = False,
        judge_rubric: str = "task_completion",
        judge_api_key: str | None = None,
    ) -> DatasetRunResult:
        """
        Run the dataset against an agent and return results.

        Args:
            agent:          Any callable that accepts input and returns output.
            metrics:        Subset of metrics to compute (default: all).
            fail_on:        Threshold expression e.g. "task_completion < 0.90".
                            Raises DatasetThresholdError if condition is met.
            verbose:        Print per-case progress.
            use_judge:      Use LLM-as-judge for semantic scoring.
            judge_rubric:   Rubric name for LLM judge.
            judge_api_key:  OpenAI API key for LLM judge.
        """
        from .eval import EvalSuite

        # Build EvalSuite-compatible dataset format
        suite_dataset = {
            "name": self.name,
            "version": self.version,
            "cases": [c.to_dict() for c in self.cases],
        }

        summary = EvalSuite.run(
            dataset=suite_dataset,
            agent=agent,
            metrics=metrics,
            verbose=verbose,
            fail_on=fail_on,
        )

        # Optionally run LLM judge on top
        judge_summary = None
        if use_judge:
            from .judge import LLMJudge
            judge = LLMJudge(api_key=judge_api_key)
            judge_cases = [
                {
                    "id": c.id,
                    "input": str(c.input),
                    "output": str(summary.case_results[i].output) if i < len(summary.case_results) else "",
                    "expected": c.expected,
                }
                for i, c in enumerate(self.cases)
            ]
            judge_summary = judge.evaluate_batch(judge_cases, rubric=judge_rubric, verbose=verbose)

        return DatasetRunResult(
            dataset_name=self.name,
            dataset_version=self.version,
            summary=summary,
            judge_summary=judge_summary,
            case_count=len(self.cases),
        )

    def __len__(self) -> int:
        return len(self.cases)

    def __repr__(self) -> str:
        return f"GoldenDataset(name={self.name!r}, version={self.version!r}, cases={len(self.cases)})"


@dataclass
class DatasetRunResult:
    """Combined result from a dataset run with optional LLM judge scores."""
    dataset_name: str
    dataset_version: str
    summary: Any               # EvalSummary
    judge_summary: Any | None  # JudgeSummary or None
    case_count: int

    def passed(self) -> bool:
        """True if all configured thresholds passed."""
        return getattr(self.summary, "passed", True)

    def print_report(self) -> None:
        """Print a full evaluation report."""
        print(f"\nDataset: {self.dataset_name} v{self.dataset_version}")
        print(f"Cases:   {self.case_count}")
        print(self.summary.summary() if hasattr(self.summary, "summary") else str(self.summary))
        if self.judge_summary:
            print()
            print(self.judge_summary.summary_str())