"""SDK exception types."""

from cortexops import EvalThresholdError


def test_eval_threshold_error_message():
    err = EvalThresholdError("task_completion < 0.9")
    assert "task_completion" in str(err)
