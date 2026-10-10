# Evaluate and trace Google ADK agents with CortexOps

[CortexOps](https://getcortexops.com) is open-source reliability infrastructure for AI agents: it traces
agent runs, scores them against a golden dataset (task completion, tool accuracy, latency, hallucination
signals), and turns the result into a CI gate that blocks a pull request when the agent regresses. With the
Agent Development Kit (ADK) you run your agent through an ADK `Runner` inside a small adapter, wrap the
adapter with `CortexTracer.wrap()`, and every turn is traced with its input, final answer, tool calls,
latency, status, and the prompt version you deployed. The same adapter is what the CI gate calls.
Everything runs locally; the hosted dashboard is optional.

## Install

```bash
pip install "cortexops[pytest]" google-adk
export GOOGLE_API_KEY=...        # or configure Vertex AI as described in the ADK docs
```

## Trace an agent

CortexOps 0.5.1 recognises ADK agents, but its built-in ADK wrapper calls `agent.run(message)`, which ADK
2.x agents do not support (`TypeError: BaseNode.run() takes 1 positional argument but 2 were given`). Until
a Runner-based wrapper ships, run the agent through ADK's own `InMemoryRunner` in an adapter object with an
`invoke` method. `tracer.wrap()` treats any object with `invoke` generically:

- `invoke(inp)` is traced: the input, the returned dict, latency, and status (an exception marks the trace
  failed and is re-raised).
- Every other attribute passes through to the adapter untraced.

```python
# my_agent.py
import uuid

from google.adk.agents import Agent
from google.adk.runners import InMemoryRunner
from google.genai import types

from cortexops import CortexTracer

MODEL = "gemini-2.0-flash"
REFUNDS = {"REF-8821": "approved", "REF-9902": "pending"}


def lookup_refund(refund_id: str) -> dict:
    """Look up the status of a refund by its ID."""
    return {"status": REFUNDS.get(refund_id, "not found")}


root_agent = Agent(
    name="refund_assistant",
    model=MODEL,
    instruction="Answer refund questions. Use lookup_refund for any refund ID such as REF-1234.",
    tools=[lookup_refund],
)


class RefundAssistant:
    """Runs one ADK turn per call in a fresh session and returns the answer and tool calls."""

    def __init__(self, agent: Agent) -> None:
        self.runner = InMemoryRunner(agent=agent, app_name="refund_assistant")

    def invoke(self, inp: dict) -> dict:
        session = self.runner.session_service.create_session_sync(
            app_name="refund_assistant", user_id="eval", session_id=str(uuid.uuid4()),
        )
        message = types.Content(role="user", parts=[types.Part(text=inp["input"])])
        answer, tool_calls = "", []
        for event in self.runner.run(user_id="eval", session_id=session.id, new_message=message):
            tool_calls += [call.name for call in event.get_function_calls()]
            if event.is_final_response() and event.content and event.content.parts:
                answer = "".join(part.text or "" for part in event.content.parts)
        return {"output": answer, "tool_calls_made": tool_calls}


tracer = CortexTracer(project="refund-assistant")   # local-only unless CORTEXOPS_API_KEY is set
traced_agent = tracer.wrap(RefundAssistant(root_agent))
```

Each call appends a `Trace` to `tracer.traces()`; `tracer.last_trace()` returns the latest one. Set
`CORTEXOPS_API_KEY` (or run `cortexops login`) to also send traces to the hosted dashboard, and
`CORTEXOPS_SAMPLE_RATE=0.1` to sample in production (failed runs are always kept).

## Tag traces with a prompt version

When you change the instruction, tools, or model, tag traces so regressions can be attributed to a prompt
version. `set_prompt` applies to every later run; `use_prompt` scopes a version to a block.

```python
# my_agent.py (continued)
tracer.set_prompt("refund-instruction", "v1")

if __name__ == "__main__":
    with tracer.use_prompt("refund-instruction", "v2"):
        result = traced_agent.invoke({"input": "What is the status of refund REF-8821?"})
    trace = tracer.last_trace()
    print(result["output"], result["tool_calls_made"])
    print(trace.status.value, trace.prompt_name, trace.prompt_version, f"{trace.total_latency_ms:.0f}ms")
```

## Gate the agent in CI

`EvalSuite` calls `agent.invoke({"input": "<case input>"})` and scores the returned
`{"output": ..., "tool_calls_made": [...]}`, which is exactly what the adapter returns, so the traced
adapter is the eval agent:

```python
# my_agent.py (continued)
eval_agent = traced_agent
```

Describe the expected behaviour in a golden dataset:

```yaml
# golden.yaml
version: 1
project: refund-assistant
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
def test_refund_assistant():
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
      - run: pip install "cortexops[pytest]" google-adk
      - run: pytest test_my_agent.py -v
        env:
          GOOGLE_API_KEY: ${{ secrets.GOOGLE_API_KEY }}
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
