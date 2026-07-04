"""Shared fixtures for CortexOps SDK integration tests."""

from __future__ import annotations

import pytest

from tests.helpers import make_framework_mock, make_trace

__all__ = ["make_framework_mock", "make_trace"]


@pytest.fixture
def project() -> str:
    return "payments-agent"


@pytest.fixture
def tracer(project):
    from cortexops import CortexTracer

    return CortexTracer(project=project, sample_rate=1.0, local_store=True)


@pytest.fixture
def echo_agent():
    def _agent(inp: dict) -> dict:
        text = inp.get("input", inp.get("prompt", ""))
        return {"output": f"Processed: {text}"}

    return _agent


@pytest.fixture
def failing_agent():
    def _agent(inp: dict) -> dict:
        raise RuntimeError("agent exploded")

    return _agent
