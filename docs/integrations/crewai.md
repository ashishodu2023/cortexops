# Evaluate and trace CrewAI crews with CortexOps

[CortexOps](https://getcortexops.com) is open-source reliability infrastructure for AI agents: it traces
agent runs, scores them against a golden dataset (task completion, tool accuracy, latency, hallucination
signals), and turns the result into a CI gate that blocks a pull request when the agent regresses. With
CrewAI you wrap a `Crew` once with `CortexTracer.wrap()`; every `kickoff` is traced with its inputs, final
output, latency, status, and the prompt version you deployed, and the same crew can be gated in CI with a
pytest decorator or the `cortexops` CLI. Everything runs locally; the hosted dashboard is optional.

## Install

```bash
pip install "cortexops[pytest]" crewai
export OPENAI_API_KEY=sk-...
```

## Trace a crew

`tracer.wrap(crew)` detects a `crewai.Crew` and returns a wrapper:

- `kickoff(inputs=...)` is traced: the `inputs` dict, `str(result)` of the `CrewOutput`, latency, and status.
- `kickoff_async`, `kickoff_for_each` and every other attribute pass through to the crew untraced.

```python
# my_agent.py
from crewai import Agent, Crew, Task
from crewai.tools import tool

from cortexops import CortexTracer

LLM = "gpt-4o-mini"
REFUNDS = {"REF-8821": "approved", "REF-9902": "pending"}
tool_calls: list[str] = []   # read by eval_agent below


@tool("lookup_refund")
def lookup_refund(refund_id: str) -> str:
    """Look up the status of a refund by its ID."""
    tool_calls.append("lookup_refund")
    return REFUNDS.get(refund_id, "not found")


support = Agent(
    role="Refund support specialist",
    goal="Answer refund questions accurately, using lookup_refund for refund IDs",
    backstory="You work on the payments support desk.",
    tools=[lookup_refund],
    llm=LLM,
)
answer = Task(
    description="Answer the customer's message: {question}",
    expected_output="A one-sentence answer for the customer",
    agent=support,
)
crew = Crew(agents=[support], tasks=[answer])

tracer = CortexTracer(project="refund-crew")   # local-only unless CORTEXOPS_API_KEY is set
traced_crew = tracer.wrap(crew)
```

Each call appends a `Trace` to `tracer.traces()`; `tracer.last_trace()` returns the latest one. Set
`CORTEXOPS_API_KEY` (or run `cortexops login`) to also send traces to the hosted dashboard, and
`CORTEXOPS_SAMPLE_RATE=0.1` to sample in production (failed runs are always kept).

## Tag traces with a prompt version

When you change a role, goal, task description, or model, tag traces so regressions can be attributed to a
prompt version. `set_prompt` applies to every later run; `use_prompt` scopes a version to a block.

```python
# my_agent.py (continued)
tracer.set_prompt("refund-crew", "v1")

if __name__ == "__main__":
    with tracer.use_prompt("refund-crew", "v2"):
        result = traced_crew.kickoff(inputs={"question": "What is the status of refund REF-8821?"})
    trace = tracer.last_trace()
    print(result.raw)
    print(trace.status.value, trace.prompt_name, trace.prompt_version, f"{trace.total_latency_ms:.0f}ms")
```

## Gate the crew in CI

`EvalSuite` calls your agent with `{"input": "<case input>"}` and scores the returned
`{"output": ..., "tool_calls_made": [...]}`. The tools append to `tool_calls` themselves; CrewAI's event bus
(`ToolUsageFinishedEvent`) also reports tool usage, but it runs sync handlers on a thread pool, so the list
may not be complete when `kickoff` returns.

```python
# my_agent.py (continued)
def eval_agent(inp: dict) -> dict:
    tool_calls.clear()
    result = traced_crew.kickoff(inputs={"question": inp["input"]})
    return {"output": result.raw, "tool_calls_made": list(tool_calls)}
```

Describe the expected behaviour in a golden dataset:

```yaml
# golden.yaml
version: 1
project: refund-crew
cases:
  - id: refund_status
    input: "What is the status of refund REF-8821?"
    expected_tool_calls: [lookup_refund]
    expected_output_contains: ["REF-8821", "approved"]
    max_latency_ms: 30000
    tags: [happy_path]
  - id: unknown_refund
    input: "Check refund REF-0000 please"
    expected_tool_calls: [lookup_refund]
    expected_output_contains: ["not found"]
    max_latency_ms: 30000
    tags: [edge_case]
  - id: greeting
    input: "hello"
    expected_output_not_contains: ["error:", "traceback"]
    max_latency_ms: 20000
    tags: [edge_case]
```

**pytest.** The plugin is registered automatically when `cortexops` is installed. The decorated test
returns the agent; the test fails when any `fail_on` condition is true and the run summary is printed.

```python
# test_my_agent.py
import cortexops
from my_agent import eval_agent


@cortexops.eval_gate("golden.yaml", fail_on=["task_completion < 0.9", "tool_accuracy < 0.9"])
def test_refund_crew():
    return eval_agent
```

**CLI.** `cortexops eval run` exits non-zero when the threshold is crossed or any case fails.
`PYTHONPATH=.` makes `my_agent` importable for the `cortexops` console script.

```bash
pytest test_my_agent.py -v
PYTHONPATH=. cortexops eval run --dataset golden.yaml --agent my_agent:eval_agent --fail-on "task_completion < 0.9"
```

A GitHub Actions job:

```yaml
name: crew-evals
on: [pull_request]
jobs:
  eval:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install "cortexops[pytest]" crewai
      - run: pytest test_my_agent.py -v
        env:
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
```

Thresholds to start from: a case passes when the mean of its four metric scores is at least 80, so gate on
`task_completion` and `tool_accuracy` as well as `pass_rate`. Larger ready-made datasets (customer support,
RAG QA, multi-step tool workflows; 26-30 cases each) are in the
[CortexOps open golden datasets](https://github.com/ashishodu2023/cortexops/tree/main/datasets).

## Links

- Website: [getcortexops.com](https://getcortexops.com)
- Documentation: [docs.getcortexops.com](https://docs.getcortexops.com)
- Source: [github.com/ashishodu2023/cortexops](https://github.com/ashishodu2023/cortexops)
- Package: [pypi.org/project/cortexops](https://pypi.org/project/cortexops/)
