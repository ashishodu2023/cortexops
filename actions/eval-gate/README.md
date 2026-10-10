# CortexOps Eval Gate

<!-- dev-copy-note:start -->
> **This is the development copy.** Use the published action,
> [`ashishodu2023/cortexops-eval-action`](https://github.com/ashishodu2023/cortexops-eval-action)
> (`uses: ashishodu2023/cortexops-eval-action@v1`). Changes are made and tested here, then synced to that
> repo; see [RELEASING.md](RELEASING.md). The README below is the one published there.
<!-- dev-copy-note:end -->

Run a [CortexOps](https://github.com/ashishodu2023/cortexops) golden-dataset eval against your AI agent
on every pull request and block the merge when quality regresses. The action:

1. installs Python and the `cortexops` SDK from PyPI,
2. runs `cortexops eval run` against your agent (or your own command),
3. writes a markdown report to the **job summary** (pass/fail headline, metrics, threshold results,
   failed cases with failure kind and score),
4. creates or updates **one sticky PR comment** with the same report,
5. fails the job if any `fail-on` condition is true, after the summary and comment are written.

It works with any agent the CortexOps SDK can call: LangGraph, LangChain runnables, CrewAI, OpenAI Agents,
PydanticAI, plain Python callables, and more.

## Quick start

```yaml
# .github/workflows/eval.yml
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
      - uses: ashishodu2023/cortexops-eval-action@v1
        with:
          dataset: evals/golden_v1.yaml
          agent: my_app.agent:build_agent()
          install: -r requirements.txt
          fail-on: task_completion < 0.90
```

`dataset` is a CortexOps golden dataset (YAML). See the
[SDK docs](https://github.com/ashishodu2023/cortexops/tree/main/sdk) for the format, or create one with
`cortexops dataset create`.

## Examples

### Several thresholds

`fail-on` takes one condition per line. The gate fails if any of them is true. Metrics are on a 0-1
scale: `task_completion`, `tool_accuracy`, `pass_rate`. Operators: `<`, `<=`, `>`, `>=`.

```yaml
      - uses: ashishodu2023/cortexops-eval-action@v1
        with:
          dataset: evals/golden_v1.yaml
          agent: my_app.agent:build_agent()
          fail-on: |
            task_completion < 0.90
            tool_accuracy < 0.95
            pass_rate < 0.80
```

Without `fail-on` the gate is `pass_rate < 1.0`: any failing case fails the job.

### LLM-as-judge scoring

Cases that define `judge_criteria` are scored by the LLM judge when `judge: true`. Pass an OpenAI key from
a secret; without one the judge falls back to a keyword heuristic.

```yaml
      - uses: ashishodu2023/cortexops-eval-action@v1
        with:
          dataset: evals/golden_v1.yaml
          agent: my_app.agent:build_agent()
          judge: true
          openai-api-key: ${{ secrets.OPENAI_API_KEY }}
          fail-on: task_completion < 0.90
```

The same key is also visible to your agent as `OPENAI_API_KEY` while the eval runs.

### Push results to the CortexOps dashboard

When `api-key` is set, the run is also uploaded to CortexOps so you can track it over time and diff
runs. Upload errors only log a warning; they never fail the gate.

```yaml
      - uses: ashishodu2023/cortexops-eval-action@v1
        with:
          dataset: evals/golden_v1.yaml
          agent: my_app.agent:build_agent()
          api-key: ${{ secrets.CORTEXOPS_API_KEY }}
          # api-url: https://cortexops.example.com   # self-hosted API
```

### Use the outputs

```yaml
      - uses: ashishodu2023/cortexops-eval-action@v1
        id: eval
        with:
          dataset: evals/golden_v1.yaml
          agent: my_app.agent:build_agent()
          fail-job: false            # report only; decide below
      - run: echo "Task completion ${{ steps.eval.outputs.task-completion }}, passed=${{ steps.eval.outputs.passed }}"
      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: eval-report
          path: ${{ runner.temp }}/cortexops-eval-*/
```

The uploaded directory contains `report.json`, `summary.md`, and `junit.xml`. `junit-path` can also be
passed to a test-report action.

### Several gates on one pull request

Each gate keeps its own sticky comment, keyed by `comment-tag` (default: the dataset path).

```yaml
      - uses: ashishodu2023/cortexops-eval-action@v1
        with:
          dataset: evals/refunds.yaml
          agent: my_app.agent:build_agent()
          title: Refunds agent
          comment-tag: refunds
      - uses: ashishodu2023/cortexops-eval-action@v1
        with:
          dataset: evals/disputes.yaml
          agent: my_app.agent:build_agent()
          title: Disputes agent
          comment-tag: disputes
```

If the first gate fails, the second step is skipped unless you add `if: ${{ !cancelled() }}` to it.

### Custom eval command

If your agent needs custom setup, pass a `command` instead; its exit code decides the gate. To keep the
job summary, outputs, and PR comment, have it write the reports to the paths the action exports:

```yaml
      - uses: ashishodu2023/cortexops-eval-action@v1
        with:
          command: >-
            python scripts/run_eval.py
            --output-json "$CORTEXOPS_REPORT_JSON"
            --summary-md "$CORTEXOPS_SUMMARY_MD"
```

## How the agent is loaded

`agent` is `module:attr` or `path/to/file.py:attr`, imported from `working-directory` (which is put on
`sys.path`). The object must be callable with a dict input, or expose `.invoke()` (LangGraph, LangChain
runnables). Append `()` to call a zero-argument factory:

| `agent` | Meaning |
|---|---|
| `agent:graph` | `from agent import graph` |
| `my_app.agents:build_agent()` | `from my_app.agents import build_agent; build_agent()` |
| `src/bot.py:Bot.run` | load `src/bot.py`, use `Bot.run` |

Without `agent`, a placeholder agent echoes the input, which is only useful to check the dataset loads.

## Inputs

| Input | Default | Description |
|---|---|---|
| `dataset` | | Golden dataset YAML, relative to `working-directory`. Required unless `command` is set. |
| `agent` | | `module:attr` or `file.py:attr`; trailing `()` calls a factory. |
| `command` | | Custom command instead of `cortexops eval run`. Gets `CORTEXOPS_REPORT_JSON`, `CORTEXOPS_SUMMARY_MD` and `CORTEXOPS_JUNIT_XML` env vars. |
| `fail-on` | `pass_rate < 1.0` | Gate conditions, one per line; the gate fails if any is true. |
| `working-directory` | `.` | Directory the eval runs in. |
| `python-version` | `3.11` | Passed to `actions/setup-python`. An empty string uses the Python already on `PATH`. |
| `cortexops-version` | `>=0.6.0,<0.7` | SDK to install; see [Choosing the SDK version](#choosing-the-sdk-version). |
| `install` | | Extra pip arguments for your agent's dependencies, run in `working-directory` (e.g. `-r requirements.txt`, `.`). |
| `judge` | `false` | Score cases that define `judge_criteria` with the LLM judge. |
| `openai-api-key` | | OpenAI key for `judge`. Without it a keyword heuristic is used. |
| `title` | `CortexOps eval gate` | Heading of the job summary and PR comment. |
| `extra-args` | | Extra whitespace-separated arguments for `cortexops eval run` (e.g. `--project my-agent`). |
| `comment-on-pr` | `true` | Create or update the sticky PR comment on `pull_request` / `pull_request_target` events. |
| `comment-tag` | dataset path | Identifies the sticky comment. Use distinct tags to run several gates on one PR. |
| `github-token` | `github.token` | Token for the PR comment. |
| `api-key` | | `CORTEXOPS_API_KEY`. When set, results are also pushed to the CortexOps dashboard. |
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
| `junit-path` | JUnit XML path (one testcase per eval case and per `fail-on` condition). |
| `comment-url` | URL of the sticky PR comment, when one was written. |

## Choosing the SDK version

The action needs `cortexops` 0.6.0 or newer, the first release with `eval run --output-json` and
`--junit-xml`. An older install fails the step with exit code 2 before the eval runs.

| `cortexops-version` | Installs |
|---|---|
| `>=0.6.0,<0.7` (default) | Newest 0.6.x from PyPI. Patch releases are picked up; a new minor release, which may change the report format or metrics, is not. |
| `0.6.0` | Exactly that version. |
| `latest` | Newest release on PyPI. |
| `>=0.6`, `~=0.6.1`, ... | Any pip version specifier. |
| `git+https://github.com/ashishodu2023/cortexops@<ref>#subdirectory=sdk` | The SDK at a branch, tag, or commit of the main repo. |
| `./path/to/sdk` | A local checkout, relative to the workspace root. |
| `none` | Nothing; use the `cortexops` already installed (e.g. via `install` or an earlier step). |

## Versioning

- `@v1` follows the latest 1.x release. Inputs and outputs only change in backwards-compatible ways within v1.
- `@v1.0.0` is an immutable release tag.
- For the strongest supply-chain guarantee, pin the full commit SHA of a release:
  `uses: ashishodu2023/cortexops-eval-action@<sha> # v1.0.0`.

See the [changelog](https://github.com/ashishodu2023/cortexops-eval-action/blob/main/CHANGELOG.md).

## Permissions and forks

- The job summary needs no extra permissions.
- The sticky comment needs `pull-requests: write`; `contents: read` is enough for everything else.
  The action finds its previous comment by a hidden `<!-- cortexops-eval-gate: <comment-tag> -->`
  marker and edits it instead of adding a new one.
- Pull requests from forks get a read-only `GITHUB_TOKEN`. The action logs a warning, skips the comment,
  and still writes the job summary and enforces the gate.
- Avoid `pull_request_target` with untrusted code: it runs the fork's agent with a write token and your
  secrets.
- `api-key` and `openai-api-key` should come from `secrets`, which are not passed to fork PRs. Without
  them the eval still runs: the judge uses its keyword heuristic and nothing is uploaded.

## Security

- Inputs reach the action's scripts only through environment variables, never by interpolating them into
  shell code.
- The actions it uses (`actions/setup-python`, `actions/github-script`) are pinned to full commit SHAs.
- The `command`, `install`, and `extra-args` inputs run as given, with your job's permissions; only set
  them from trusted workflow code.

## Running locally

The action is a thin wrapper around the CLI, so the same gate runs anywhere:

```bash
pip install "cortexops>=0.6.0,<0.7"
cortexops eval run --dataset golden_v1.yaml --agent "agent:build_agent()" \
  --fail-on "task_completion < 0.90" --fail-on "tool_accuracy < 0.95" \
  --output-json report.json --summary-md summary.md --junit-xml junit.xml
```

Inside GitHub Actions the CLI also appends the markdown report to `$GITHUB_STEP_SUMMARY`
(disable with `--no-step-summary`). For GitLab CI, see the
[GitLab template](https://github.com/ashishodu2023/cortexops/tree/main/ci-templates/gitlab).

## Contributing

This repository is published from
[`actions/eval-gate`](https://github.com/ashishodu2023/cortexops/tree/main/actions/eval-gate) in the main
CortexOps repo, where the action is developed and tested against the SDK. Please open issues and pull
requests there.

## License

[MIT](https://github.com/ashishodu2023/cortexops-eval-action/blob/main/LICENSE)
