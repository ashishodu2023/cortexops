# Framework integration guides

One self-contained guide per agent framework. Each covers install, tracing with `CortexTracer.wrap()`,
prompt version tagging, and an eval gate in CI (pytest plugin and `cortexops` CLI). They are written so
they can be submitted to the framework's own documentation with only format changes (for example MDX
front matter), and they describe what the CortexOps 0.5.1 wrapper actually does for that framework.

| Framework | Guide | What `wrap()` traces |
|---|---|---|
| LangGraph | [langgraph.md](langgraph.md) | `invoke`, `ainvoke` on a compiled graph |
| CrewAI | [crewai.md](crewai.md) | `kickoff(inputs=...)` on a `Crew` |
| PydanticAI | [pydantic_ai.md](pydantic_ai.md) | `run_sync` on an `Agent` |
| OpenAI Agents SDK | [openai_agents.md](openai_agents.md) | `run_sync` and `run` (via `Runner`) on an `Agent` |
| Google ADK | [google_adk.md](google_adk.md) | a Runner-based adapter's `invoke` (the built-in ADK wrapper does not work with ADK 2.x) |

## Verification

Every code sample in the guides is executed by [`_verify/verify_guides.py`](_verify/verify_guides.py):

```bash
pip install -e "sdk[pytest]" langgraph langchain-core pydantic-ai-slim openai-agents google-adk crewai
python docs/integrations/_verify/verify_guides.py            # all guides whose framework is installed
python docs/integrations/_verify/verify_guides.py crewai     # one guide
```

The script writes each guide's `# my_agent.py`, `# golden.yaml` and `# test_my_agent.py` blocks verbatim
to a temporary directory, replaces the single line that selects a hosted model with an offline fake from
[`_verify/fakes.py`](_verify/fakes.py), and then runs `python my_agent.py` plus the guide's own `pytest`
and `cortexops eval run` commands exactly as written. The fakes plug into each framework's model interface
(`BaseChatModel`, `FunctionModel`, `agents.Model`, `crewai.BaseLLM`, `google.adk.models.BaseLlm`), so the
framework's real agent loop, tool execution and result objects run; only the model's text is scripted.
Framework-specific claims (for example that PydanticAI results expose `.output`, or that the built-in ADK
wrapper fails on ADK 2.x) are asserted as extra checks.

Last run (2026-10-09, Python 3.12, cortexops 0.5.1), all against the real packages:

| Guide | Package version | Result |
|---|---|---|
| langgraph | langgraph 1.2.14 | PASS |
| crewai | crewai 1.6.1 | PASS |
| pydantic_ai | pydantic-ai-slim 2.55.0 | PASS |
| openai_agents | openai-agents 0.23.1 | PASS |
| google_adk | google-adk 2.11.0 | PASS |

Not verified: calls to the hosted models themselves (OpenAI, Gemini), which need API keys. CrewAI writes
to `~/.local/share` on import; run the verifier with a writable `HOME`.

## Upstream targets

Where each guide could be contributed, checked against the upstream repositories on 2026-10-09. No issues
or pull requests have been opened upstream. Items marked "to confirm" need a maintainer's answer before a
pull request.

| Framework | Repository | Target | Contribution rules |
|---|---|---|---|
| LangGraph | [langchain-ai/docs](https://github.com/langchain-ai/docs) | Integration listing issue using the [integration submission template](https://github.com/langchain-ai/docs/blob/main/.github/ISSUE_TEMPLATE/06-integration-submission.yml); automation adds a row to `scripts/data/integration_external_docs.yaml` linking to `langgraph.md` hosted in this repository | [integrations-langchain.mdx](https://github.com/langchain-ai/docs/blob/main/src/oss/contributing/integrations-langchain.mdx): packages under the download threshold are listed via the issue; hand-written integration pages are not accepted |
| CrewAI | [crewAIInc/crewAI](https://github.com/crewAIInc/crewAI) | New page `docs/edge/en/observability/cortexops.mdx` (from `crewai.md`, Mintlify front matter) plus a navigation entry in `docs/docs.json` | [CONTRIBUTING.md](https://github.com/crewAIInc/crewAI/blob/main/.github/CONTRIBUTING.md): pull requests written with AI assistance must carry the `llm-generated` label |
| PydanticAI | [pydantic/pydantic-ai](https://github.com/pydantic/pydantic-ai) | To confirm: an entry in the "Third-party ecosystem" section of `docs/extensibility.md`, or `docs/evals/evaluators/framework-integrations.md`; any new page must also be added to `docs/navigation.yml` (enforced by a test) | [CONTRIBUTING.md](https://github.com/pydantic/pydantic-ai/blob/main/CONTRIBUTING.md): open an issue to agree on the change before a pull request |
| OpenAI Agents SDK | [openai/openai-agents-python](https://github.com/openai/openai-agents-python) | "External tracing processors list" in `docs/tracing.md`. Not eligible yet: the list is for `TracingProcessor` implementations and CortexOps does not ship one | [CONTRIBUTING.md](https://github.com/openai/openai-agents-python/blob/main/CONTRIBUTING.md): pull requests are accepted from collaborators; external listings are requested via an issue with evidence of usage |
| Google ADK | [google/adk-docs](https://github.com/google/adk-docs) | New page `docs/integrations/cortexops.md` (from `google_adk.md`) with catalog front matter (`catalog_title`, `catalog_description`, `catalog_icon: /integrations/assets/cortexops.png`, `catalog_tags: ["observability"]`) and the icon in `docs/integrations/assets/` | [CONTRIBUTING.md](https://github.com/google/adk-docs/blob/main/CONTRIBUTING.md): open an issue describing the integration first |

Before submitting the Google ADK page, consider shipping a Runner-based ADK wrapper in the SDK
(see [#1](https://github.com/ashishodu2023/cortexops/issues/1)) so the page can use `tracer.wrap(root_agent)`
directly instead of the adapter.
