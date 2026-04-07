"""
Versioning, reproducibility, and batch execution — checklist items 9, 12.
- Run metadata: model, prompt version, dataset version, SDK version
- Batch eval result aggregator
- Statistical regression detection
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import datetime


# ── Run metadata for reproducibility (checklist item 9) ───────────────────
@dataclass
class RunMetadata:
    """
    Captures everything needed to reproduce an eval run exactly.
    Stored alongside every EvalRun record.
    """
    project: str
    dataset_version: int
    sdk_version: str = "0.1.0"
    model_name: str = ""
    model_temperature: float = 0.7
    prompt_version: int | None = None
    prompt_name: str | None = None
    environment: str = "development"
    git_commit: str | None = None
    triggered_by: str = "manual"  # manual | ci | scheduled
    started_at: datetime = field(default_factory=datetime.utcnow)
    tags: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "project": self.project,
            "dataset_version": self.dataset_version,
            "sdk_version": self.sdk_version,
            "model_name": self.model_name,
            "model_temperature": self.model_temperature,
            "prompt_version": self.prompt_version,
            "prompt_name": self.prompt_name,
            "environment": self.environment,
            "git_commit": self.git_commit,
            "triggered_by": self.triggered_by,
            "started_at": self.started_at.isoformat(),
            "tags": self.tags,
        }


# ── Statistical regression detection (checklist item 5) ───────────────────
def detect_regressions(
    baseline_scores: list[float],
    current_scores: list[float],
    threshold_delta: float = 0.05,
    min_samples: int = 5,
) -> dict:
    """
    Detect statistically significant regressions between two eval runs.

    Uses mean comparison with standard deviation bounds.
    For production: replace with Welch's t-test via scipy.

    Args:
        baseline_scores: task_completion scores from the baseline run.
        current_scores: task_completion scores from the current run.
        threshold_delta: Minimum delta to flag as a regression (default 5%).
        min_samples: Minimum samples required for statistical analysis.

    Returns:
        dict with is_regression, delta, confidence, and details.
    """
    if len(baseline_scores) < min_samples or len(current_scores) < min_samples:
        return {
            "is_regression": False,
            "delta": 0.0,
            "confidence": "insufficient_data",
            "details": f"Need {min_samples}+ samples. Got baseline={len(baseline_scores)}, current={len(current_scores)}.",
        }

    baseline_mean = statistics.mean(baseline_scores)
    current_mean = statistics.mean(current_scores)
    delta = current_mean - baseline_mean

    # Use standard deviation to estimate noise level
    baseline_stdev = statistics.stdev(baseline_scores) if len(baseline_scores) > 1 else 0.0
    signal_to_noise = abs(delta) / (baseline_stdev + 1e-9)

    is_regression = delta < -threshold_delta and signal_to_noise > 1.5

    return {
        "is_regression": is_regression,
        "delta": round(delta, 4),
        "baseline_mean": round(baseline_mean, 4),
        "current_mean": round(current_mean, 4),
        "baseline_stdev": round(baseline_stdev, 4),
        "signal_to_noise": round(signal_to_noise, 2),
        "confidence": "high" if signal_to_noise > 3.0 else "medium" if signal_to_noise > 1.5 else "low",
        "details": (
            f"Current mean {current_mean:.1%} vs baseline {baseline_mean:.1%} "
            f"(delta {delta:+.1%}, SNR {signal_to_noise:.1f})"
        ),
    }


# ── Batch eval aggregator (checklist item 12) ─────────────────────────────
@dataclass
class BatchCaseResult:
    case_id: str
    passed: bool
    score: float
    task_completion: bool
    tool_accuracy: float
    latency_ms: float
    failure_kind: str | None = None
    failure_detail: str | None = None


class BatchAggregator:
    """
    Aggregate results from a batch eval run.
    Handles partial failures — collects all results before computing summary.
    """

    def __init__(self, total_cases: int) -> None:
        self.total_cases = total_cases
        self.results: list[BatchCaseResult] = []
        self.errors: list[dict] = []

    def add_result(self, result: BatchCaseResult) -> None:
        self.results.append(result)

    def add_error(self, case_id: str, error: Exception) -> None:
        """Record a case that failed to execute — does not abort the batch."""
        self.errors.append({"case_id": case_id, "error": str(error), "type": type(error).__name__})
        # Add a failed placeholder so totals are accurate
        self.results.append(BatchCaseResult(
            case_id=case_id,
            passed=False,
            score=0.0,
            task_completion=False,
            tool_accuracy=0.0,
            latency_ms=0.0,
            failure_kind="EXECUTION_ERROR",
            failure_detail=str(error),
        ))

    def summarize(self) -> dict:
        if not self.results:
            return {
                "total_cases": self.total_cases,
                "passed": 0,
                "failed": 0,
                "task_completion_rate": 0.0,
                "tool_accuracy": 0.0,
                "latency_p50_ms": 0.0,
                "latency_p95_ms": 0.0,
            }

        passed = sum(1 for r in self.results if r.passed)
        latencies = sorted(r.latency_ms for r in self.results if r.latency_ms > 0)
        tool_accuracies = [r.tool_accuracy for r in self.results]

        def percentile(data: list[float], p: float) -> float:
            if not data:
                return 0.0
            k = (len(data) - 1) * p / 100
            lo, hi = int(k), min(int(k) + 1, len(data) - 1)
            return data[lo] + (data[hi] - data[lo]) * (k - lo)

        return {
            "total_cases": len(self.results),
            "passed": passed,
            "failed": len(self.results) - passed,
            "task_completion_rate": round(passed / len(self.results), 4),
            "tool_accuracy": round(statistics.mean(tool_accuracies), 2) if tool_accuracies else 0.0,
            "latency_p50_ms": round(percentile(latencies, 50), 2),
            "latency_p95_ms": round(percentile(latencies, 95), 2),
            "execution_errors": len(self.errors),
            "error_details": self.errors,
        }


# ── CI output formatters (checklist item 8) ──────────────────────────────
def to_junit_xml(summary: dict, suite_name: str = "CortexOps Eval") -> str:
    """
    Convert eval summary to JUnit XML format.
    Compatible with Jenkins, GitLab CI, and GitHub Actions test reporters.
    """
    cases = summary.get("case_results", [])
    total = summary.get("total_cases", len(cases))
    failed = summary.get("failed", 0)
    time_s = summary.get("latency_p50_ms", 0) / 1000

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<testsuite name="{suite_name}" tests="{total}" failures="{failed}" time="{time_s:.3f}">',
    ]
    for case in cases:
        case_id = case.get("case_id", "unknown")
        passed = case.get("passed", True)
        latency = case.get("latency_ms", 0) / 1000
        lines.append(f'  <testcase name="{case_id}" time="{latency:.3f}">')
        if not passed:
            failure_kind = case.get("failure_kind", "UNKNOWN")
            failure_detail = case.get("failure_detail", "")
            lines.append(f'    <failure type="{failure_kind}">{failure_detail}</failure>')
        lines.append("  </testcase>")
    lines.append("</testsuite>")
    return "\n".join(lines)