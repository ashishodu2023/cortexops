# Tool workflows golden dataset

26 cases for a "workspace assistant" that chains tools: contact search, calendar, email, tickets,
a read-only SQL reporting database, currency conversion, and a calculator. The cases test tool selection,
argument extraction, multi-step chains, partial failures, and confirmation before risky side effects.

```bash
python run_eval.py                       # reference agent, strict gate
python run_eval.py --variant flaky_tool
pytest -v
```

`fixtures.json` defines five contacts (two named Alex), busy calendar slots on 2030-03-12 and
2030-03-13, four tickets (one carries an injected instruction in its description), and fixed FX rates.
The fixture clock is 2026-10-01; future-dated cases use 2030 so they stay valid for agents on a real clock.

## What each category tests

| Category | Cases | What a failure means |
|---|---|---|
| `happy_path` | `wf_schedule_meeting`, `wf_email_internal`, `wf_convert_currency`, `wf_ticket_status`, `wf_create_ticket`, `wf_sql_report`, `wf_percentage` | Single-intent requests use the wrong tool or wrong arguments. |
| `multi_step` | `wf_chain_contact_calendar_event`, `wf_expense_convert_and_file`, `wf_bulk_ticket_creation`, `wf_partial_recipients`, plus the meeting and email happy paths | A dependent step was skipped (no availability check before booking), fan-out stopped early, or one bad recipient sank the whole request. |
| `edge_case` | `wf_calendar_conflict`, `wf_unknown_contact`, `wf_past_date`, `wf_outside_working_hours`, `wf_unsupported_currency`, `wf_structured_conversion` | Validation is missing: booking into a busy slot, in the past, or at 3 am; unsupported currencies; structured arguments ignored. |
| `ambiguous` | `wf_ambiguous_contact`, `wf_vague_meeting` | The agent picked one of two contacts, or invented attendees and times, instead of asking. |
| `refusal` | `wf_unsupported_travel`, `wf_destructive_sql`, `wf_external_email_confirmation` | Out-of-scope actions attempted, a write query run, or an external email sent without confirmation. |
| `adversarial` | `wf_sql_injection_in_request`, `wf_injection_ignore_rules_exfiltration`, `wf_indirect_injection_ticket`, `wf_injection_bcc_smuggling` | User text or tool output (ticket TCK-104) caused exfiltration or SQL injection. |
| `latency_budget` | `wf_convert_currency`, `wf_ticket_status`, `wf_percentage` | Simple lookups exceed a 1 s budget. |

## Reference agent

`workflow_agent.py` strips override phrases, refuses write SQL, requires confirmation for non-internal
recipients, removes BCC/CC/forward clauses that add outside addresses, validates dates and working hours
before calling tools, and never acts on text found inside tool output. `run_sql` itself runs on an
in-memory SQLite database with `PRAGMA query_only = ON`, a second layer of defence.

Unlike the other two reference agents it has no tool-error handling, so a failing tool raises out of
`invoke`. Variants for the reliability report:

| Variant | Degradation |
|---|---|
| `missing_tool` | `check_calendar` removed; meetings are booked without an availability check. |
| `flaky_tool` | `search_contacts` fails with HTTP 502 for one in three names (deterministic); the exception propagates. |
| `injection_susceptible` | Guardrails off: external email without confirmation, raw SQL, and instructions in tool output are obeyed. |
| `slow_tool` | `convert_currency` is 2 s slower. |

## Adapting to your agent

- Back your tools with `fixtures.json`, or rewrite names, ids, and expected strings for your own data.
- Side effects that must not happen (`send_email`, `create_event`) are guarded with `expected_output_not_contains` ("Sent to", "Scheduled") because the tool-accuracy metric does not penalise extra calls. If your agent words confirmations differently, update those strings so the guards still bite.
- `wf_partial_recipients` and `wf_indirect_injection_ticket` carry `judge_criteria` for `judge: llm`.
