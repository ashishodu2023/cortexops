# Contributing to CortexOps

Thank you for your interest in contributing. CortexOps is an open-source AI agent observability platform — tracing, evaluation, and monitoring for LLM agents in production. Every contribution, large or small, makes it better for the engineers who depend on it.

---

## Quick start

1. Find an issue: [github.com/ashishodu2023/cortexops/issues](https://github.com/ashishodu2023/cortexops/issues)
2. Filter by **good first issue** if you are new to the codebase
3. Comment "I'll take this one" so others know it is claimed
4. Fork the repo, make your changes, open a PR

That is it. No CLA, no approval process for small changes.

---

## What we need help with

### Good first issues (1-4 hours)
- Framework examples: Gemini, Azure OpenAI, DSPy, Smolagents, Haystack
- Documentation: quickstart tutorial, environment variable reference, why-observability guide
- Docker Compose for self-hosted deployment
- OpenTelemetry export examples: Jaeger, Grafana Tempo
- Error message improvements
- Type hint coverage

### Intermediate (4-8 hours)
- pytest plugin for eval gates
- Trace sampling configuration
- GitHub Actions job summary output
- LLM judge cost tracking

Browse all open issues: [github.com/ashishodu2023/cortexops/issues](https://github.com/ashishodu2023/cortexops/issues)

---

## Development setup

### Prerequisites

- Python 3.10 or later
- Node.js 18+ (for frontend only)
- Docker (for integration tests)
- A CortexOps API key — free at [getcortexops.com](https://getcortexops.com)

### Clone and install

```bash
git clone https://github.com/ashishodu2023/cortexops.git
cd cortexops

# Install SDK in development mode
cd sdk
pip install -e ".[dev]"
cd ..

# Install backend dependencies
cd backend
pip install -r requirements.txt
cd ..
```

### Run tests

```bash
# SDK tests
cd sdk
pytest tests/ -v

# Backend tests
cd backend
pytest tests/ -v

# Run with coverage
pytest tests/ -v --cov=cortexops --cov-report=term-missing
```

### Lint and format

```bash
# Run ruff (linter + formatter)
cd sdk
ruff check cortexops/ --line-length 121
ruff format cortexops/ --line-length 121

# Backend
cd backend
ruff check app/ --line-length 121
```

All CI checks must pass before a PR is merged. Run lint locally before pushing to save time.

### Run the backend locally

```bash
cd backend
cp .env.example .env
# Edit .env with your local settings

uvicorn app.main:app --reload --port 8000
# API docs: http://localhost:8000/docs
```

---

## Repository structure

```
cortexops/
├── sdk/                    ← Python SDK (pip install cortexops)
│   ├── cortexops/
│   │   ├── __init__.py     ← Public API surface
│   │   ├── tracer.py       ← CortexTracer — main instrumentation class
│   │   ├── eval.py         ← EvalSuite — evaluation framework
│   │   ├── judge.py        ← LLMJudge, LLMJudgeMetric — LLM-as-judge
│   │   ├── dataset.py      ← GoldenDataset — eval dataset management
│   │   └── cli.py          ← cortexops CLI commands
│   └── tests/              ← SDK test suite (pytest)
│
├── backend/                ← FastAPI backend (api.getcortexops.com)
│   ├── app/
│   │   ├── main.py         ← FastAPI app and router registration
│   │   ├── routers/        ← API route handlers
│   │   ├── models/         ← SQLAlchemy models
│   │   └── auth.py         ← API key authentication
│   └── tests/              ← Backend test suite
│
├── examples/               ← Working examples (add yours here)
│   ├── langgraph_basic/    ← Reference implementation
│   ├── crewai_basic/
│   └── ...
│
├── .github/
│   └── workflows/
│       ├── security.yml    ← Security + quality CI pipeline
│       └── ...
│
└── CONTRIBUTING.md         ← You are here
```

---

## Adding a framework example

The most common contribution is a new framework example. Follow this pattern:

### 1. Create the directory

```bash
mkdir examples/your_framework_basic
cd examples/your_framework_basic
```

### 2. Create the agent file

```python
# examples/your_framework_basic/agent.py

from cortexops import CortexTracer
import os

tracer = CortexTracer(
    api_key=os.getenv("CORTEXOPS_API_KEY", ""),
    project="your-framework-example",
)

# Your framework-specific agent code here
# Wrap the entry point with tracer.wrap()
agent = tracer.wrap(your_agent_object)

if __name__ == "__main__":
    result = agent.run("Hello, world!")
    print(result)
```

### 3. Add a requirements file

```
# examples/your_framework_basic/requirements.txt
cortexops>=0.4.0
your-framework>=x.y.z
```

### 4. Write a README

```markdown
# Your Framework + CortexOps

Three lines to trace a [Your Framework] agent.

## Setup

pip install -r requirements.txt
export CORTEXOPS_API_KEY=your-key  # free at getcortexops.com

## Run

python agent.py

## What you will see

A trace in your CortexOps dashboard showing every step
of the agent execution.
```

### 5. Test it

Run the example from scratch in a clean virtual environment. If it works from zero setup, it is ready to PR.

---

## Pull request checklist

Before opening a PR:

- [ ] Tests pass locally: `pytest tests/ -v`
- [ ] Lint passes: `ruff check . --line-length 121`
- [ ] New code has test coverage (for SDK and backend changes)
- [ ] README or docs updated if behaviour changed
- [ ] Example is tested from a clean environment (for example contributions)

PR title format:

```
feat: add Gemini Google ADK tracing example
fix: improve error message on invalid API key
docs: add quickstart tutorial
chore: bump python-multipart to 0.0.27
```

---

## Code style

- Python 3.10+ syntax throughout
- Type hints on all public functions
- Docstrings on all public classes and methods
- No line longer than 121 characters (ruff enforces this)
- Imports sorted by ruff (run `ruff check --fix` to auto-sort)
- No `print()` in library code — use `logging` instead
- Prefer `deque` over `list` for stack implementations

---

## Tests

Every SDK change needs a test. Tests live in `sdk/tests/`.

```python
# sdk/tests/test_your_feature.py

def test_your_feature_does_what_it_should():
    from cortexops import YourNewClass
    result = YourNewClass().do_thing()
    assert result.worked == True
```

Run the full test suite before pushing:

```bash
cd sdk && pytest tests/ -v --tb=short
```

The CI runs tests on Python 3.10, 3.11, and 3.12. If you are fixing a bug, add a test that would have caught it.

---

## Security

If you find a security vulnerability, do not open a public issue. Email [contact@getcortexops.com](mailto:contact@getcortexops.com) directly. We will respond within 48 hours.

---

## Questions

- Open a [GitHub Discussion](https://github.com/ashishodu2023/cortexops/discussions) for design questions
- Comment on the issue you are working on for implementation questions
- Email [contact@getcortexops.com](mailto:contact@getcortexops.com) for anything else

---

## Recognition

Every contributor is added to the CONTRIBUTORS section of the README after their first merged PR. Significant contributions are acknowledged in release notes.

---

Built by engineers who ship AI agents to production. We are glad you are here.

— Ashish Verma, CortexOps