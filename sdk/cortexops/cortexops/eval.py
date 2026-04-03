from __future__ import annotations

import statistics
import time
from pathlib import Path
from typing import Any

import yaml

from .metrics import compute_case_result
from .models import (
    EvalCase,
    EvalDataset,
    EvalSummary,
    FailureKind,
    RunStatus,
    Trace,
    TraceNode,
)


class EvalSuite:
    """Run evaluation suites against any instrumented agent.

    Usage:
        results = EvalSuite.run(
            dataset="golden_v1.yaml",
            agent=your_langgraph_app,   # wrapped or raw callable
        )
        print(results.summary())
    """

    @classmethod
    def run(
        cls,
        dataset: str | Path | dict | EvalDataset,
        agent: Any,
        *,
        metrics: list[str] | None = None,
        verbose: bool = True,
        fail_on: str | None = None,
    ) -> EvalSummary:
        """Run a full eval suite.

        Args:
            dataset:  Path to YAML, dict, or EvalDataset object.
            agent:    Any callable that accepts a string or dict input.
            metrics:  Optional subset of metrics to run.
            verbose:  Print case-by-case progress.
            fail_on:  Threshold expression like "task_completion < 0.90".
                      Raises EvalThresholdError if the condition is met.
        """
        ds = cls._load_dataset(dataset)
        case_results = []

        for i, case in enumerate(ds.cases):
            if verbose:
                print(f"  [{i+1}/{len(ds.cases)}] {case.id} ... ", end="", flush=True)

            trace = cls._run_case(agent, case)
            result = compute_case_result(case, trace)
            case_results.append(result)

            if verbose:
                status = "pass" if result.passed else "FAIL"
                print(f"{status} ({result.score:.0f})")

        latencies = [r.latency_ms for r in case_results]
        latencies_sorted = sorted(latencies)
        n = len(latencies_sorted)

        summary = EvalSummary(
            project=ds.project,
            dataset_version=ds.version,
            total_cases=len(case_results),
            passed=sum(1 for r in case_results if r.passed),
            failed=sum(1 for r in case_results if not r.passed),
            warnings=sum(1 for r in case_results if not r.passed and r.score >= 60),
            task_completion_rate=sum(1 for r in case_results if r.task_completion) / max(n, 1),
            tool_accuracy=statistics.mean(r.tool_accuracy for r in case_results) if case_results else 0.0,
            latency_p50_ms=latencies_sorted[int(n * 0.50) - 1] if n else 0.0,
            latency_p95_ms=latencies_sorted[int(n * 0.95) - 1] if n else 0.0,
            case_results=case_results,
        )

        if verbose:
            print()
            print(summary.summary())

        if fail_on:
            cls._check_threshold(summary, fail_on)

        return summary

    @classmethod
    def _run_case(cls, agent: Any, case: EvalCase) -> Trace:
        input_data = case.input if isinstance(case.input, dict) else {"input": case.input}
        t0 = time.perf_counter()

        try:
            if hasattr(agent, "invoke"):
                output = agent.invoke(input_data)
            elif callable(agent):
                output = agent(input_data)
            else:
                raise TypeError(f"Agent {type(agent).__name__} is not callable")
            latency_ms = (time.perf_counter() - t0) * 1000
            output_dict = output if isinstance(output, dict) else {"output": str(output)}

            return Trace(
                project="eval",
                case_id=case.id,
                input=input_data,
                output=output_dict,
                total_latency_ms=latency_ms,
                status=RunStatus.COMPLETED,
                nodes=[
                    TraceNode(
                        node_id="eval_root",
                        node_name="agent",
                        input=input_data,
                        output=output_dict,
                        latency_ms=latency_ms,
                    )
                ],
            )

        except Exception as exc:
            latency_ms = (time.perf_counter() - t0) * 1000
            return Trace(
                project="eval",
                case_id=case.id,
                input=input_data,
                output={},
                total_latency_ms=latency_ms,
                status=RunStatus.FAILED,
                failure_kind=FailureKind.UNKNOWN,
                failure_detail=str(exc),
            )

    @classmethod
    def _load_dataset(cls, dataset: str | Path | dict | EvalDataset) -> EvalDataset:
        if isinstance(dataset, EvalDataset):
            return dataset

        if isinstance(dataset, dict):
            return cls._parse_dataset_dict(dataset)

        path = Path(dataset)
        if not path.exists():
            raise FileNotFoundError(f"Dataset not found: {path}")

        raw = yaml.safe_load(path.read_text())
        return cls._parse_dataset_dict(raw)

    @classmethod
    def _parse_dataset_dict(cls, raw: dict) -> EvalDataset:
        cases = []
        for c in raw.get("cases", []):
            cases.append(
                EvalCase(
                    id=str(c["id"]),
                    input=c["input"],
                    expected_tool_calls=c.get("expected_tool_calls", []),
                    expected_output_contains=c.get("expected_output_contains", []),
                    expected_output_not_contains=c.get("expected_output_not_contains", []),
                    max_latency_ms=c.get("max_latency_ms"),
                    judge=c.get("judge", "rule"),
                    judge_criteria=c.get("judge_criteria"),
                    tags=c.get("tags", []),
                )
            )
        return EvalDataset(
            version=raw.get("version", 1),
            project=raw.get("project", "unknown"),
            description=raw.get("description", ""),
            cases=cases,
        )

    @classmethod
    def _check_threshold(cls, summary: EvalSummary, fail_on: str) -> None:
        """Parse and evaluate a threshold expression like 'task_completion < 0.90'."""
        import re

        m = re.match(r"(\w+)\s*([<>]=?)\s*([\d.]+)", fail_on.strip())
        if not m:
            raise ValueError(f"Invalid fail_on expression: '{fail_on}'")

        metric, op, threshold_str = m.groups()
        threshold = float(threshold_str)

        actual = {
            "task_completion": summary.task_completion_rate,
            "tool_accuracy": summary.tool_accuracy / 100.0,
            "pass_rate": summary.passed / max(summary.total_cases, 1),
        }.get(metric)

        if actual is None:
            raise ValueError(f"Unknown metric in fail_on: '{metric}'")

        failed = {
            "<": actual < threshold,
            "<=": actual <= threshold,
            ">": actual > threshold,
            ">=": actual >= threshold,
        }.get(op, False)

        if failed:
            raise EvalThresholdError(
                f"Eval gate failed: {metric}={actual:.3f} {op} {threshold} "
                f"(project={summary.project})"
            )


class EvalThresholdError(Exception):
    """Raised when an eval run fails a CI threshold gate."""
