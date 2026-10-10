"""pytest integration — run golden-dataset eval gates as ordinary tests.

Usage:
    import cortexops

    @cortexops.eval_gate("golden_v1.yaml", fail_on="task_completion < 0.90")
    def test_payments_agent():
        return build_agent()          # return the agent; the gate runs the dataset

The plugin is registered automatically via the `pytest11` entry point when
cortexops is installed. It adds the `cortexops_eval` marker (deselect with
`-m "not cortexops_eval"`) and an eval summary at the end of the run.
"""
from __future__ import annotations

import functools
import inspect
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .eval import EvalSuite, EvalThresholdError
from .models import EvalDataset, EvalSummary

MARKER = "cortexops_eval"
DEFAULT_FAIL_ON = "pass_rate < 1.0"


@dataclass
class GateResult:
    name: str
    summary: EvalSummary
    failures: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.failures


_results: list[GateResult] = []


def gate_results() -> list[GateResult]:
    """Eval gate results recorded in this process (used for the terminal summary)."""
    return list(_results)


def _resolve_dataset(dataset: str | Path | dict | EvalDataset, fn: Callable) -> str | Path | dict | EvalDataset:
    if not isinstance(dataset, (str, Path)):
        return dataset
    path = Path(dataset)
    if path.is_absolute() or path.exists():
        return path
    try:
        beside_test = Path(inspect.getfile(fn)).parent / path
    except (TypeError, OSError):
        return path
    return beside_test if beside_test.exists() else path


def _fail(message: str) -> None:
    try:
        import pytest
    except ImportError:
        raise EvalThresholdError(message) from None
    pytest.fail(message, pytrace=False)


def eval_gate(
    dataset: str | Path | dict | EvalDataset,
    *,
    fail_on: str | list[str] | None = DEFAULT_FAIL_ON,
    verbose: bool = False,
) -> Callable[[Callable[..., Any]], Callable[..., None]]:
    """Turn a test function into an eval gate.

    The decorated function receives pytest fixtures as usual and must return
    the agent to evaluate (anything `EvalSuite.run` accepts). The test fails
    when any `fail_on` expression is true — by default, when any case fails.

    Args:
        dataset:  YAML path (resolved relative to the test file if not found
                  from the working directory), dict, or EvalDataset.
        fail_on:  One expression or a list, e.g. ["task_completion < 0.9",
                  "tool_accuracy < 0.95"]. Pass None to only record results.
        verbose:  Print case-by-case progress (visible with `pytest -s`).
    """
    conditions = [fail_on] if isinstance(fail_on, str) else list(fail_on or [])
    for cond in conditions:
        EvalSuite._parse_threshold(cond)

    def decorator(fn: Callable[..., Any]) -> Callable[..., None]:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> None:
            agent = fn(*args, **kwargs)
            if agent is None:
                raise TypeError(f"@eval_gate test '{fn.__name__}' must return the agent to evaluate")
            summary = EvalSuite.run(_resolve_dataset(dataset, fn), agent, verbose=verbose)
            failures = []
            for cond in conditions:
                try:
                    EvalSuite._check_threshold(summary, cond)
                except EvalThresholdError as exc:
                    failures.append(str(exc))
            _results.append(GateResult(name=fn.__qualname__, summary=summary, failures=failures))
            if failures:
                _fail("\n".join(failures) + "\n\n" + summary.summary())

        try:
            import pytest
        except ImportError:
            return wrapper
        return getattr(pytest.mark, MARKER)(wrapper)

    return decorator


# ── pytest hooks ───────────────────────────────────────────────────────────

def pytest_configure(config: Any) -> None:
    config.addinivalue_line("markers", f"{MARKER}: CortexOps eval gate (deselect with -m 'not {MARKER}')")


def pytest_terminal_summary(terminalreporter: Any, exitstatus: int, config: Any) -> None:
    if not _results:
        return
    tr = terminalreporter
    tr.section("CortexOps eval gates")
    for r in _results:
        s = r.summary
        line = (
            f"{'PASS' if r.passed else 'FAIL'}  {r.name}  [{s.project}]  "
            f"{s.passed}/{s.total_cases} cases · task completion {s.task_completion_rate:.1%} · "
            f"tool accuracy {s.tool_accuracy:.1f} · p95 {s.latency_p95_ms:.0f}ms"
        )
        tr.write_line(line, green=r.passed, red=not r.passed)
