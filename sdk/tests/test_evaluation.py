"""EvalSuite integration."""

import pytest

from cortexops import EvalSuite, EvalThresholdError
from cortexops.models import EvalCase, EvalDataset


def _dataset() -> EvalDataset:
    return EvalDataset(
        version=1,
        project="test-agent",
        cases=[
            EvalCase(id="case_01", input="What is 2+2?", expected_output_contains=["4"]),
            EvalCase(id="case_02", input="Say hello", expected_output_contains=["hello"]),
        ],
    )


def test_eval_suite_passes():
    def agent(inp: dict) -> dict:
        q = inp.get("input", "")
        if "2+2" in q:
            return {"output": "The answer is 4"}
        return {"output": "hello there"}

    summary = EvalSuite.run(dataset=_dataset(), agent=agent, verbose=False)
    assert summary.total_cases == 2
    assert summary.passed == 2
    assert summary.task_completion_rate == 1.0


def test_eval_suite_fail_on_threshold():
    def bad(inp: dict) -> dict:
        return {"output": "nothing useful"}

    with pytest.raises(EvalThresholdError):
        EvalSuite.run(dataset=_dataset(), agent=bad, verbose=False, fail_on="task_completion < 0.5")
