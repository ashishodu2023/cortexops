# Evaluate and trace OpenAI Agents SDK agents with CortexOps

[CortexOps](https://getcortexops.com) is open-source reliability infrastructure for AI agents: it traces
agent runs, scores them against a golden dataset (task completion, tool accuracy, latency, hallucination
signals), and turns the result into a CI gate that blocks a pull request when the agent regresses. With the
OpenAI Agents SDK you wrap an `Agent` once with `CortexTracer.wrap()`; the wrapper runs it through `Runner`
and traces each run with its prompt, result, latency, status, and the prompt version you deployed. The same
agent can then be gated in CI with a pytest decorator or the `cortexops` CLI. CortexOps runs alongside the
Agents SDK's built-in tracing; it does not replace or disable it.

## Install

```bash
pip install "cortexops[pytest]" openai-agents
export OPENAI_API_KEY=sk-...
```

## Trace an agent

`tracer.wrap(agent)` detects an `agents.Agent` and returns a wrapper:

- `run_sync(prompt, **kwargs)` calls `Runner.run_sync(agent, prompt, **kwargs)` and traces it: the prompt, `str(result)`, latency, and status.
- `await run(prompt, **kwargs)` is traced too; it executes `Runner.run_sync` in a worker thread, so it is safe to call from async code.
- Every other attribute (`name`, `tools`, `clone`, ...) passes through to the agent.

```python
# my_agent.py
from agents import Agent, function_tool

from cortexops import CortexTracer

MODEL = "gpt-4o-mini"
REFUNDS = {"REF-8821": "approved", "REF-9902": "pending"}


@function_tool
def lookup_refund(refund_id: str) -> str:
    """Look up the status of a refund by its ID."""
    return REFUNDS.get(refund_id, "not found")


agent = Agent(
    name="Refund agent",
    instructions="You answer refund questions. Use lookup_refund for refund IDs.",
    tools=[lookup_refund],
    model=MODEL,
)

tracer = CortexTracer(project="refund-agent")   # local-only unless CORTEXOPS_API_KEY is set
traced_agent = tracer.wrap(agent)
```

Each call appends a `Trace` to `tracer.traces()`; `tracer.last_trace()` returns the latest one. Set
`CORTEXOPS_API_KEY` (or run `cortexops login`) to also send traces to the hosted dashboard, and
`CORTEXOPS_SAMPLE_RATE=0.1` to sample in production (failed runs are always kept).

## Tag traces with a prompt version

When you change `instructions` or the model, tag traces so regressions can be attributed to a prompt version.
`set_prompt` applies to every later run; `use_prompt` scopes a version to a block.

```python
# my_agent.py (continued)
tracer.set_prompt("refund-instructions", "v1")

if __name__ == "__main__":
    with tracer.use_prompt("refund-instructions", "v2"):
        result = traced_agent.run_sync("What is the status of refund REF-8821?")
    trace = tracer.last_trace()
    print(result.final_output)
    print(trace.status.value, trace.prompt_name, trace.prompt_version, f"{trace.total_latency_ms:.0f}ms")
```

## Gate the agent in CI

`EvalSuite` calls your agent with `{"input": "<case input>"}` and scores the returned
`{"output": ..., "tool_calls_made": [...]}`. Tool calls come from the run's new items:

```python
# my_agent.py (continued)
def eval_agent(inp: dict) -> dict:
    result = traced_agent.run_sync(inp["input"])
    tool_calls = [item.raw_item.name for item in result.new_items if item.type == "tool_call_item"]
    return {"output": result.final_output, "tool_calls_made": tool_calls}
```

Describe the expected behaviour in a golden dataset:

```yaml
# golden.yaml
version: 1
project: refund-agent
cases:
  - id: refund_status
    input: "What is the status of refund REF-8821?"
    expected_tool_calls: [lookup_refund]
    expected_output_contains: ["REF-8821", "approved"]
    max_latency_ms: 15000
    tags: [happy_path]
  - id: unknown_refund
    input: "Check refund REF-0000 please"
    expected_tool_calls: [lookup_refund]
    expected_output_contains: ["not found"]
    max_latency_ms: 15000
    tags: [edge_case]
  - id: greeting
    input: "hello"
    expected_output_not_contains: ["error:", "traceback"]
    max_latency_ms: 10000
    tags: [edge_case]
```

**pytest.** The plugin is registered automatically when `cortexops` is installed. The decorated test
returns the agent; the test fails when any `fail_on` condition is true and the run summary is printed.

```python
# test_my_agent.py
import cortexops
from my_agent import eval_agent


@cortexops.eval_gate("golden.yaml", fail_on=["task_completion < 0.9", "tool_accuracy < 0.9"])
def test_refund_agent():
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
name: agent-evals
on: [pull_request]
jobs:
  eval:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install "cortexops[pytest]" openai-agents
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
