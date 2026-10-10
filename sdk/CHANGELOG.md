# Changelog

All notable changes to CortexOps are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [Unreleased]

### Added
- **GitHub Action** — `uses: ashishodu2023/cortexops/actions/eval-gate@<ref>` runs a golden dataset against your agent, writes the report to the job summary, keeps one sticky PR comment up to date, and fails the job when a `fail-on` condition is true. Outputs include `passed`, `task-completion`, `pass-rate`, `summary-path` and `report-path`. See `actions/eval-gate/README.md`.
- **`cortexops eval run` reports** — `--output-json` (summary, per-threshold results, `gate_passed`, `pass_rate`, `mean_score`; no traces), `--summary-md` (markdown: headline, metrics table, thresholds, failed cases with failure kind and score) and `--junit-xml` (one testcase per eval case and per condition). Inside GitHub Actions the markdown is appended to `$GITHUB_STEP_SUMMARY` automatically (`--no-step-summary` to disable).
- **`--agent module:attr`** now imports from the current directory, accepts `path/to/file.py:attr` and dotted attributes, and calls factories written as `agent:build_agent()`.
- **Multiple `--fail-on` conditions** — repeat the flag or pass newline-separated conditions; the gate fails if any is true.
- `--judge` (LLM judge for cases with `judge_criteria`), `--push` / `--base-url` (upload results with `CORTEXOPS_API_KEY`), `--title`.
- `EvalSuite.evaluate_threshold()` returns a `ThresholdResult` instead of raising.
- GitLab CI template (`ci-templates/gitlab/cortexops-eval.gitlab-ci.yml`) and a `cortexops-eval` pre-commit hook.

### Changed
- `cortexops eval run` with `--fail-on` gates only on the given conditions; previously it also exited 1 when any case failed. Without `--fail-on` the gate is `pass_rate < 1.0` (unchanged behaviour).
- `cortexops eval run` exits with code 2 for configuration errors (missing dataset, invalid `--fail-on`, agent import failure) instead of 1.
- `--project` now overrides the dataset's project; it was previously only printed.

---

## [0.5.1] — 2026-10-09

### Added
- **Prompt version tracking** — `tracer.set_prompt(name, version)`, `tracer.clear_prompt()`, and the `tracer.use_prompt(name, version)` context manager tag every trace with `prompt_name` / `prompt_version`. The hosted API stores them, `GET /v1/traces` filters by `prompt_name` / `prompt_version`, and the dashboard shows the prompt on each trace.
- **pytest plugin for eval gates** — `@cortexops.eval_gate("golden_v1.yaml", fail_on="task_completion < 0.90")` turns a test that returns an agent into a golden-dataset gate. Auto-registered via the `pytest11` entry point; adds the `cortexops_eval` marker and an eval summary to the pytest report. Install with `pip install "cortexops[pytest]"`.
- **Sampling configuration** — `CORTEXOPS_SAMPLE_RATE` environment variable and a `sample_errors` constructor flag. Each trace records its `sample_rate` and whether it was sampled.
- **Automatic Pro key email** (hosted API) — Stripe and PayPal checkouts email the new key automatically (Resend, falling back to SendGrid), with every outcome in the auth audit log. Admins can rotate and re-send a key with `POST /v1/admin/keys/{id}/resend-email`.

### Fixed
- Unsampled failed runs (`sample_rate < 1.0`) raised `ValueError: "Trace" object has no field "metadata"` instead of the agent's own exception, and were never sent to the hosted API.
- Traces now include the tracer's `environment`; previously every hosted trace was recorded as `development`.
- `fail_on` expressions with trailing text (e.g. `"task_completion < 0.9 or else"`) are now rejected instead of being silently truncated.
- Hosted API: Stripe webhook retries could create duplicate Pro keys.

---

## [0.5.0] — 2026-07-05

### Added
- **`CortexClient.add_case_from_trace()`** — promote a production trace into a golden dataset case (`POST /v1/eval/datasets/{id}/cases/from-trace`).
- **Dataset & prompt APIs on client** — `list_datasets`, `get_dataset`, `create_dataset`, `commit_prompt`, `list_prompt_catalog`, `project_for_key`.
- **Error-always sampling** — failed runs are captured even when `sample_rate < 1.0`, so regressions are not dropped by head-based sampling.

### Changed
- **Production API URL** — default `CortexClient` base URL is now `https://api.getcortexops.com` (was `api.cortexops.ai`).
- **API key header** — client uses `X-API-Key` to match the hosted API auth middleware.
- **`push_eval()`** — targets `POST /v1/evals/ingest` with optional dataset/prompt metadata.
- **Framework detection** — Google ADK vs OpenAI Agents disambiguation fixed; sampling validates `0.0–1.0` range.
- **PyPI metadata** — expanded framework keywords and `httpx` as a core dependency.

### Fixed
- Eval ingest payload strips embedded trace objects before upload.
- `failure_kind` enum serialized correctly for API ingest.

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