"""LLM judge metric — offline / no-API path."""

from cortexops import judge as judge_module
from cortexops.judge import JudgeResult, LLMJudgeMetric
from cortexops.metrics import compute_case_result
from cortexops.models import EvalCase, FailureKind, Trace


def _judged_case() -> EvalCase:
    return EvalCase(
        id="refund",
        input="I want a refund",
        judge="llm",
        judge_criteria="agent confirms refund processed and provides reference number",
    )


def _trace(output: str) -> Trace:
    return Trace(project="p", input={"q": "I want a refund"}, output={"answer": output})


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


def test_heuristic_judge_failure_produces_valid_case_result(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    result = compute_case_result(_judged_case(), _trace("Hello, how can I help you today?"))
    assert result.score < 100.0
    assert result.failure_kind == FailureKind.UNKNOWN
    assert "Heuristic" in (result.failure_detail or "")


def test_llm_judge_failure_produces_valid_case_result(monkeypatch):
    class RejectingJudge:
        def __init__(self, **kwargs):
            pass

        def evaluate(self, **kwargs):
            return JudgeResult(
                case_id="refund", score=0.2, raw_score=2, max_score=10,
                passed=False, reasoning="no refund reference given",
            )

    monkeypatch.setattr(judge_module, "LLMJudge", RejectingJudge)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-live-looking-key")
    result = compute_case_result(_judged_case(), _trace("refund processed, reference number R-1"))
    assert result.score < 100.0
    assert result.failure_kind == FailureKind.UNKNOWN
    assert result.failure_detail == "no refund reference given"
