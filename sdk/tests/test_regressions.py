"""Regression detection via eval thresholds."""

import pytest
from cortexops import EvalSuite, EvalThresholdError
from cortexops.models import EvalCase, EvalDataset


def test_regression_gate():
    ds = EvalDataset(
        version=1,
        project="reg",
        cases=[EvalCase(id="c1", input="hi", expected_output_contains=["hello"])],
    )

    def bad(inp: dict) -> dict:
        return {"output": "nope"}

    with pytest.raises(EvalThresholdError):
        EvalSuite.run(dataset=ds, agent=bad, verbose=False, fail_on="task_completion < 0.9")
