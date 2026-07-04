"""LLM judge metric — offline / no-API path."""

from cortexops.judge import JudgeResult, LLMJudgeMetric


def test_judge_result_model():
    result = JudgeResult(
        case_id="c1",
        score=0.9,
        raw_score=9,
        max_score=10,
        passed=True,
        reasoning="looks good",
    )
    assert result.passed
    assert result.score == 0.9


def test_llm_judge_metric_importable():
    assert LLMJudgeMetric is not None
