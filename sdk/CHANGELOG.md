# Changelog

All notable changes to CortexOps are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [0.4.0] — 2026-05-24

### Added
- **LLM-as-judge evaluation** — `LLMJudgeMetric` and `LLMJudge` classes for semantic scoring of agent outputs against configurable rubrics (task completion, response quality, safety). Heuristic fallback when no API key is available.
- **Golden dataset API** — `GoldenDataset` class for building, versioning, and running evaluation datasets. Supports YAML/JSON persistence, production trace seeding, tag-based filtering, and direct agent execution.
- **CI/CD eval gate CLI** — `cortexops eval run --dataset <file> --judge --fail-on "task_completion < 0.90"` — exits with code 1 on regression, drop-in for GitHub Actions.
- **Eval API backend** — `POST /v1/eval/judge` and `POST /v1/eval/datasets` REST endpoints (Pro tier).
- **Three built-in rubrics** — `task_completion`, `response_quality`, `safety` with weighted criteria and configurable pass thresholds.

### Fixed
- CVE-2026-42561 — python-multipart bumped to 0.0.27.
- `httpx` added to core SDK dependencies (previously optional only).
- Ruff lint: removed unused `typing.Any`, fixed import sort order.

---

## [0.2.0] — 2026-04-07

### Added
- **Auto API key resolution** — `CortexTracer` now auto-loads key from `CORTEXOPS_API_KEY` env var or `~/.cortexops/credentials`. No more passing `api_key=` manually in code.
- **`cortexops login`** — interactive CLI login. Saves key to `~/.cortexops/credentials`.
- **`cortexops logout`** — removes stored credentials.
- **`cortexops whoami`** — shows active key source and verifies against API.
- **`auth` module** — `save_credentials()`, `load_credentials()`, `verify_key()` for programmatic credential management.
- **`CORTEXOPS_PROJECT` env var** — `CortexTracer()` with no arguments auto-loads project from environment.
- **`is_hosted` property** — `tracer.is_hosted` is `True` when a key is resolved, `False` for local-only mode.
- **Free tier enforcement** — `GET /v1/traces/quota` endpoint returns current usage and limits.
- **PII redaction** — emails, card numbers, SSNs automatically scrubbed before trace storage.
- **Idempotency keys** — pass `Idempotency-Key` header to prevent duplicate traces on retry.
- **Local JSONL store** — `LocalTraceStore` for offline/air-gapped use.

### Changed
- `CortexTracer.__init__` — `project` is now optional (falls back to `CORTEXOPS_PROJECT` env var or `"default"`).
- `pyproject.toml` — Development Status upgraded from Alpha → Beta.
- Package URLs updated to `getcortexops.com`.

### Fixed
- `@timed` decorator removed from FastAPI route handlers (caused `PydanticUndefinedAnnotation` at startup).
- Ruff: E402 (late imports), F401 (unused imports), E741 (ambiguous variable), F541 (f-string without placeholders).
- CORS preflight `OPTIONS` returning 400 — all `getcortexops.com` domains added to allowed origins.

## [0.1.0] — 2025-04-03

First public release.

### Added

**SDK**
- `CortexTracer` — one-line instrumentation for LangGraph, CrewAI, and any callable
- `EvalSuite` — golden dataset runner with YAML format support
- Built-in metrics: `task_completion`, `tool_accuracy`, `latency`, `hallucination`
- `LLMJudgeMetric` — GPT-4o scoring for open-ended outputs with heuristic fallback
- `CortexClient` — HTTP client for the hosted API
- `cortexops` CLI — `eval run`, `eval diff`, `failures` commands
- Full type annotations, Pydantic v2 models throughout

**Backend**
- FastAPI + async SQLAlchemy + Celery worker
- `POST /v1/evals` — trigger async eval runs
- `GET /v1/evals/{run_id}` — poll results
- `GET /v1/evals/diff` — compare two runs
- `POST /v1/traces` — ingest traces from SDK
- `POST /v1/prompts` — prompt version commits
- `GET /v1/prompts/diff` — unified diff between versions
- `POST /v1/keys` — API key management
- Slack + webhook alerting on regression
- SHA-256 hashed API key auth middleware

**Examples**
- LangGraph payments agent with 9 golden eval cases
- `run_eval.py` CLI runner with `--fail-on` threshold support

**Infrastructure**
- GitHub Actions eval gate — blocks PRs on regression
- Docker Compose for local full-stack development
- MIT license

### Links
- PyPI: https://pypi.org/project/cortexops/0.1.0
- GitHub: https://github.com/ashishodu2023/cortexops/releases/tag/v0.1.0