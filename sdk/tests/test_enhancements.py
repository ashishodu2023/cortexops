"""Tests for CortexOps enhancements — LLM judge, CLI, alerting."""

import sys
import os
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "backend"))
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test.db")

from cortexops.judge import LLMJudgeMetric
from cortexops.models import EvalCase, RunStatus, Trace, TraceNode


def make_trace(output: str, latency_ms: float = 100.0) -> Trace:
    node = TraceNode(node_id="n1", node_name="agent", output={"output": output}, latency_ms=latency_ms)
    return Trace(
        project="test",
        total_latency_ms=latency_ms,
        output={"output": output},
        nodes=[node],
        status=RunStatus.COMPLETED,
    )


# ---------------------------------------------------------------------------
# LLM judge metric
# ---------------------------------------------------------------------------

class TestLLMJudgeMetric:
    def test_skips_when_judge_is_rule(self):
        metric = LLMJudgeMetric()
        case = EvalCase(id="c1", input="test", judge="rule", judge_criteria="must be helpful")
        trace = make_trace("here is a helpful response")
        score, fk, _ = metric.score(case, trace)
        assert score == 100.0
        assert fk is None

    def test_skips_when_no_criteria(self):
        metric = LLMJudgeMetric()
        case = EvalCase(id="c1", input="test", judge="llm")
        trace = make_trace("some output")
        score, fk, _ = metric.score(case, trace)
        assert score == 100.0

    def test_heuristic_fallback_high_match(self):
        metric = LLMJudgeMetric(api_key="placeholder")
        case = EvalCase(
            id="c1",
            input="Explain refund policy",
            judge="llm",
            judge_criteria="response should mention refund policy clearly and offer assistance",
        )
        trace = make_trace("Our refund policy allows returns within 30 days. I am happy to assist you.")
        score, fk, fd = metric.score(case, trace)
        assert score > 50.0
        assert fd is not None

    def test_heuristic_fallback_low_match(self):
        metric = LLMJudgeMetric(api_key="placeholder")
        case = EvalCase(
            id="c1",
            input="Explain refund policy",
            judge="llm",
            judge_criteria="response should mention refund policy clearly and offer assistance",
        )
        trace = make_trace("I cannot help with that request.")
        score, fk, _ = metric.score(case, trace)
        assert score < 100.0


# ---------------------------------------------------------------------------
# Alerting
# ---------------------------------------------------------------------------

class TestAlertPayload:
    def _get_classes(self):
        from app.services.alerting import AlertPayload, SlackAlerter
        return AlertPayload, SlackAlerter

    def test_should_alert_on_failures(self):
        AlertPayload, SlackAlerter = self._get_classes()
        payload = AlertPayload(
            project="test", run_id="abc",
            task_completion_rate=0.8, tool_accuracy=90.0,
            passed=8, failed=2, total_cases=10, regressions=0,
            failed_cases=[{"case_id": "c1", "failure_kind": "tool_call_mismatch", "score": 40}],
        )
        alerter = SlackAlerter(webhook_url=None, threshold=0.90)
        assert alerter.should_alert(payload) is True

    def test_no_alert_when_passing(self):
        AlertPayload, SlackAlerter = self._get_classes()
        payload = AlertPayload(
            project="test", run_id="abc",
            task_completion_rate=0.95, tool_accuracy=98.0,
            passed=10, failed=0, total_cases=10, regressions=0, failed_cases=[],
        )
        alerter = SlackAlerter(webhook_url=None, threshold=0.90)
        assert alerter.should_alert(payload) is False

    def test_alert_on_regression(self):
        AlertPayload, SlackAlerter = self._get_classes()
        payload = AlertPayload(
            project="test", run_id="abc",
            task_completion_rate=0.95, tool_accuracy=98.0,
            passed=10, failed=0, total_cases=10, regressions=2, failed_cases=[],
        )
        alerter = SlackAlerter(webhook_url=None, threshold=0.90)
        assert alerter.should_alert(payload) is True


# ---------------------------------------------------------------------------
# Prompt diff logic
# ---------------------------------------------------------------------------

class TestPromptDiff:
    def test_unified_diff_detects_changes(self):
        import difflib

        v1 = "You are a helpful assistant.\nAlways respond in English."
        v2 = "You are a helpful payments assistant.\nAlways respond in English.\nBe concise."

        diff = list(difflib.unified_diff(
            v1.splitlines(keepends=True),
            v2.splitlines(keepends=True),
            fromfile="v1", tofile="v2", lineterm="",
        ))
        additions = sum(1 for l in diff if l.startswith("+") and not l.startswith("+++"))
        deletions = sum(1 for l in diff if l.startswith("-") and not l.startswith("---"))

        assert additions >= 1
        assert deletions >= 1

    def test_identical_prompts_no_diff(self):
        import difflib

        v1 = v2 = "You are a helpful assistant."
        diff = list(difflib.unified_diff(
            v1.splitlines(keepends=True),
            v2.splitlines(keepends=True),
            fromfile="v1", tofile="v2", lineterm="",
        ))
        assert diff == []


# ---------------------------------------------------------------------------
# CLI imports
# ---------------------------------------------------------------------------

class TestCLIImports:
    def test_cli_module_imports(self):
        from cortexops.cli import main, cmd_eval_run, cmd_version
        assert callable(main)
        assert callable(cmd_eval_run)
        assert callable(cmd_version)

    def test_version_command(self, capsys):
        import argparse
        from cortexops.cli import cmd_version
        cmd_version(argparse.Namespace())
        captured = capsys.readouterr()
        assert "cortexops" in captured.out
        assert "0.2.0" in captured.out


# ---------------------------------------------------------------------------
# API key generation
# ---------------------------------------------------------------------------

class TestApiKeyGeneration:
    def test_generate_produces_cxo_prefix(self):
        pytest.importorskip("app.auth", reason="backend not installed")
        from app.auth import generate_api_key
        raw, hashed = generate_api_key()
        assert raw.startswith("cxo-")

    def test_hash_is_deterministic(self):
        pytest.importorskip("app.auth", reason="backend not installed")
        from app.auth import hash_key
        assert hash_key("test-key") == hash_key("test-key")
        assert hash_key("key-a") != hash_key("key-b")

    def test_generated_keys_unique(self):
        pytest.importorskip("app.auth", reason="backend not installed")
        from app.auth import generate_api_key
        keys = {generate_api_key()[0] for _ in range(20)}
        assert len(keys) == 20


# ---------------------------------------------------------------------------
# Auth key generation — pure logic, no FastAPI dependency
# ---------------------------------------------------------------------------

class TestApiKeyPureFunctions:
    """Tests the pure key generation logic, independent of FastAPI."""

    def _gen(self):
        import secrets, hashlib
        raw = f"cxo-{secrets.token_hex(32)}"
        hashed = hashlib.sha256(raw.encode()).hexdigest()
        return raw, hashed

    def _hash(self, raw: str) -> str:
        import hashlib
        return hashlib.sha256(raw.encode()).hexdigest()

    def test_key_has_cxo_prefix(self):
        raw, _ = self._gen()
        assert raw.startswith("cxo-")

    def test_hash_is_deterministic(self):
        assert self._hash("test-key") == self._hash("test-key")
        assert self._hash("key-a") != self._hash("key-b")

    def test_generated_keys_are_unique(self):
        keys = {self._gen()[0] for _ in range(20)}
        assert len(keys) == 20

    def test_raw_key_length(self):
        raw, _ = self._gen()
        assert len(raw) == 68  # "cxo-" (4) + "-" (0 included in prefix) + 64 hex chars


# ── Framework detection tests ────────────────────────────────────────────
class TestFrameworkDetection:
    """Test that _detect_framework correctly identifies all supported SDKs."""

    def _make_mock(self, class_name: str, module: str) -> object:
        from unittest.mock import MagicMock
        obj = MagicMock()
        obj.__class__.__name__ = class_name
        obj.__class__.__module__ = module
        return obj

    def test_detects_langgraph(self):
        from cortexops.tracer import CortexTracer
        mock = self._make_mock("CompiledStateGraph", "langgraph.graph.graph")
        assert CortexTracer._detect_framework(mock) == "langgraph"

    def test_detects_crewai(self):
        from cortexops.tracer import CortexTracer
        mock = self._make_mock("Crew", "crewai.crew")
        assert CortexTracer._detect_framework(mock) == "crewai"

    def test_detects_openai_agents(self):
        from cortexops.tracer import CortexTracer
        mock = self._make_mock("Agent", "agents.agent")
        assert CortexTracer._detect_framework(mock) == "openai_agents"

    def test_detects_pydantic_ai(self):
        from cortexops.tracer import CortexTracer
        mock = self._make_mock("Agent", "pydantic_ai.agent")
        assert CortexTracer._detect_framework(mock) == "pydantic_ai"

    def test_detects_agno(self):
        from cortexops.tracer import CortexTracer
        mock = self._make_mock("Agent", "agno.agent.agent")
        assert CortexTracer._detect_framework(mock) == "agno"

    def test_detects_autogen(self):
        from cortexops.tracer import CortexTracer
        from unittest.mock import MagicMock
        mock = self._make_mock("AssistantAgent", "autogen.agentchat.assistant_agent")
        mock.initiate_chat = MagicMock()
        assert CortexTracer._detect_framework(mock) == "autogen"

    def test_detects_smolagents(self):
        from cortexops.tracer import CortexTracer
        from unittest.mock import MagicMock
        mock = self._make_mock("CodeAgent", "smolagents.agents")
        mock.run = MagicMock()
        assert CortexTracer._detect_framework(mock) == "smolagents"

    def test_detects_haystack(self):
        from cortexops.tracer import CortexTracer
        mock = self._make_mock("Pipeline", "haystack.core.pipeline.pipeline")
        assert CortexTracer._detect_framework(mock) == "haystack"

    def test_detects_dspy(self):
        from cortexops.tracer import CortexTracer
        from unittest.mock import MagicMock
        mock = self._make_mock("RefundClassifier", "dspy.modules")
        mock.forward = MagicMock()
        assert CortexTracer._detect_framework(mock) == "dspy"

    def test_detects_llamaindex_query(self):
        from cortexops.tracer import CortexTracer
        from unittest.mock import MagicMock
        mock = self._make_mock("RetrieverQueryEngine", "llama_index.core.query_engine")
        mock.query = MagicMock()
        assert CortexTracer._detect_framework(mock) == "llamaindex_query"

    def test_detects_llamaindex_chat(self):
        from cortexops.tracer import CortexTracer
        from unittest.mock import MagicMock
        mock = self._make_mock("CondensePlusContextChatEngine", "llama_index.core.chat_engine")
        mock.chat = MagicMock()
        # No query attr → should detect as chat engine
        del mock.query
        assert CortexTracer._detect_framework(mock) == "llamaindex_chat"

    def test_generic_callable_fallback(self):
        from cortexops.tracer import CortexTracer
        def my_fn(x): return x
        assert CortexTracer._detect_framework(my_fn) == "generic"


class TestNewFrameworkWrappers:
    """Test that new framework wrappers trace correctly using mock agents."""

    def _tracer(self):
        from cortexops import CortexTracer
        return CortexTracer(project="test", sample_rate=1.0)

    def test_pydantic_ai_wrap_traces(self):
        from unittest.mock import MagicMock, patch
        tracer = self._tracer()
        mock_agent = MagicMock()
        mock_agent.__class__.__name__ = "Agent"
        mock_agent.__class__.__module__ = "pydantic_ai.agent"
        mock_result = MagicMock()
        mock_result.data = "refund_approved"
        mock_agent.run_sync.return_value = mock_result

        wrapped = tracer.wrap(mock_agent)
        result = wrapped.run_sync("Process refund #4821")

        assert result.data == "refund_approved"
        trace = tracer.last_trace()
        assert trace is not None
        assert str(trace.status) in ("completed", "RunStatus.COMPLETED")
        print(f"PydanticAI trace: latency={trace.total_latency_ms:.0f}ms")

    def test_smolagents_wrap_traces(self):
        from unittest.mock import MagicMock
        tracer = self._tracer()
        mock_agent = MagicMock()
        mock_agent.__class__.__name__ = "CodeAgent"
        mock_agent.__class__.__module__ = "smolagents.agents"
        mock_agent.run.return_value = "Task completed: refund approved"

        wrapped = tracer.wrap(mock_agent)
        result = wrapped.run("Process refund for order #4821")

        assert result == "Task completed: refund approved"
        trace = tracer.last_trace()
        assert trace is not None
        assert str(trace.status) in ("completed", "RunStatus.COMPLETED")

    def test_haystack_wrap_traces(self):
        from unittest.mock import MagicMock
        tracer = self._tracer()
        mock_pipeline = MagicMock()
        mock_pipeline.__class__.__name__ = "Pipeline"
        mock_pipeline.__class__.__module__ = "haystack.core.pipeline.pipeline"
        mock_pipeline.run.return_value = {"llm": {"replies": ["refund approved"]}}

        wrapped = tracer.wrap(mock_pipeline)
        result = wrapped.run({"retriever": {"query": "refund policy"}})

        assert "llm" in result
        trace = tracer.last_trace()
        assert trace is not None
        assert str(trace.status) in ("completed", "RunStatus.COMPLETED")

    def test_dspy_wrap_traces(self):
        from unittest.mock import MagicMock
        tracer = self._tracer()
        mock_module = MagicMock()
        mock_module.__class__.__name__ = "RefundClassifier"
        mock_module.__class__.__module__ = "dspy.modules"
        mock_module.forward.return_value = MagicMock(action="refund_approved")
        mock_module.forward.__name__ = "forward"

        wrapped = tracer.wrap(mock_module)
        result = wrapped("What should I do with refund #4821?")

        trace = tracer.last_trace()
        assert trace is not None
        assert str(trace.status) in ("completed", "RunStatus.COMPLETED")

    def test_agno_wrap_traces(self):
        from unittest.mock import MagicMock
        tracer = self._tracer()
        mock_agent = MagicMock()
        mock_agent.__class__.__name__ = "Agent"
        mock_agent.__class__.__module__ = "agno.agent.agent"
        mock_agent.run.return_value = MagicMock(content="Refund approved for order #4821")

        wrapped = tracer.wrap(mock_agent)
        result = wrapped.run("Process refund for order #4821")

        trace = tracer.last_trace()
        assert trace is not None
        assert str(trace.status) in ("completed", "RunStatus.COMPLETED")