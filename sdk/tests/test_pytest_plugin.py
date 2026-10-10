"""pytest eval-gate plugin (@cortexops.eval_gate + pytest11 entry point)."""

import textwrap

import pytest

import cortexops
from cortexops import pytest_plugin

pytest_plugins = ["pytester"]

DATASET = {
    "version": 1,
    "project": "payments-agent",
    "cases": [
        {"id": "refund_01", "input": "status of REF-1", "expected_output_contains": ["approved"]},
        {"id": "refund_02", "input": "status of REF-2", "expected_output_contains": ["approved"]},
    ],
}


def good_agent(inp: dict) -> dict:
    return {"output": "approved"}


def half_agent(inp: dict) -> dict:
    if "REF-2" in inp["input"]:
        raise RuntimeError("lookup service down")
    return {"output": "approved"}


@pytest.fixture(autouse=True)
def _isolated_results(monkeypatch):
    monkeypatch.setattr(pytest_plugin, "_results", [])


def test_eval_gate_exported():
    assert cortexops.eval_gate is pytest_plugin.eval_gate


def test_passing_gate_records_result():
    @cortexops.eval_gate(DATASET)
    def gate():
        return good_agent

    assert gate() is None
    result = pytest_plugin.gate_results()[-1]
    assert result.passed
    assert result.summary.passed == 2


def test_failing_gate_fails_test_with_summary():
    @cortexops.eval_gate(DATASET, fail_on="task_completion < 0.9")
    def gate():
        return lambda inp: (_ for _ in ()).throw(RuntimeError("down"))

    with pytest.raises(pytest.fail.Exception) as exc:
        gate()
    assert "Eval gate failed: task_completion=0.000" in str(exc.value)
    assert "CortexOps eval — payments-agent" in str(exc.value)


def test_default_gate_requires_every_case_to_pass():
    @cortexops.eval_gate(DATASET)
    def gate():
        return half_agent

    with pytest.raises(pytest.fail.Exception, match="pass_rate=0.500"):
        gate()


def test_multiple_conditions_and_none():
    @cortexops.eval_gate(DATASET, fail_on=["task_completion < 0.4", "pass_rate < 0.4"])
    def lenient():
        return half_agent

    lenient()

    @cortexops.eval_gate(DATASET, fail_on=["task_completion < 0.4", "pass_rate < 0.9"])
    def strict():
        return half_agent

    with pytest.raises(pytest.fail.Exception) as exc:
        strict()
    assert "pass_rate=0.500" in str(exc.value)
    assert "task_completion" not in str(exc.value).split("\n\n")[0]

    @cortexops.eval_gate(DATASET, fail_on=None)
    def record_only():
        return half_agent

    record_only()
    assert pytest_plugin.gate_results()[-1].passed


def test_invalid_expression_rejected_at_decoration():
    with pytest.raises(ValueError, match="Unknown metric"):
        cortexops.eval_gate(DATASET, fail_on="accuracy < 0.9")
    with pytest.raises(ValueError, match="Invalid fail_on"):
        cortexops.eval_gate(DATASET, fail_on="task_completion < 0.9 or else")


def test_gate_must_return_agent():
    @cortexops.eval_gate(DATASET)
    def gate():
        pass

    with pytest.raises(TypeError, match="must return the agent"):
        gate()


def test_gate_applies_marker():
    @cortexops.eval_gate(DATASET)
    def gate():
        return good_agent

    assert any(m.name == pytest_plugin.MARKER for m in gate.pytestmark)


def test_plugin_end_to_end(pytester):
    pytester.makefile(
        ".yaml",
        golden=textwrap.dedent("""\
            version: 1
            project: payments-agent
            cases:
              - id: refund_01
                input: "status of REF-1"
                expected_output_contains: ["approved"]
            """),
    )
    pytester.makepyfile(
        textwrap.dedent("""\
            import pytest
            import cortexops

            @pytest.fixture
            def reply():
                return "approved"

            @cortexops.eval_gate("golden.yaml", fail_on="task_completion < 0.9")
            def test_good(reply):
                return lambda inp: {"output": reply}

            def _down(inp):
                raise RuntimeError("agent down")

            @cortexops.eval_gate("golden.yaml")
            def test_bad():
                return _down
            """)
    )
    # Loaded through the pytest11 entry point, as in a user's project
    result = pytester.runpytest_subprocess("--strict-markers")
    result.assert_outcomes(passed=1, failed=1)
    result.stdout.fnmatch_lines([
        "*CortexOps eval gates*",
        "PASS  test_good*1/1 cases*",
        "FAIL  test_bad*0/1 cases*",
    ])

    deselected = pytester.runpytest_subprocess("-m", "not cortexops_eval")
    deselected.assert_outcomes(deselected=2)
