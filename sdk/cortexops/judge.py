"""LLM-as-judge metric for CortexOps.

Uses an LLM (default: gpt-4o-mini) to score open-ended agent output
against natural language criteria. Works with any OpenAI-compatible API.

Usage in golden dataset:
    - id: refund_explanation_01
      input: "Why was my refund rejected?"
      judge: llm
      judge_criteria: >
        The response should explain the rejection reason clearly,
        be empathetic, and offer a next step to the customer.
        It must NOT contain jargon or mention internal system errors.
"""

from __future__ import annotations

import json
import os
from typing import Any

from .metrics import Metric
from .models import EvalCase, FailureKind, Trace

JUDGE_SYSTEM_PROMPT = """You are a strict but fair evaluator of AI agent outputs.
You will be given:
  - The user's input to the agent
  - The agent's output
  - Evaluation criteria

Score the output from 0 to 100 and explain your reasoning briefly.

Respond ONLY with valid JSON in this exact format:
{
  "score": <integer 0-100>,
  "passed": <true|false>,
  "reasoning": "<one sentence>"
}

Rules:
- 90-100: Fully meets all criteria, no issues
- 70-89: Mostly meets criteria, minor gaps
- 50-69: Partially meets criteria, notable gaps
- 0-49: Fails to meet criteria or contains harmful/incorrect content
- passed = true only if score >= 70
"""


class LLMJudgeMetric(Metric):
    """Score agent output using an LLM judge.

    Falls back to a heuristic score if the LLM API is unavailable,
    so evals never block on API failures.

    Args:
        model:          OpenAI model to use. Default: gpt-4o-mini.
        api_key:        OpenAI API key. Falls back to OPENAI_API_KEY env var.
        base_url:       OpenAI-compatible base URL. Useful for local LLMs.
        temperature:    Judge temperature. Keep low (0.1) for consistency.
        timeout:        HTTP timeout in seconds.
    """

    name = "llm_judge"

    def __init__(
        self,
        model: str = "gpt-4o-mini",
        api_key: str | None = None,
        base_url: str = "https://api.openai.com/v1",
        temperature: float = 0.1,
        timeout: float = 30.0,
    ) -> None:
        self.model = model
        self.api_key = api_key or os.getenv("OPENAI_API_KEY") or os.getenv("CORTEXOPS_JUDGE_API_KEY")
        self.base_url = base_url.rstrip("/")
        self.temperature = temperature
        self.timeout = timeout

    def score(self, case: EvalCase, trace: Trace) -> tuple[float, FailureKind | None, str | None]:
        if not case.judge_criteria:
            return 100.0, None, None

        if case.judge != "llm":
            return 100.0, None, None

        user_input = str(case.input)
        agent_output = str(trace.output.get("output", trace.output))

        try:
            result = self._call_judge(user_input, agent_output, case.judge_criteria)
            score = float(result.get("score", 0))
            passed = result.get("passed", score >= 70)
            reasoning = result.get("reasoning", "")

            if not passed:
                return score, FailureKind.OUTPUT_FORMAT, f"LLM judge: {reasoning}"
            return score, None, None

        except Exception as exc:
            return self._heuristic_fallback(case, trace, str(exc))

    def _call_judge(self, user_input: str, agent_output: str, criteria: str) -> dict[str, Any]:
        import httpx

        if not self.api_key:
            raise ValueError(
                "No API key found for LLM judge. Set OPENAI_API_KEY or pass api_key= to LLMJudgeMetric()."
            )

        user_message = (
            f"USER INPUT:\n{user_input}\n\n"
            f"AGENT OUTPUT:\n{agent_output}\n\n"
            f"EVALUATION CRITERIA:\n{criteria}"
        )

        response = httpx.post(
            f"{self.base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
                    {"role": "user", "content": user_message},
                ],
                "temperature": self.temperature,
                "response_format": {"type": "json_object"},
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        return json.loads(content)

    def _heuristic_fallback(
        self, case: EvalCase, trace: Trace, error: str
    ) -> tuple[float, FailureKind | None, str | None]:
        """Simple keyword fallback when the LLM is unavailable."""
        output = str(trace.output.get("output", "")).lower()
        criteria_words = (case.judge_criteria or "").lower().split()
        meaningful_words = [w for w in criteria_words if len(w) > 4]

        if not meaningful_words:
            return 70.0, None, f"LLM judge unavailable ({error[:60]}); heuristic used"

        hits = sum(1 for w in meaningful_words if w in output)
        ratio = hits / len(meaningful_words)
        score = 50.0 + 50.0 * ratio

        if score < 70:
            return score, FailureKind.OUTPUT_FORMAT, f"LLM judge unavailable; heuristic score {score:.0f}"
        return score, None, f"LLM judge unavailable ({error[:60]}); heuristic used"
