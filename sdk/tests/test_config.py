"""Tracer configuration."""

from pathlib import Path

import pytest

from cortexops import CortexTracer


def test_sample_rate_bounds():
    with pytest.raises(ValueError):
        CortexTracer(project="p", sample_rate=1.5)


def test_project_from_env(monkeypatch):
    monkeypatch.setenv("CORTEXOPS_PROJECT", "env-project")
    t = CortexTracer(sample_rate=1.0)
    assert t.project == "env-project"


def test_local_only_without_key(monkeypatch, tmp_path):
    monkeypatch.delenv("CORTEXOPS_API_KEY", raising=False)
    monkeypatch.setattr("cortexops.tracer._CREDENTIALS_FILE", tmp_path / "missing-credentials")
    t = CortexTracer(project="local", api_key=None)
    assert t.is_hosted is False
    assert isinstance(tmp_path, Path)
