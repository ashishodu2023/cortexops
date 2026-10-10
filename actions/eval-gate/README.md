# CortexOps eval gate (GitHub Action)

Run a CortexOps golden-dataset eval against your agent on every pull request and block the merge
when quality regresses. The action:

1. installs Python and `cortexops`,
2. runs `cortexops eval run` against your agent (or your own command),
3. writes a markdown report to the **job summary** (pass/fail headline, metrics, threshold results,
   failed cases with failure kind and score),
4. creates or updates **one sticky PR comment** with the same report,
5. fails the job if any `fail-on` condition is true, after the summary and comment are written.

```yaml
name: Eval gate
on:
  pull_request:

permissions:
  contents: read

jobs:
  eval:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      pull-requests: write   # only needed for the sticky PR comment
    steps:
      - uses: actions/checkout@v4
      - uses: ashishodu2023/cortexops/actions/eval-gate@main   # pin to a tag or commit SHA
        with:
          dataset: evals/golden_v1.yaml
          agent: my_app.agent:build_agent()
          install: -r requirements.txt
          fail-on: |
            task_completion < 0.90
            tool_accuracy < 0.95
```

> Requires a `cortexops` release with `eval run --output-json` (newer than 0.5.1). Until it is on
> PyPI, set `cortexops-version: bundled` to install the SDK from the same ref as the action.

## How the agent is loaded

`agent` is `module:attr` or `path/to/file.py:attr`, imported from `working-directory` (which is put
on `sys.path`). The object must be callable with a dict input, or expose `.invoke()` (LangGraph,
LangChain runnables). Append `()` to call a zero-argument factory:

| `agent` | Meaning |
|---|---|
| `agent:graph` | `from agent import graph` |
| `my_app.agents:build_agent()` | `from my_app.agents import build_agent; build_agent()` |
| `src/bot.py:Bot.run` | load `src/bot.py`, use `Bot.run` |

If your agent needs custom setup, pass a `command` instead; its exit code decides the gate. To keep
the job summary, outputs, and PR comment, have it write the reports to the paths the action exports:

```yaml
      - uses: ashishodu2023/cortexops/actions/eval-gate@main
        with:
          command: >-
            python scripts/run_eval.py
            --output-json "$CORTEXOPS_REPORT_JSON"
            --summary-md "$CORTEXOPS_SUMMARY_MD"
```

## Inputs

| Input | Default | Description |
|---|---|---|
| `dataset` | | Golden dataset YAML, relative to `working-directory`. Required unless `command` is set. |
| `agent` | | `module:attr` or `file.py:attr`; trailing `()` calls a factory. Without it a placeholder agent runs. |
| `command` | | Custom command instead of `cortexops eval run`. Gets `CORTEXOPS_REPORT_JSON`, `CORTEXOPS_SUMMARY_MD` and `CORTEXOPS_JUNIT_XML` env vars. |
| `fail-on` | `pass_rate < 1.0` | Gate conditions, one per line; the gate fails if any is true. Metrics (0-1): `task_completion`, `tool_accuracy`, `pass_rate`. Operators: `<`, `<=`, `>`, `>=`. |
| `working-directory` | `.` | Directory the eval runs in. |
| `python-version` | `3.11` | Passed to `actions/setup-python`. Empty string uses the Python already on `PATH`. |
| `cortexops-version` | `latest` | `latest`, a version (`0.6.0`), a specifier (`>=0.6`), a local path (`./sdk`), `bundled` (SDK at the action's ref), or `none`. |
| `install` | | Extra pip arguments for your agent's dependencies, run in `working-directory` (e.g. `-r requirements.txt`, `.`). |
| `judge` | `false` | Score cases that define `judge_criteria` with the LLM judge. |
| `openai-api-key` | | OpenAI key for `judge`. Without it a keyword heuristic is used. |
| `title` | `CortexOps eval gate` | Heading of the job summary and PR comment. |
| `extra-args` | | Extra whitespace-separated arguments for `cortexops eval run` (e.g. `--project my-agent`). |
| `comment-on-pr` | `true` | Create or update the sticky PR comment on `pull_request` / `pull_request_target` events. |
| `comment-tag` | dataset path | Identifies the sticky comment. Use distinct tags to run several gates on one PR. |
| `github-token` | `github.token` | Token for the PR comment. |
| `api-key` | | `CORTEXOPS_API_KEY`. When set, results are also pushed to the CortexOps dashboard (upload errors only warn). |
| `api-url` | hosted API | CortexOps API URL for `api-key` uploads. |
| `fail-job` | `true` | Set to `false` to report without failing the job. |

## Outputs

| Output | Description |
|---|---|
| `passed` | `true` if the gate passed, otherwise `false`. |
| `exit-code` | `0` passed, `1` gate failed, `2` configuration error (missing dataset, bad expression, agent import error). |
| `task-completion` | Task completion rate, 0-1. |
| `pass-rate` | Fraction of passing cases, 0-1. |
| `tool-accuracy` | Tool accuracy, 0-1. |
| `mean-score` | Mean case score, 0-100. |
| `failed` | Number of failed cases. |
| `summary-path` | Markdown report path. |
| `report-path` | JSON report path (summary, threshold results, case results without traces). |
| `junit-path` | JUnit XML path, for test-report actions. |
| `comment-url` | URL of the sticky PR comment, when one was written. |

Upload the reports as an artifact:

```yaml
      - uses: ashishodu2023/cortexops/actions/eval-gate@main
        id: eval
        with:
          dataset: golden_v1.yaml
          agent: agent:build_agent()
      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: eval-report
          path: ${{ runner.temp }}/cortexops-eval-*/
```

## Permissions and forks

- The job summary needs no extra permissions.
- The sticky comment needs `pull-requests: write`. The action finds its previous comment by a
  hidden `<!-- cortexops-eval-gate: <comment-tag> -->` marker and edits it instead of adding a new one.
- Pull requests from forks get a read-only `GITHUB_TOKEN`. The action logs a warning, skips the
  comment, and still writes the job summary and enforces the gate. Avoid `pull_request_target` with
  untrusted code: it runs the fork's agent with a write token and your secrets.
- `api-key` and `openai-api-key` should come from `secrets`, which are not available to fork PRs.

## Running locally

The action is a thin wrapper around the CLI, so the same gate runs anywhere:

```bash
pip install cortexops
cortexops eval run --dataset golden_v1.yaml --agent "agent:build_agent()" \
  --fail-on "task_completion < 0.90" --fail-on "tool_accuracy < 0.95" \
  --output-json report.json --summary-md summary.md
```

Inside GitHub Actions the CLI also appends the markdown report to `$GITHUB_STEP_SUMMARY`
(disable with `--no-step-summary`).
