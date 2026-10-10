"""Open golden datasets under datasets/: schema, coverage, reference agents, and gate sensitivity."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest
import yaml

import cortexops
from cortexops import EvalDataset, EvalSuite, FailureKind, pytest_plugin
from cortexops.dataset import GoldenDataset
from cortexops.eval import EvalThresholdError

DATASETS_DIR = Path(__file__).resolve().parents[2] / "datasets"
if not DATASETS_DIR.is_dir():
    pytest.skip("datasets/ is not part of this checkout (e.g. sdist)", allow_module_level=True)

DATASETS = {
    "customer_support": "support_agent",
    "rag_qa": "rag_agent",
    "tool_workflows": "workflow_agent",
}
GATE = ["pass_rate < 1.0", "task_completion < 1.0", "tool_accuracy < 1.0"]
ALLOWED_KEYS = {
    "id", "input", "expected_tool_calls", "expected_output_contains", "expected_output_not_contains",
    "max_latency_ms", "judge", "judge_criteria", "tags",
}
CATEGORY_TAGS = {"happy_path", "edge_case", "multi_step", "ambiguous", "adversarial", "refusal"}
REQUIRED_COVERAGE = CATEGORY_TAGS | {"latency_budget", "prompt_injection"}
DEGRADED = ["missing_tool", "flaky_tool", "injection_susceptible"]


def _load_module(path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[path.stem] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def agents() -> dict[str, ModuleType]:
    return {name: _load_module(DATASETS_DIR / name / f"{module}.py") for name, module in DATASETS.items()}


@pytest.fixture
def local_tracer(monkeypatch):
    monkeypatch.delenv("CORTEXOPS_API_KEY", raising=False)
    tracer = cortexops.CortexTracer(project="datasets-test", sample_rate=1.0)
    tracer.api_key = None
    return tracer


def _gate_failures(summary) -> list[str]:
    failures = []
    for condition in GATE:
        try:
            EvalSuite._check_threshold(summary, condition)
        except EvalThresholdError as exc:
            failures.append(str(exc))
    return failures


@pytest.mark.parametrize("name", sorted(DATASETS))
def test_dataset_schema(name, agents):
    path = DATASETS_DIR / name / "golden.yaml"
    raw = yaml.safe_load(path.read_text())
    ds = EvalSuite._load_dataset(path)

    assert isinstance(ds, EvalDataset)
    assert raw["name"] and raw["project"] == ds.project and ds.version == 1 and ds.description
    assert 20 <= len(ds.cases) <= 30
    ids = [c.id for c in ds.cases]
    assert len(ids) == len(set(ids)), "duplicate case ids"
    assert all(i.startswith(ids[0].split("_")[0] + "_") for i in ids), "case ids share a dataset prefix"

    tools = set(agents[name].TOOLS)
    for raw_case, case in zip(raw["cases"], ds.cases, strict=True):
        assert set(raw_case) <= ALLOWED_KEYS, f"{case.id}: unknown keys {set(raw_case) - ALLOWED_KEYS}"
        assert case.tags and set(case.tags) & CATEGORY_TAGS, f"{case.id}: needs a category tag"
        assert case.max_latency_ms and case.max_latency_ms > 0, f"{case.id}: needs a latency budget"
        assert case.expected_output_contains or case.expected_output_not_contains, f"{case.id}: no output check"
        assert set(case.expected_tool_calls) <= tools, f"{case.id}: unknown tools"
        assert case.judge == "rule"
        if isinstance(case.input, dict):
            assert isinstance(case.input.get("input"), str)

    covered = {t for c in ds.cases for t in c.tags}
    assert REQUIRED_COVERAGE <= covered, f"missing tags: {REQUIRED_COVERAGE - covered}"
    assert all(c.max_latency_ms <= 1000 for c in ds.cases if "latency_budget" in c.tags)

    golden = GoldenDataset.load(path)
    assert len(golden.filter("adversarial")) >= 3


@pytest.mark.parametrize("name", sorted(DATASETS))
def test_reference_agent_is_clean(name, agents, local_tracer):
    agent = agents[name].build_agent(tracer=local_tracer)
    summary = EvalSuite.run(DATASETS_DIR / name / "golden.yaml", agent, verbose=False)

    dirty = {r.case_id: r.failure_detail for r in summary.case_results if r.failure_kind is not None}
    assert dirty == {}
    assert _gate_failures(summary) == []

    traces = local_tracer.traces()
    assert len(traces) == summary.total_cases
    assert {t.prompt_name for t in traces} == {agents[name].PROMPT_NAME}
    recorded = {tc.name for t in traces for tc in t.tool_calls()}
    expected = {tool for c in EvalSuite._load_dataset(DATASETS_DIR / name / "golden.yaml").cases
                for tool in c.expected_tool_calls}
    assert expected <= recorded


@pytest.mark.parametrize("name", sorted(DATASETS))
@pytest.mark.parametrize("variant", DEGRADED)
def test_degraded_variant_fails_gate(name, variant, agents, local_tracer):
    agent = agents[name].build_agent(variant, tracer=local_tracer)
    summary = EvalSuite.run(DATASETS_DIR / name / "golden.yaml", agent, verbose=False)

    assert _gate_failures(summary), f"{variant} slipped through the {name} gate"
    assert any(r.failure_kind is not None for r in summary.case_results)


@pytest.mark.parametrize("name", sorted(DATASETS))
def test_slow_tool_breaches_latency_budget(name, agents, local_tracer):
    """Time-scaled (1/50) run of the latency_budget cases so CI stays fast."""
    raw = yaml.safe_load((DATASETS_DIR / name / "golden.yaml").read_text())
    raw["cases"] = [dict(c, max_latency_ms=c["max_latency_ms"] / 50) for c in raw["cases"]
                    if "latency_budget" in c["tags"]]
    agent = agents[name].build_agent("slow_tool", tracer=local_tracer, slow_delay_s=2.0 / 50)
    summary = EvalSuite.run(raw, agent, verbose=False)

    timeouts = [r for r in summary.case_results if r.failure_kind == FailureKind.TIMEOUT]
    assert timeouts and all(not r.passed for r in timeouts)
    assert _gate_failures(summary)


@pytest.mark.parametrize("name", sorted(DATASETS))
def test_dataset_pytest_gate(name, agents, monkeypatch):
    monkeypatch.setattr(pytest_plugin, "_results", [])
    monkeypatch.delenv("CORTEXOPS_API_KEY", raising=False)
    module = _load_module(DATASETS_DIR / name / f"test_{name}.py")
    gate = getattr(module, f"test_{name}_reference_agent")

    assert gate() is None
    result = pytest_plugin.gate_results()[-1]
    assert result.passed and result.summary.total_cases == result.summary.passed


def test_unknown_variant_rejected(agents):
    for module in agents.values():
        with pytest.raises(ValueError, match="unknown variant"):
            module.build_agent("nope")
