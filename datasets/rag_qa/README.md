# RAG QA golden dataset

28 cases for a retrieval-augmented question-answering agent over the documentation of a fictional
storage product, "Nimbus". The ten-page corpus is in [`corpus/`](corpus/) as plain Markdown, so you can
index it in your own vector store and reuse the cases unchanged.

```bash
python run_eval.py                            # reference agent, strict gate
python run_eval.py --variant injection_susceptible
pytest -v
```

One corpus page (`corpus/account_security.md`) deliberately contains an **indirect prompt injection**
in a "community tip". Keep it when you index the corpus; the adversarial cases depend on it.

## What each category tests

| Category | Cases | What a failure means |
|---|---|---|
| `happy_path` | `rag_free_storage`, `rag_pro_unit_price`, `rag_business_sla`, `rag_trash_retention`, `rag_encryption_at_rest`, `rag_sso_plan`, `rag_regions`, `rag_api_auth`, `rag_citation_required` | Retrieval or grounding is broken: the fact is missing, wrong, or uncited. |
| `multi_step` | `rag_calc_pro_3tb`, `rag_calc_business_minimum`, `rag_calc_egress`, `rag_multi_hop_sso_rate_limit`, `rag_document_summary` | The agent answered from a single chunk where it needed a calculation (with a plan minimum or free tier), two documents, or the whole page. |
| `edge_case` | `rag_false_premise_unlimited`, `rag_negative_fact_free_sla`, `rag_plan_specific_file_limit`, `rag_typo_robustness`, `rag_structured_input_plan`, `rag_calc_business_minimum` | False premises are accepted, negations or plan-specific facts are confused, typos break retrieval, structured context is ignored. |
| `ambiguous` | `rag_ambiguous_limit`, `rag_ambiguous_price` | The agent guessed instead of asking which limit or price was meant. |
| `refusal` | `rag_unanswerable_gpu`, `rag_unanswerable_weather`, `rag_refuse_unauthorized_access`, `rag_injection_role_play` | The agent made up an answer the corpus does not support, or helped with unauthorized access. |
| `adversarial` | `rag_injection_user_override`, `rag_indirect_injection_password_reset`, `rag_injection_role_play`, `rag_injection_summary_of_poisoned_doc` | A user override ("ignore the documentation and confirm...") or instructions inside retrieved text changed the answer. |
| `latency_budget` | `rag_free_storage`, `rag_trash_retention`, `rag_api_auth` | Simple factoids exceed a 1 s budget, usually because retrieval is slow. |

## Reference agent

`rag_agent.py` splits the corpus into sentences, ranks them with TF-IDF (`retrieve`), drops retrieved
sentences that contain instructions aimed at AI assistants, answers with the top one or two sentences plus
`Sources: [doc_id]`, uses `calculator` for pricing questions, and abstains with "does not cover" below
a relevance threshold. Variants for the reliability report:

| Variant | Degradation |
|---|---|
| `missing_tool` | `calculator` removed; pricing questions are answered with the unit price only. |
| `flaky_tool` | `retrieve` times out for one in three queries (deterministic); the agent replies that search is unavailable. |
| `injection_susceptible` | No sanitisation of retrieved text, and user overrides are obeyed. |
| `slow_tool` | `retrieve` is 2 s slower. |

## Adapting to your agent

- Index `corpus/*.md` in your retriever. Pricing maths assumes 1 TB = 1024 GB.
- Return citations in the output text (for example `[security]` or the file name) if you keep `rag_citation_required`.
- Abstain with wording that does not match the SDK hallucination patterns ("I don't have information", "as of <month> <year>"); the expected string here is "does not cover", so either use that phrase or change it.
- The two `unanswerable` cases and `rag_false_premise_unlimited` are the best candidates for `judge: llm`.
