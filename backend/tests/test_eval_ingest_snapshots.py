"""Eval ingest snapshots: prompt versions and datasets are reused or committed without 500s."""
from __future__ import annotations

import uuid

import pytest
from conftest import PROJECT


def _ingest(client, **extra):
    body = {
        "project": PROJECT,
        "total_cases": 1,
        "passed": 1,
        "failed": 0,
        "task_completion_rate": 1.0,
        "tool_accuracy": 100.0,
        "latency_p50_ms": 10.0,
        "latency_p95_ms": 20.0,
        "case_results": [{
            "case_id": "c1", "passed": True, "score": 100.0,
            "task_completion": True, "tool_accuracy": 100.0, "latency_ms": 10.0,
        }],
        **extra,
    }
    r = client.post("/v1/evals/ingest", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _commit(client, name, content):
    r = client.post("/v1/prompts", json={"project": PROJECT, "prompt_name": name, "content": content})
    assert r.status_code == 201, r.text
    return r.json()


def _versions(client, name):
    r = client.get("/v1/prompts", params={"project": PROJECT, "prompt_name": name})
    assert r.status_code == 200, r.text
    return r.json()


def _snapshot(name, content, **extra):
    return {"prompt_name": name, "content": content, **extra}


@pytest.mark.parametrize("existing", [0, 1, 2, 3])
def test_ingest_reuses_latest_version_when_content_unchanged(client, existing):
    name = f"refund-{uuid.uuid4().hex[:6]}"
    for i in range(existing):
        _commit(client, name, f"prompt v{i + 1}")
    content = f"prompt v{existing}" if existing else "prompt v1"

    _ingest(client, prompt=_snapshot(name, content))

    versions = _versions(client, name)
    assert len(versions) == max(existing, 1)
    assert versions[0]["version"] == max(existing, 1)
    assert versions[0]["content"] == content


@pytest.mark.parametrize("existing", [1, 2, 3])
def test_ingest_commits_new_version_when_content_changed(client, existing):
    name = f"triage-{uuid.uuid4().hex[:6]}"
    for i in range(existing):
        _commit(client, name, f"prompt v{i + 1}")
    latest_id = _versions(client, name)[0]["id"]

    _ingest(client, prompt=_snapshot(
        name, "rewritten prompt", model="gpt-4o", temperature=0.2, commit_message="tune", author="ci",
    ))

    versions = _versions(client, name)
    assert len(versions) == existing + 1
    new = versions[0]
    assert new["version"] == existing + 1
    assert new["content"] == "rewritten prompt"
    assert new["parent_version_id"] == latest_id
    assert (new["model"], new["temperature"], new["commit_message"], new["author"]) == ("gpt-4o", 0.2, "tune", "ci")


def test_ingest_first_version_has_no_parent(client):
    name = f"fresh-{uuid.uuid4().hex[:6]}"
    _ingest(client, prompt=_snapshot(name, "hello"))
    [v1] = _versions(client, name)
    assert v1["version"] == 1
    assert v1["parent_version_id"] is None


def test_repeated_ingest_with_same_prompt_is_idempotent(client):
    name = f"stable-{uuid.uuid4().hex[:6]}"
    _commit(client, name, "a")
    _commit(client, name, "b")
    for _ in range(3):
        _ingest(client, prompt=_snapshot(name, "b"))
    assert [v["version"] for v in _versions(client, name)] == [2, 1]


@pytest.mark.parametrize("changed", [{"model": "gpt-4o-mini"}, {"temperature": 0.1}])
def test_ingest_commits_new_version_when_settings_changed(client, changed):
    name = f"settings-{uuid.uuid4().hex[:6]}"
    _ingest(client, prompt=_snapshot(name, "same", model="gpt-4o", temperature=0.2))
    _ingest(client, prompt=_snapshot(name, "same", **{"model": "gpt-4o", "temperature": 0.2, **changed}))

    versions = _versions(client, name)
    assert [v["version"] for v in versions] == [2, 1]
    assert {k: versions[0][k] for k in changed} == changed


def test_ingest_without_settings_reuses_version_with_settings(client):
    name = f"nosettings-{uuid.uuid4().hex[:6]}"
    _ingest(client, prompt=_snapshot(name, "same", model="gpt-4o", temperature=0.2))
    _ingest(client, prompt=_snapshot(name, "same"))
    assert [v["version"] for v in _versions(client, name)] == [1]


def _datasets_named(client, name):
    r = client.get("/v1/eval/datasets")
    assert r.status_code == 200, r.text
    return [d for d in r.json() if d["name"] == name]


@pytest.mark.parametrize("existing", [0, 1, 2])
def test_ingest_dataset_snapshot_with_existing_same_name(client, existing):
    name = f"golden-{uuid.uuid4().hex[:6]}"
    for _ in range(existing):
        r = client.post("/v1/eval/datasets", json={"name": name, "cases": [{"id": "c1"}]})
        assert r.status_code == 201, r.text

    _ingest(client, dataset={"name": name, "cases": [{"id": "c1"}, {"id": "c2"}]})

    assert len(_datasets_named(client, name)) == max(existing, 1)
