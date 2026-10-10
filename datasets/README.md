# CortexOps open golden datasets

Reusable, versioned golden datasets for evaluating AI agents with [CortexOps](https://getcortexops.com).
Each set ships with a small deterministic reference agent (no LLM, no API key), so the
dataset, the agent, and the CI gate can be read, run, and diffed in milliseconds.

| Dataset | Cases | Agent under test | Tools |
|---|---|---|---|
| [`customer_support/`](customer_support/) | 30 | E-commerce support agent | `lookup_order`, `track_shipment`, `check_refund_eligibility`, `issue_refund`, `update_shipping_address`, `search_kb`, `escalate_to_human` |
| [`rag_qa/`](rag_qa/) | 28 | Documentation QA over a Markdown corpus | `retrieve`, `get_document`, `calculator` |
| [`tool_workflows/`](tool_workflows/) | 26 | Workspace assistant with multi-step tool chains | `search_contacts`, `check_calendar`, `create_event`, `send_email`, `create_ticket`, `get_ticket`, `run_sql`, `convert_currency`, `calculator` |

Every directory contains:

- `golden.yaml` -- the dataset, in the standard CortexOps format (`id`, `input`, `expected_tool_calls`, `expected_output_contains`, `expected_output_not_contains`, `max_latency_ms`, `judge`, `judge_criteria`, `tags`).
- `*_agent.py` -- the reference agent, instrumented with `CortexTracer` (`trace_node` per step, `record_tool_call` per tool call, `set_prompt` for prompt versioning). `build_agent(variant=...)` also builds the degraded variants used in the [Agent Reliability Report](../docs/reports/agent-reliability-2026-10.md).
- `run_eval.py` -- `EvalSuite.run` plus `fail_on` thresholds; exits non-zero when the gate fails.
- `test_<name>.py` -- the same gate as a pytest test via `@cortexops.eval_gate`.
- `README.md` -- what each case category tests and how to adapt the set to your agent.
- Fixture data (`fixtures.json` or `corpus/`) that the case inputs refer to.

## Run

```bash
pip install "cortexops[pytest]"

python datasets/customer_support/run_eval.py                 # one dataset, CI-style exit code
pytest datasets -v                                           # all three gates as pytest tests
cd datasets/rag_qa && PYTHONPATH=. cortexops eval run --dataset golden.yaml --agent rag_agent:run
```

`PYTHONPATH=.` is needed for the CLI because `--agent module:object` is imported from `sys.path`,
which does not include the working directory for console scripts.

## Tag taxonomy

Every case carries at least one category tag, plus domain tags (`refund`, `pricing`, `calendar`, ...):

| Tag | What it tests |
|---|---|
| `happy_path` | The common request, answered correctly with the right tools. |
| `edge_case` | Boundary conditions: policy limits, not-found ids, conflicts, typos, structured (dict) input, non-English input. |
| `multi_step` | Two or more dependent tool calls, fan-out, or partial failures inside a chain. |
| `ambiguous` | Under-specified requests where the right move is a clarifying question and no side effects. |
| `adversarial` | Prompt injection (direct and indirect, via retrieved text or tool output), social engineering, data exfiltration. `prompt_injection` / `indirect_injection` mark the subtype. |
| `refusal` | Out-of-scope, unsafe, or unanswerable requests that must be declined or abstained on. |
| `latency_budget` | Simple requests with a tight `max_latency_ms` (1000 ms) that a fast path should meet. |

Filter with the SDK: `GoldenDataset.load("datasets/rag_qa/golden.yaml").filter("adversarial")`.

## Scoring caveats (CortexOps SDK 0.5.1)

Read these before choosing `fail_on` thresholds; the reliability report shows each one in practice.

- A case **passes** when the mean of four metric scores (task completion, tool accuracy, latency, hallucination) is at least 80. One failing metric can therefore still pass: a prohibited string in the output scores 30 on task completion and averages to 82.5, and an output containing `error:` scores 20 and averages to exactly 80.
- **Task completion** for a case is true when its score is at least 80, so with three expected strings, missing one (score 83.3) still counts as completed. Missing every expected string scores 50, which still averages to a passing 87.5 when the other metrics are clean; only the `task_completion` threshold catches it.
- **Tool accuracy** checks that expected tools were called. Extra calls, such as an unexpected `issue_refund` or `send_email`, are not penalised; guard side effects with `expected_output_not_contains`.
- **Latency** only fails a case on its own when the run takes more than about 1.8x its budget.
- `EvalSuite` scores tool usage from `output["tool_calls_made"]`, so the reference agents return that list alongside `output`.
- The hallucination metric flags phrases such as "I don't have access/information" and "as of <month> <year>". Phrase abstentions differently (these datasets use "does not cover").

For these reasons the gates here use all three thresholds: `pass_rate < 1.0`, `task_completion < 1.0`, and `tool_accuracy < 1.0`.
For an LLM agent, start from the same gate and loosen deliberately (for example `pass_rate < 0.9`) rather than gating on `pass_rate` alone.

## Adapting a dataset to your agent

1. **Point your tools at the fixtures** (`fixtures.json`, or index `rag_qa/corpus/` in your retriever) so case inputs and expected strings stay valid, or rewrite the ids and expected strings for your own data.
2. **Map tool names.** `expected_tool_calls` uses the reference tool names; rename them to yours.
3. **Return the eval shape.** `EvalSuite` passes `{"input": ...}` (or the dict input as-is) to `agent.invoke(...)` or `agent(...)`, and reads `output` and `tool_calls_made` from the result.
4. **Re-baseline latency budgets.** Budgets assume an LLM agent (1-8 s); keep the tight `latency_budget` cases as your fast-path SLO or move them.
5. **Optionally switch nuanced cases to the LLM judge.** Cases with `judge_criteria` describe the intended behaviour; set `judge: llm` and `OPENAI_API_KEY` to score them semantically.

## License

MIT, the same license as the rest of the repository (see [LICENSE](../LICENSE)). All names, orders,
contacts, documents, and email addresses are fictional; `.example` domains are reserved for documentation.
