# Contributing to CortexOps

Thank you for your interest in contributing. CortexOps is an early-stage open-source project and we welcome all contributions — bug fixes, new metrics, documentation, and examples.

---

## Local dev setup

```bash
git clone https://github.com/ashishodu2023/cortexops
cd cortexops

# SDK (core library)
cd sdk
pip install -e ".[dev]"
pytest tests/ -v

# Backend (FastAPI + Celery)
cd ../backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# Run the example
cd ../examples/langgraph_payments
python run_eval.py
```

---

## Project structure

```
sdk/cortexops/          Core library — tracer, eval, metrics, CLI
  tracer.py             CortexTracer — wraps LangGraph / CrewAI / callable
  eval.py               EvalSuite — golden dataset runner
  metrics.py            Built-in metrics (task_completion, tool_accuracy, etc.)
  judge.py              LLM-as-judge metric (GPT-4o / any OpenAI-compatible API)
  cli.py                cortexops CLI
  models.py             Pydantic data models

backend/app/            FastAPI service
  routers/evals.py      POST /v1/evals, GET /v1/evals/{run_id}
  routers/traces.py     POST /v1/traces, GET /v1/traces
  routers/prompts.py    POST /v1/prompts, GET /v1/prompts/diff
  routers/keys.py       POST /v1/keys, DELETE /v1/keys/{id}
  services/alerting.py  Slack + webhook alerting
  worker/tasks.py       Celery async eval execution

examples/               Runnable demos
  langgraph_payments/   LangGraph payments agent + 9-case golden dataset
```

---

## How to add a custom metric

Subclass `cortexops.Metric` and implement `score()`:

```python
from cortexops import Metric, EvalCase, Trace, FailureKind

class CitationMetric(Metric):
    name = "citations"

    def score(self, case: EvalCase, trace: Trace):
        output = trace.output.get("output", "")
        has_citation = "[source:" in output.lower()
        if not has_citation:
            return 40.0, FailureKind.OUTPUT_FORMAT, "Response missing citation"
        return 100.0, None, None
```

Then pass it to `EvalSuite.run()`:

```python
EvalSuite.run(dataset="golden.yaml", agent=my_agent, extra_metrics=[CitationMetric()])
```

---

## Pull request checklist

- [ ] `pytest sdk/tests/ -v` passes (18/18)
- [ ] New metrics include at least 2 test cases
- [ ] New backend routes include a schema in `models/schemas.py`
- [ ] Commit messages follow: `type(scope): description` — e.g. `feat(metrics): add citation metric`
- [ ] Update `README.md` if adding a user-visible feature

---

## Good first issues

Label: `good first issue`

- Add `CrewAI` example in `examples/crewai_customer_support/`
- Add `AutoGen` example in `examples/autogen_research/`
- Add `planAdherence` metric that checks whether the agent followed its stated plan
- Add CLI `cortexops dashboard` command that opens the local web UI
- Write docs for the LLM-as-judge metric with example criteria
- Add `pytest-asyncio` tests for the FastAPI routes

---

## Code style

- Python: `ruff check` — no exceptions. Run `ruff check --fix` before committing.
- TypeScript: `eslint` + `prettier`.
- No `print()` in SDK code — use `logging`.
- All Pydantic models use `model_config = {"from_attributes": True}` for ORM compatibility.

---

## Contact

Open an issue for bugs or feature requests.  
For security vulnerabilities, email `security@cortexops.ai` — do not open a public issue.
