"""LLM-as-judge token usage and USD cost, per call, per case and per eval run (mocked judge API)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from cortexops import CortexClient, EvalSuite
from cortexops.judge import (
    MODEL_PRICES,
    LLMJudge,
    aggregate_usage,
    estimate_cost_usd,
    model_price,
    register_model_price,
)
from cortexops.models import EvalSummary

JUDGE_JSON = json.dumps({
    "criteria_scores": {"goal_achieved": 5, "no_hallucination": 5, "appropriate_tools": 5},
    "reasoning": "Correct refund.",
})


def _judge_response(usage: dict | None = None, model: str = "gpt-4o-mini-2024-07-18") -> MagicMock:
    body = {"model": model, "choices": [{"message": {"content": JUDGE_JSON}}]}
    if usage is not None:
        body["usage"] = usage
    response = MagicMock(status_code=200)
    response.json.return_value = body
    return response


USAGE = {"prompt_tokens": 1000, "completion_tokens": 500, "total_tokens": 1500}
GPT_4O_MINI_COST = (1000 * 0.15 + 500 * 0.60) / 1_000_000


@pytest.fixture
def restore_prices():
    saved = dict(MODEL_PRICES)
    yield
    MODEL_PRICES.clear()
    MODEL_PRICES.update(saved)


def test_model_price_resolves_dated_snapshots_to_longest_base():
    assert model_price("gpt-4o-mini") == MODEL_PRICES["gpt-4o-mini"]
    assert model_price("gpt-4o-mini-2024-07-18") == MODEL_PRICES["gpt-4o-mini"]
    assert model_price("gpt-4o-2024-08-06") == MODEL_PRICES["gpt-4o"]
    assert model_price("gpt-4omega") is None
    assert model_price("claude-judge") is None
    assert model_price(None) is None


def test_estimate_cost_is_none_not_zero_when_unknown():
    assert estimate_cost_usd("gpt-4o-mini", 1000, 500) == pytest.approx(GPT_4O_MINI_COST)
    assert estimate_cost_usd("my-finetune", 1000, 500) is None
    assert estimate_cost_usd("gpt-4o-mini", None, 500) is None
    assert estimate_cost_usd("gpt-4o-mini", 0, 0) == 0.0


def test_prices_can_be_overridden(restore_prices):
    assert estimate_cost_usd("my-finetune", 1_000_000, 0, {"my-finetune": (3.0, 6.0)}) == pytest.approx(3.0)
    register_model_price("my-finetune", 1.0, 2.0)
    assert estimate_cost_usd("my-finetune", 1_000_000, 1_000_000) == pytest.approx(3.0)


def test_aggregate_usage():
    assert aggregate_usage([]) == (None, None, None)
    assert aggregate_usage([(None, None, None)]) == (None, None, None)
    assert aggregate_usage([(10, 5, 0.1), (None, None, None), (20, 5, 0.2)]) == (30, 10, pytest.approx(0.3))
    # One unpriced judged call makes the total unknown rather than an undercount.
    assert aggregate_usage([(10, 5, 0.1), (20, 5, None)]) == (30, 10, None)


def test_evaluate_captures_usage_and_cost():
    judge = LLMJudge(api_key="sk-test")
    with patch("httpx.post", return_value=_judge_response(USAGE)):
        result = judge.evaluate("c1", "refund #1", "Refunded $5")
    assert (result.tokens_in, result.tokens_out) == (1000, 500)
    assert result.cost_usd == pytest.approx(GPT_4O_MINI_COST)
    assert result.passed


def test_evaluate_unknown_model_reports_tokens_without_cost():
    judge = LLMJudge(api_key="sk-test", model="internal-judge")
    with patch("httpx.post", return_value=_judge_response(USAGE, model="internal-judge")):
        result = judge.evaluate("c1", "q", "a")
    assert (result.tokens_in, result.tokens_out, result.cost_usd) == (1000, 500, None)


def test_evaluate_prices_alias_by_resolved_model():
    judge = LLMJudge(api_key="sk-test", model="my-azure-deployment")
    with patch("httpx.post", return_value=_judge_response(USAGE, model="gpt-4o-mini-2024-07-18")):
        result = judge.evaluate("c1", "q", "a")
    assert result.cost_usd == pytest.approx(GPT_4O_MINI_COST)


def test_evaluate_without_usage_block():
    judge = LLMJudge(api_key="sk-test")
    with patch("httpx.post", return_value=_judge_response(None)):
        result = judge.evaluate("c1", "q", "a")
    assert (result.tokens_in, result.tokens_out, result.cost_usd) == (None, None, None)


def test_evaluate_batch_totals_cost():
    judge = LLMJudge(api_key="sk-test", prices={"gpt-4o-mini": (1.0, 1.0)})
    cases = [{"id": "a", "input": "q", "output": "a"}, {"id": "b", "input": "q", "output": "a"}]
    with patch("httpx.post", return_value=_judge_response(USAGE)):
        summary = judge.evaluate_batch(cases, verbose=False)
    assert (summary.total_tokens_in, summary.total_tokens_out) == (2000, 1000)
    assert summary.total_judge_cost_usd == pytest.approx(0.003)
    assert "judge cost: $0.003000 (2,000 in / 1,000 out tokens)" in summary.summary_str()


def _dataset(judge: str) -> dict:
    return {
        "project": "payments-agent",
        "cases": [
            {"id": "refund", "input": "refund order 1", "judge": judge, "judge_criteria": "refund approved"},
            {"id": "plain", "input": "hello"},
        ],
    }


def test_eval_run_aggregates_judge_cost(monkeypatch, echo_agent):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    with patch("httpx.post", return_value=_judge_response(USAGE)) as post:
        summary = EvalSuite.run(_dataset("llm"), echo_agent, verbose=False)
    assert post.call_count == 1
    judged, plain = summary.case_results
    assert (judged.judge_tokens_in, judged.judge_tokens_out) == (1000, 500)
    assert judged.judge_cost_usd == pytest.approx(GPT_4O_MINI_COST)
    assert (plain.judge_tokens_in, plain.judge_cost_usd) == (None, None)
    assert (summary.judge_tokens_in, summary.judge_tokens_out) == (1000, 500)
    assert summary.judge_cost_usd == pytest.approx(GPT_4O_MINI_COST)
    assert "Judge cost      : $0.000450 (1,000 in / 500 out tokens)" in summary.summary()


def test_eval_run_without_judge_has_no_cost(echo_agent):
    summary = EvalSuite.run(_dataset("rule"), echo_agent, verbose=False)
    assert (summary.judge_cost_usd, summary.judge_tokens_in, summary.judge_tokens_out) == (None, None, None)
    assert "Judge cost" not in summary.summary()


def test_judge_failure_falls_back_without_cost(monkeypatch, echo_agent):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    with patch("httpx.post", side_effect=RuntimeError("judge down")):
        summary = EvalSuite.run(_dataset("llm"), echo_agent, verbose=False)
    assert summary.judge_cost_usd is None
    assert summary.case_results[0].judge_tokens_in is None


def test_old_payloads_still_parse():
    old = {
        "project": "p", "dataset_version": 1, "total_cases": 0, "passed": 0, "failed": 0, "warnings": 0,
        "task_completion_rate": 0.0, "tool_accuracy": 0.0, "latency_p50_ms": 0.0, "latency_p95_ms": 0.0,
    }
    summary = EvalSummary.model_validate(old)
    assert summary.judge_cost_usd is None
    assert "Judge cost" not in summary.summary()


def test_push_eval_sends_judge_cost(monkeypatch, echo_agent):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    with patch("httpx.post", return_value=_judge_response(USAGE)):
        summary = EvalSuite.run(_dataset("llm"), echo_agent, verbose=False)
    client = CortexClient(api_key="cxo-test")
    with patch.object(client, "_post", return_value={}) as post:
        client.push_eval(summary)
    payload = post.call_args.args[1]
    assert payload["judge_cost_usd"] == pytest.approx(GPT_4O_MINI_COST)
    assert (payload["judge_tokens_in"], payload["judge_tokens_out"]) == (1000, 500)
    assert payload["case_results"][0]["judge_tokens_in"] == 1000
    assert "trace" not in payload["case_results"][0]
