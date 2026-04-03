# CortexOps

**Reliability infrastructure for AI agents.**  
Evaluate · Observe · Operate — for LangGraph, CrewAI, and AutoGen.

[![PyPI version](https://img.shields.io/pypi/v/cortexops.svg)](https://pypi.org/project/cortexops/)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![CI](https://github.com/ashishodu2023/cortexops/actions/workflows/eval.yml/badge.svg)](https://github.com/ashishodu2023/cortexops/actions/workflows/eval.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

[Website](https://getcortexops.com) · [PyPI](https://pypi.org/project/cortexops) · [Docs](https://github.com/ashishodu2023/cortexops)
---

## The problem

You deployed an agent. You have no idea if it regressed overnight.

No standard eval format. No failure traces. No CI gate before the next prompt change ships.  
CortexOps fixes that.

---

## Quickstart

```bash
pip install cortexops
```

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
# CortexOps eval — payments-agent
#   Cases           : 9  (7 passed, 2 failed)
#   Task completion : 91.4%
#   Tool accuracy   : 97.0/100
#   Latency p50/p95 : 42ms / 187ms
#   Failed cases:
#     - escalation_router: tool_call_mismatch (score 41)
```

---

## Golden dataset format

Define test cases in YAML. Run them locally or in CI.

```yaml
# golden_v1.yaml
version: 1
project: payments-agent

cases:
  - id: refund_lookup_01
    input: "What is the status of refund REF-8821?"
    expected_tool_calls: [lookup_refund]
    expected_output_contains: ["approved", "REF-8821"]
    max_latency_ms: 3000

  - id: dispute_escalation_01
    input: "I was charged twice — this is unauthorized"
    expected_tool_calls: [classify_dispute, route_escalation]
    expected_output_contains: ["escalated"]
    max_latency_ms: 5000
```

---

## CI eval gate

Add to `.github/workflows/eval.yml`:

```yaml
- name: CortexOps eval gate
  run: |
    python examples/langgraph_payments/run_eval.py \
      --dataset golden_v1.yaml \
      --fail-on "task_completion < 0.90"
```

If the eval drops below threshold, the job exits non-zero and the PR is blocked.

---

## Repo structure

```
cortexops/
├── sdk/                        # pip install cortexops
│   ├── cortexops/
│   │   ├── tracer.py           # CortexTracer — wraps LangGraph / CrewAI
│   │   ├── eval.py             # EvalSuite — golden dataset runner
│   │   ├── metrics.py          # task_completion, tool_accuracy, latency, hallucination
│   │   ├── models.py           # Pydantic data models
│   │   └── client.py           # HTTP client for hosted API
│   └── tests/
├── backend/                    # FastAPI + Celery + SQLite/Postgres
│   ├── app/
│   │   ├── main.py
│   │   ├── routers/            # /v1/evals, /v1/traces
│   │   ├── models/             # DB records + API schemas
│   │   └── worker/             # Celery async eval tasks
│   └── Dockerfile
├── frontend/                   # React + TypeScript dashboard
├── examples/
│   └── langgraph_payments/     # Full runnable demo
│       ├── agent.py
│       ├── golden_v1.yaml
│       └── run_eval.py
└── docker-compose.yml
```

---

## Run the full stack locally

```bash
git clone https://github.com/ashishodu2023/cortexops
cd cortexops

# Start API + worker + Redis
docker compose up --build

# In another terminal — run the demo eval
cd examples/langgraph_payments
pip install -e ../../sdk/
python run_eval.py

# API docs at http://localhost:8000/docs
# Dashboard at http://localhost:3000
```

---

## Supported frameworks

| Framework | Status |
|---|---|
| LangGraph | Stable |
| CrewAI | Stable |
| AutoGen | Beta |
| LlamaIndex agents | Coming soon |
| Custom callables | Supported via `CortexTracer.wrap()` |

---

## Built-in metrics

| Metric | What it checks |
|---|---|
| `task_completion` | Agent produced a valid, non-error output |
| `tool_accuracy` | Expected tool calls were actually made |
| `latency` | Response within `max_latency_ms` budget |
| `hallucination` | Detects fabrication signals in output |

Add custom metrics by subclassing `cortexops.Metric`.

---

## Contributing

```bash
git clone https://github.com/ashishodu2023/cortexops
cd cortexops/sdk
pip install -e ".[dev]"
pytest tests/ -v
```

See [CONTRIBUTING.md](CONTRIBUTING.md). Issues labeled `good first issue` are a great place to start.

---

## Citation

```bibtex
@software{cortexops2025,
  author  = {Ashish, et al.},
  title   = {CortexOps: Reliability Infrastructure for AI Agents},
  year    = {2025},
  url     = {https://github.com/ashishodu2023/cortexops},
}
```

---

## License

MIT — see [LICENSE](LICENSE).

---

<p align="center">
  <a href="https://cortexops.ai">cortexops.ai</a> ·
  <a href="https://github.com/ashishodu2023/cortexops/issues">Issues</a> ·
  <a href="https://github.com/ashishodu2023/cortexops/discussions">Discussions</a>
</p>
