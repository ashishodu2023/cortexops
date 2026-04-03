# CortexOps

**Reliability infrastructure for AI agents.**  
Evaluate · Observe · Operate — for LangGraph, CrewAI, and AutoGen.

[![PyPI version](https://img.shields.io/pypi/v/cortexops.svg)](https://pypi.org/project/cortexops/)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![CI](https://github.com/ashishodu2023/cortexops/actions/workflows/eval.yml/badge.svg)](https://github.com/ashishodu2023/cortexops/actions/workflows/eval.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://github.com/ashishodu2023/cortexops/blob/main/LICENSE)

---

## The problem

You deployed an agent. You have no idea if it regressed overnight.

No standard eval format. No failure traces. No CI gate before the next prompt change ships.  
CortexOps fixes that.

---

## Install

```bash
pip install cortexops

# With HTTP client (for pushing traces to hosted API):
pip install cortexops[http]

# With LLM judge support:
pip install cortexops[llm]
```

---

## Quickstart

```python
from cortexops import CortexTracer, EvalSuite

# Wrap your LangGraph app — zero refactor required
tracer = CortexTracer(project="payments-agent")
graph  = tracer.wrap(your_langgraph_app)

# Run evaluations against a golden dataset
results = EvalSuite.run(
    dataset="golden_v1.yaml",
    agent=graph,
)
print(results.summary())
```

---

## Golden dataset (YAML)

```yaml
version: 1
project: payments-agent

cases:
  - id: refund_lookup_01
    input: "What is the status of refund REF-8821?"
    expected_tool_calls: [lookup_refund]
    expected_output_contains: ["approved", "REF-8821"]
    max_latency_ms: 3000

  - id: open_ended_explanation_01
    input: "Why was my refund rejected?"
    judge: llm
    judge_criteria: >
      The response must explain the rejection reason clearly,
      be empathetic, and offer a concrete next step. No jargon.
```

---

## CI gate

```bash
cortexops eval run \
  --dataset golden_v1.yaml \
  --fail-on "task_completion < 0.90"
```

Exits non-zero if the threshold is not met — blocks the PR.

---

## Built-in metrics

| Metric | What it checks |
|---|---|
| `task_completion` | Non-empty, non-error output with expected content |
| `tool_accuracy` | Expected tool calls were actually made |
| `latency` | Response within `max_latency_ms` budget |
| `hallucination` | Fabrication signals in output |
| `llm_judge` | GPT-4o scores against natural-language criteria |

---

## Links

- **Docs**: [docs.cortexops.ai](https://docs.cortexops.ai)
- **Repo**: [github.com/ashishodu2023/cortexops](https://github.com/ashishodu2023/cortexops)
- **Issues**: [GitHub Issues](https://github.com/ashishodu2023/cortexops/issues)
