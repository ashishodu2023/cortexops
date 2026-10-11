"""CORS_ORIGINS accepts the documented comma-separated form as well as a JSON array."""
from __future__ import annotations

import pytest
from app.config import _DEFAULT_CORS, Settings


@pytest.mark.parametrize("raw,expected", [
    ("http://localhost:3000", ["http://localhost:3000"]),
    ("https://a.example.com, https://b.example.com", ["https://a.example.com", "https://b.example.com"]),
    ('["https://a.example.com", "https://b.example.com"]', ["https://a.example.com", "https://b.example.com"]),
    (" , ", _DEFAULT_CORS),
])
def test_cors_origins_from_env(monkeypatch, raw, expected):
    monkeypatch.setenv("CORS_ORIGINS", raw)
    assert Settings().cors_origins == expected


def test_cors_origins_default(monkeypatch):
    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    assert Settings().cors_origins == _DEFAULT_CORS
