"""`cortexops eval run`: --agent loading, multiple --fail-on, JSON/markdown reports, job summaries."""

from __future__ import annotations

import json
import sys
import textwrap
import uuid

import pytest
import yaml

from cortexops import EvalSuite, EvalThresholdError
from cortexops.cli import _load_agent, _split_fail_on, main
from cortexops.models import CaseResult, EvalSummary, FailureKind
from cortexops.report import build_report, render_markdown

DATASET = {
    "version": 3,
    "project": "payments-agent",
    "cases": [
        {"id": "refund_01", "input": "status of REF-1", "expected_output_contains": ["approved"]},
        {"id": "refund_02", "input": "status of REF-2", "expected_output_contains": ["approved"]},
        {"id": "refund_03", "input": "status of REF-3", "expected_output_contains": ["approved"]},
        {"id": "refund_04", "input": "status of REF-4", "expected_output_contains": ["approved"]},
    ],
}

AGENT_SOURCE = textwrap.dedent(
    """
    def good_agent(inp):
        return {"output": "approved"}

    def flaky_agent(inp):
        if "REF-4" in inp["input"]:
            raise RuntimeError("lookup service down")
        return {"output": "approved"}

    def build_agent():
        return good_agent

    class Wrapper:
        agent = staticmethod(good_agent)

    NOT_AN_AGENT = 42
    """
)


@pytest.fixture
def workdir(tmp_path, monkeypatch):
    """A cwd with dataset.yaml and a uniquely named agent module; sys.path/env restored afterwards."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "path", list(sys.path))
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    monkeypatch.delenv("CORTEXOPS_API_KEY", raising=False)
    module = f"cx_agent_{uuid.uuid4().hex[:8]}"
    (tmp_path / f"{module}.py").write_text(AGENT_SOURCE)
    (tmp_path / "dataset.yaml").write_text(yaml.safe_dump(DATASET))
    return tmp_path, module


def run_cli(*argv: str) -> int:
    old = sys.argv
    sys.argv = ["cortexops", "eval", "run", *argv]
    try:
        with pytest.raises(SystemExit) as exc:
            main()
    finally:
        sys.argv = old
    return exc.value.code


# ── --fail-on parsing ─────────────────────────────────────────────────────


def test_split_fail_on_flattens_repeats_and_newlines():
    values = ["task_completion < 0.9", "pass_rate < 1.0\n\n  # comment\n tool_accuracy < 0.8 "]
    assert _split_fail_on(values) == ["task_completion < 0.9", "pass_rate < 1.0", "tool_accuracy < 0.8"]
    assert _split_fail_on(None) == []


def test_evaluate_threshold_returns_result_and_check_still_raises():
    summary = EvalSuite.run(DATASET, lambda inp: {"output": "approved"}, verbose=False)
    ok = EvalSuite.evaluate_threshold(summary, " task_completion < 0.9 ")
    assert (ok.expression, ok.metric, ok.op, ok.threshold, ok.actual, ok.failed) == (
        "task_completion < 0.9", "task_completion", "<", 0.9, 1.0, False,
    )
    assert EvalSuite.evaluate_threshold(summary, "pass_rate >= 1.0").failed
    with pytest.raises(EvalThresholdError):
        EvalSuite._check_threshold(summary, "pass_rate >= 1.0")


# ── --agent loading ───────────────────────────────────────────────────────


def test_load_agent_from_cwd_module(workdir):
    _, module = workdir
    agent = _load_agent(f"{module}:good_agent")
    assert agent({"input": "x"}) == {"output": "approved"}


def test_load_agent_factory_and_dotted_attr(workdir):
    _, module = workdir
    assert _load_agent(f"{module}:build_agent()")({"input": "x"}) == {"output": "approved"}
    assert _load_agent(f"{module}:Wrapper.agent")({"input": "x"}) == {"output": "approved"}


def test_load_agent_from_file_path(workdir):
    tmp_path, module = workdir
    nested = tmp_path / "pkg_dir"
    nested.mkdir()
    (nested / f"{module}_file.py").write_text(AGENT_SOURCE)
    agent = _load_agent(f"pkg_dir/{module}_file.py:build_agent()")
    assert agent({"input": "x"}) == {"output": "approved"}


@pytest.mark.parametrize("spec", ["no_colon", ":attr", "mod:", "mod:()"])
def test_load_agent_rejects_malformed_spec(spec):
    with pytest.raises(ValueError):
        _load_agent(spec)


def test_load_agent_rejects_non_callable(workdir):
    _, module = workdir
    with pytest.raises(TypeError):
        _load_agent(f"{module}:NOT_AN_AGENT")


# ── exit codes and gate semantics ─────────────────────────────────────────


def test_eval_run_passes_with_agent(workdir):
    _, module = workdir
    assert run_cli("-d", "dataset.yaml", "-a", f"{module}:good_agent", "-q") == 0


def test_eval_run_default_gate_fails_on_any_failed_case(workdir, capsys):
    _, module = workdir
    assert run_cli("-d", "dataset.yaml", "-a", f"{module}:flaky_agent", "-q") == 1
    assert "pass_rate=0.750 < 1.0" in capsys.readouterr().err


def test_eval_run_explicit_threshold_tolerates_failures_within_budget(workdir):
    _, module = workdir
    assert run_cli("-d", "dataset.yaml", "-a", f"{module}:flaky_agent", "--fail-on", "pass_rate < 0.7", "-q") == 0


def test_eval_run_multiple_fail_on_any_true_fails(workdir, capsys):
    _, module = workdir
    code = run_cli(
        "-d", "dataset.yaml", "-a", f"{module}:flaky_agent", "-q",
        "--fail-on", "tool_accuracy < 0.5",
        "--fail-on", "task_completion < 0.9",
    )
    assert code == 1
    err = capsys.readouterr().err
    assert "task_completion=0.750 < 0.9" in err
    assert "tool_accuracy" not in err


@pytest.mark.parametrize(
    "argv",
    [
        ("-d", "missing.yaml"),
        ("-d", "dataset.yaml", "--fail-on", "latency < 3"),
        ("-d", "dataset.yaml", "--fail-on", "task_completion < 0.9 or else"),
        ("-d", "dataset.yaml", "-a", "does_not_exist_mod:agent"),
        ("-d", "dataset.yaml", "-a", "no-colon"),
    ],
)
def test_eval_run_configuration_errors_exit_2(workdir, argv):
    assert run_cli(*argv) == 2


def test_eval_run_without_agent_uses_passthrough(workdir, capsys):
    assert run_cli("-d", "dataset.yaml", "-q", "--fail-on", "pass_rate < 0") == 0
    assert "passthrough placeholder" in capsys.readouterr().out


def test_eval_run_project_override(workdir):
    tmp_path, module = workdir
    run_cli("-d", "dataset.yaml", "-a", f"{module}:good_agent", "-q", "-p", "other", "--output-json", "r.json")
    assert json.loads((tmp_path / "r.json").read_text())["project"] == "other"


# ── reports ───────────────────────────────────────────────────────────────


def test_output_json_report(workdir):
    tmp_path, module = workdir
    code = run_cli(
        "-d", "dataset.yaml", "-a", f"{module}:flaky_agent", "-q",
        "--fail-on", "task_completion < 0.9", "--output-json", "report.json",
    )
    assert code == 1
    report = json.loads((tmp_path / "report.json").read_text())
    assert report["schema_version"] == 1
    assert report["gate_passed"] is False
    assert report["dataset_path"] == "dataset.yaml"
    assert report["pass_rate"] == 0.75
    assert report["task_completion_rate"] == 0.75
    assert report["thresholds"] == [
        {"expression": "task_completion < 0.9", "metric": "task_completion", "op": "<",
         "threshold": 0.9, "actual": 0.75, "failed": True},
    ]
    failed = [c for c in report["case_results"] if not c["passed"]]
    assert [c["case_id"] for c in failed] == ["refund_04"]
    assert failed[0]["failure_kind"] == "unknown"
    assert all("trace" not in c for c in report["case_results"])


def test_junit_xml_report(workdir):
    import xml.etree.ElementTree as ET

    tmp_path, module = workdir
    code = run_cli(
        "-d", "dataset.yaml", "-a", f"{module}:flaky_agent", "-q",
        "--fail-on", "task_completion < 0.9", "--fail-on", "tool_accuracy < 0.5", "--junit-xml", "junit.xml",
    )
    assert code == 1
    root = ET.parse(tmp_path / "junit.xml").getroot()  # nosemgrep: use-defused-xml-parse
    assert (root.tag, root.get("tests"), root.get("failures")) == ("testsuites", "6", "2")
    cases_suite, gate_suite = root.findall("testsuite")
    assert cases_suite.get("name") == "cortexops.payments-agent"
    failed = [tc for tc in cases_suite.findall("testcase") if tc.find("failure") is not None]
    assert [tc.get("name") for tc in failed] == ["refund_04"]
    assert failed[0].find("failure").get("type") == "unknown"
    assert failed[0].find("failure").text == "Agent produced no output"
    gate = {tc.get("name"): tc.find("failure") for tc in gate_suite.findall("testcase")}
    assert gate["fail_on: task_completion < 0.9"].get("message") == "task_completion=0.750 < 0.9"
    assert gate["fail_on: tool_accuracy < 0.5"] is None


def test_mean_score_in_reports(workdir):
    tmp_path, module = workdir
    run_cli("-d", "dataset.yaml", "-a", f"{module}:flaky_agent", "-q", "--output-json", "r.json", "--summary-md", "s.md")
    assert json.loads((tmp_path / "r.json").read_text())["mean_score"] == pytest.approx((3 * 100 + 75) / 4)
    assert "| Mean score | 93.8/100 |" in (tmp_path / "s.md").read_text()


def test_legacy_output_still_writes_raw_summary(workdir):
    tmp_path, module = workdir
    run_cli("-d", "dataset.yaml", "-a", f"{module}:good_agent", "-q", "-o", "raw.json")
    raw = json.loads((tmp_path / "raw.json").read_text())
    assert raw["total_cases"] == 4
    assert "gate_passed" not in raw
    assert raw["case_results"][0]["trace"] is not None


def test_summary_md_and_github_step_summary(workdir, monkeypatch):
    tmp_path, module = workdir
    step_summary = tmp_path / "step_summary.md"
    step_summary.write_text("existing\n")
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(step_summary))
    code = run_cli(
        "-d", "dataset.yaml", "-a", f"{module}:flaky_agent", "-q",
        "--fail-on", "task_completion < 0.9", "--fail-on", "tool_accuracy < 0.5", "--summary-md", "s.md",
    )
    assert code == 1
    md = (tmp_path / "s.md").read_text()
    assert md.startswith("## CortexOps eval gate: FAILED")
    assert "| Passed / failed | 3 / 1 |" in md
    assert "| Task completion | 75.0% |" in md
    assert "| `task_completion < 0.9` | 0.750 | FAILED |" in md
    assert "| `tool_accuracy < 0.5` | 1.000 | ok |" in md
    assert "| `refund_04` | unknown | 75 | Agent produced no output |" in md
    appended = step_summary.read_text()
    assert appended.startswith("existing\n## CortexOps eval gate: FAILED")


def test_no_step_summary_flag(workdir, monkeypatch):
    tmp_path, module = workdir
    step_summary = tmp_path / "step_summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(step_summary))
    run_cli("-d", "dataset.yaml", "-a", f"{module}:good_agent", "-q", "--no-step-summary")
    assert not step_summary.exists()


def test_custom_title(workdir):
    tmp_path, module = workdir
    run_cli("-d", "dataset.yaml", "-a", f"{module}:good_agent", "-q", "--summary-md", "s.md", "--title", "Refunds")
    md = (tmp_path / "s.md").read_text()
    assert md.startswith("## Refunds: PASSED")
    assert "_All cases passed._" in md


def _summary_with_failures(n: int) -> EvalSummary:
    cases = [
        CaseResult(
            case_id=f"case_{i}", passed=False, score=40.0, task_completion=False, tool_accuracy=0.0,
            latency_ms=12.0, latency_ok=True, failure_kind=FailureKind.TOOL_CALL_MISMATCH,
            failure_detail="expected a | b\nnewline " + "x" * 300,
        )
        for i in range(n)
    ]
    return EvalSummary(
        project="p", dataset_version=1, total_cases=n, passed=0, failed=n, warnings=0,
        task_completion_rate=0.0, tool_accuracy=0.0, latency_p50_ms=12.0, latency_p95_ms=1500.0,
        case_results=cases,
    )


def test_render_markdown_escapes_and_truncates():
    md = render_markdown(_summary_with_failures(3), [], max_failed_cases=2)
    assert "### Thresholds" not in md
    assert "### Failed cases (3)" in md
    assert "`case_2`" not in md
    assert "...and 1 more failed cases." in md
    row = next(line for line in md.splitlines() if line.startswith("| `case_0`"))
    assert "expected a \\| b newline" in row
    assert row.endswith("... |")
    assert "| Latency p50 / p95 | 12 ms / 1500 ms |" in md


def test_build_report_without_thresholds_passes():
    report = build_report(_summary_with_failures(1), [])
    assert report["gate_passed"] is True
    assert report["dataset_path"] is None


# ── --judge / --push ──────────────────────────────────────────────────────


def test_judge_flag_enables_llm_judge_for_cases_with_criteria(workdir, monkeypatch, capsys):
    tmp_path, module = workdir
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    data = {**DATASET, "cases": [{**DATASET["cases"][0], "judge_criteria": "mentions refund timeline"}]}
    (tmp_path / "judge.yaml").write_text(yaml.safe_dump(data))
    seen = []
    from cortexops import judge as judge_mod

    def fake_score(self, case, trace):
        seen.append(case.judge)
        return 100.0, None, None

    monkeypatch.setattr(judge_mod.LLMJudgeMetric, "score", fake_score)
    assert run_cli("-d", "judge.yaml", "-a", f"{module}:good_agent", "-q") == 0
    assert seen == []
    assert run_cli("-d", "judge.yaml", "-a", f"{module}:good_agent", "-q", "--judge") == 0
    assert seen == ["llm"]
    assert "keyword heuristic" in capsys.readouterr().out


def test_push_without_key_warns_and_keeps_exit_code(workdir, monkeypatch, capsys):
    _, module = workdir
    monkeypatch.setattr("cortexops.tracer._CREDENTIALS_FILE", workdir[0] / "no-creds")
    assert run_cli("-d", "dataset.yaml", "-a", f"{module}:good_agent", "-q", "--push") == 0
    assert "skipping upload" in capsys.readouterr().err


def test_push_uploads_summary(workdir, monkeypatch):
    _, module = workdir
    monkeypatch.setenv("CORTEXOPS_API_KEY", "cxo-test")
    pushed = []
    from cortexops.client import CortexClient

    def fail_project(self):
        raise RuntimeError("offline")

    monkeypatch.setattr(CortexClient, "project_for_key", fail_project)
    monkeypatch.setattr(CortexClient, "push_eval", lambda self, summary, **kw: pushed.append((self, summary)))
    assert run_cli("-d", "dataset.yaml", "-a", f"{module}:good_agent", "-q", "--push", "--base-url", "http://x") == 0
    client, summary = pushed[0]
    assert client.base_url == "http://x"
    assert client.api_key == "cxo-test"
    assert summary.total_cases == 4


def test_push_failure_does_not_fail_gate(workdir, monkeypatch, capsys):
    _, module = workdir
    monkeypatch.setenv("CORTEXOPS_API_KEY", "cxo-test")
    from cortexops.client import CortexClient

    def boom(self, *a, **kw):
        raise RuntimeError("503")

    monkeypatch.setattr(CortexClient, "project_for_key", lambda self: "payments-agent")
    monkeypatch.setattr(CortexClient, "push_eval", boom)
    assert run_cli("-d", "dataset.yaml", "-a", f"{module}:good_agent", "-q", "--push") == 0
    assert "eval upload failed: 503" in capsys.readouterr().err
