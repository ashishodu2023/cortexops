"""EvalSuite summary rendering."""

from cortexops import EvalSuite
from cortexops.models import EvalCase, EvalDataset


def test_summary_string_renders():
    ds = EvalDataset(
        version=1,
        project="test-agent",
        cases=[EvalCase(id="c1", input="hi", expected_output_contains=["hi"])],
    )

    def agent(inp: dict) -> dict:
        return {"output": inp.get("input", "")}

    summary = EvalSuite.run(dataset=ds, agent=agent, verbose=False)
    text = summary.summary()
    assert "test-agent" in text
    assert "Task completion" in text
