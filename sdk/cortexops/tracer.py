from __future__ import annotations

import os
import time
import uuid
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .models import FailureKind, RunStatus, ToolCall, ToolCallStatus, Trace, TraceNode

# ── Key resolution order ───────────────────────────────────────────────────
# 1. Explicit api_key argument
# 2. CORTEXOPS_API_KEY environment variable
# 3. ~/.cortexops/credentials file  (written by `cortexops login`)
# 4. None → local-only mode, no hosted tracing

_CREDENTIALS_FILE = Path.home() / ".cortexops" / "credentials"
_DEFAULT_API_URL   = "https://api.getcortexops.com"
_ENV_KEY           = "CORTEXOPS_API_KEY"
_ENV_URL           = "CORTEXOPS_API_URL"
_ENV_PROJECT       = "CORTEXOPS_PROJECT"
_ENV_ENV           = "CORTEXOPS_ENVIRONMENT"


def _resolve_api_key(explicit: str | None) -> str | None:
    """Resolve API key from multiple sources in priority order."""
    if explicit:
        return explicit
    # Environment variable
    if env_key := os.getenv(_ENV_KEY):
        return env_key
    # Credentials file written by `cortexops login`
    if _CREDENTIALS_FILE.exists():
        try:
            import json
            creds = json.loads(_CREDENTIALS_FILE.read_text())
            return creds.get("api_key")
        except Exception:
            pass
    return None


def _resolve_api_url(explicit: str) -> str:
    """Resolve API URL — explicit arg > env var > default."""
    if explicit != _DEFAULT_API_URL:
        return explicit.rstrip("/")
    return os.getenv(_ENV_URL, _DEFAULT_API_URL).rstrip("/")


class CortexTracer:
    """Instruments AI agents with zero-refactor tracing.

    API key resolution order (most to least specific):
      1. api_key argument
      2. CORTEXOPS_API_KEY environment variable
      3. ~/.cortexops/credentials (written by `cortexops login`)
      4. None — local-only mode, traces stored in memory only

    Usage:
        # Explicit key
        tracer = CortexTracer(project="payments-agent", api_key="cxo-...")

        # From environment variable (recommended for CI)
        # export CORTEXOPS_API_KEY=cxo-...
        tracer = CortexTracer(project="payments-agent")

        # After `cortexops login` (recommended for local dev)
        tracer = CortexTracer(project="payments-agent")

        graph = tracer.wrap(your_langgraph_app)
        result = graph.invoke({"messages": [...]})
        trace  = tracer.last_trace()
    """

    def __init__(
        self,
        project: str | None = None,
        api_key: str | None = None,
        api_url: str = _DEFAULT_API_URL,
        environment: str | None = None,
        sample_rate: float = 1.0,
        local_store: bool = True,
    ) -> None:
        # Project: arg > env var
        self.project     = project or os.getenv(_ENV_PROJECT) or "default"
        # Key: auto-resolved from all sources
        self.api_key     = _resolve_api_key(api_key)
        self.api_url     = _resolve_api_url(api_url)
        # Environment: arg > env var > "development"
        self.environment = environment or os.getenv(_ENV_ENV, "development")
        self.sample_rate = sample_rate
        self.local_store = local_store
        self._traces: list[Trace] = []
        self._current_trace: Trace | None = None

        # Inform user where key came from — only in development
        if self.environment == "development" and self.api_key:
            source = "argument"
            if not api_key:
                if os.getenv(_ENV_KEY):
                    source = f"env:{_ENV_KEY}"
                elif _CREDENTIALS_FILE.exists():
                    source = "~/.cortexops/credentials"
            if source != "argument":
                import logging
                logging.getLogger(__name__).debug(
                    "CortexTracer: api_key loaded from %s", source
                )

    @property
    def is_hosted(self) -> bool:
        """True if traces will be shipped to the hosted API."""
        return bool(self.api_key)

    # ── Framework detection helpers ─────────────────────────────────────

    @staticmethod
    def _detect_framework(agent: Any) -> str:
        """Return a string identifying the agent framework."""
        t = type(agent)
        name = t.__name__
        module = t.__module__ or ""

        # LangGraph
        if name == "CompiledStateGraph":
            return "langgraph"
        # CrewAI
        if name == "Crew" and "crewai" in module:
            return "crewai"
        # OpenAI Agents SDK — Agent class
        if name == "Agent" and "agents" in module:
            return "openai_agents"
        # PydanticAI — Agent class
        if name == "Agent" and "pydantic_ai" in module:
            return "pydantic_ai"
        # Agno / Phidata
        if "agno" in module or "phi" in module:
            return "agno"
        # AutoGen — ConversableAgent, AssistantAgent, UserProxyAgent
        if "autogen" in module and hasattr(agent, "initiate_chat"):
            return "autogen"
        # Google ADK
        if "google" in module and "adk" in module:
            return "google_adk"
        # Smolagents (HuggingFace)
        if "smolagents" in module and hasattr(agent, "run"):
            return "smolagents"
        # LlamaIndex — query engine or chat engine
        if "llama_index" in module or "llama-index" in module:
            if hasattr(agent, "query"):
                return "llamaindex_query"
            if hasattr(agent, "chat"):
                return "llamaindex_chat"
        # Haystack Pipeline
        if name == "Pipeline" and "haystack" in module:
            return "haystack"
        # DSPy — Module subclass with forward()
        if "dspy" in module and hasattr(agent, "forward"):
            return "dspy"
        # Generic fallback
        return "generic"

    def wrap(self, agent: Any) -> Any:
        """
        Auto-detect agent framework and return an instrumented wrapper.

        Supported frameworks:
            LangGraph      — CompiledStateGraph (invoke / ainvoke / stream)
            CrewAI         — Crew (kickoff / kickoff_async)
            OpenAI Agents  — Agent (Runner.run / Runner.run_sync)
            PydanticAI     — Agent (run_sync / run / run_stream)
            Agno           — Agent (run / arun / print_response)
            AutoGen        — ConversableAgent (initiate_chat)
            Google ADK     — Agent (run)
            Smolagents     — CodeAgent / ToolCallingAgent (run)
            LlamaIndex     — query engine (query) / chat engine (chat)
            Haystack       — Pipeline (run)
            DSPy           — Module subclass (forward / __call__)
            Generic        — Any Python callable or object with .invoke()
        """
        framework = self._detect_framework(agent)
        dispatch = {
            "langgraph":       self._wrap_langgraph,
            "crewai":          self._wrap_crewai,
            "openai_agents":   self._wrap_openai_agents,
            "pydantic_ai":     self._wrap_pydantic_ai,
            "agno":            self._wrap_agno,
            "autogen":         self._wrap_autogen,
            "google_adk":      self._wrap_google_adk,
            "smolagents":      self._wrap_smolagents,
            "llamaindex_query":self._wrap_llamaindex_query,
            "llamaindex_chat": self._wrap_llamaindex_chat,
            "haystack":        self._wrap_haystack,
            "dspy":            self._wrap_dspy,
            "generic":         self._wrap_callable,
        }
        wrapper_fn = dispatch.get(framework, self._wrap_callable)
        return wrapper_fn(agent)

    def _wrap_langgraph(self, graph: Any) -> Any:
        tracer = self

        class InstrumentedGraph:
            def invoke(self_, input: dict, config: dict | None = None, **kwargs) -> dict:
                return tracer._run_traced(
                    fn=lambda: graph.invoke(input, config, **kwargs),
                    input=input, framework="langgraph",
                )

            async def ainvoke(self_, input: dict, config: dict | None = None, **kwargs) -> dict:
                import asyncio
                return await asyncio.get_event_loop().run_in_executor(
                    None, lambda: tracer._run_traced(
                        fn=lambda: graph.invoke(input, config, **kwargs),
                        input=input, framework="langgraph",
                    )
                )

            def stream(self_, input: dict, config: dict | None = None, **kwargs):
                return graph.stream(input, config, **kwargs)

            def __getattr__(self_, name: str):
                return getattr(graph, name)

        return InstrumentedGraph()

    def _wrap_crewai(self, crew: Any) -> Any:
        tracer = self

        class InstrumentedCrew:
            def kickoff(self_, inputs: dict | None = None) -> Any:
                return tracer._run_traced(
                    fn=lambda: crew.kickoff(inputs=inputs),
                    input=inputs or {}, framework="crewai",
                )

            def __getattr__(self_, name: str):
                return getattr(crew, name)

        return InstrumentedCrew()

    def _wrap_callable(self, fn: Any) -> Any:
        tracer = self

        if hasattr(fn, "invoke"):
            original_invoke = fn.invoke

            class InvokeWrapper:
                def invoke(self_, *args, **kwargs):
                    input_data = args[0] if args else kwargs
                    return tracer._run_traced(
                        fn=lambda: original_invoke(*args, **kwargs),
                        input=input_data if isinstance(input_data, dict) else {"input": input_data},
                        framework="generic",
                    )

                def __getattr__(self_, name: str):
                    return getattr(fn, name)

            return InvokeWrapper()

        def wrapper(*args, **kwargs):
            input_data = {"args": list(args), "kwargs": kwargs}
            return tracer._run_traced(fn=lambda: fn(*args, **kwargs), input=input_data, framework="generic")

        return wrapper

    # ── OpenAI Agents SDK ────────────────────────────────────────────────
    def _wrap_openai_agents(self, agent: Any) -> Any:
        """
        Wrap an OpenAI Agents SDK Agent.

        Usage:
            from agents import Agent, Runner
            from cortexops import CortexTracer

            my_agent = Agent(name="refund-agent", instructions="...")
            tracer   = CortexTracer(project="payments-agent")
            wrapped  = tracer.wrap(my_agent)

            # Sync
            result = wrapped.run_sync("Process refund for order #4821")

            # Async
            result = await wrapped.run("Process refund for order #4821")
        """
        tracer = self

        class InstrumentedOpenAIAgent:
            def run_sync(self_, prompt: str, **kwargs) -> Any:
                try:
                    from agents import Runner
                except ImportError:
                    raise ImportError("pip install openai-agents")
                return tracer._run_traced(
                    fn=lambda: Runner.run_sync(agent, prompt, **kwargs),
                    input={"prompt": prompt},
                    framework="openai_agents",
                )

            async def run(self_, prompt: str, **kwargs) -> Any:
                try:
                    from agents import Runner
                except ImportError:
                    raise ImportError("pip install openai-agents")
                import asyncio
                return await asyncio.get_event_loop().run_in_executor(
                    None, lambda: Runner.run_sync(agent, prompt, **kwargs)
                )

            def __getattr__(self_, name: str) -> Any:
                return getattr(agent, name)

        return InstrumentedOpenAIAgent()

    # ── PydanticAI ────────────────────────────────────────────────────────
    def _wrap_pydantic_ai(self, agent: Any) -> Any:
        """
        Wrap a PydanticAI Agent.

        Usage:
            from pydantic_ai import Agent
            from cortexops import CortexTracer

            my_agent = Agent("openai:gpt-4o", instructions="...")
            tracer   = CortexTracer(project="payments-agent")
            wrapped  = tracer.wrap(my_agent)

            result = wrapped.run_sync("Process refund for order #4821")
            print(result.data)
        """
        tracer = self

        class InstrumentedPydanticAgent:
            def run_sync(self_, prompt: str, **kwargs) -> Any:
                return tracer._run_traced(
                    fn=lambda: agent.run_sync(prompt, **kwargs),
                    input={"prompt": prompt},
                    framework="pydantic_ai",
                )

            async def run(self_, prompt: str, **kwargs) -> Any:
                return await agent.run(prompt, **kwargs)

            def __getattr__(self_, name: str) -> Any:
                return getattr(agent, name)

        return InstrumentedPydanticAgent()

    # ── Agno (Phidata) ────────────────────────────────────────────────────
    def _wrap_agno(self, agent: Any) -> Any:
        """
        Wrap an Agno (formerly Phidata) Agent.

        Usage:
            from agno.agent import Agent
            from agno.models.openai import OpenAIChat
            from cortexops import CortexTracer

            my_agent = Agent(model=OpenAIChat(id="gpt-4o"), ...)
            tracer   = CortexTracer(project="payments-agent")
            wrapped  = tracer.wrap(my_agent)

            result = wrapped.run("Process refund for order #4821")
        """
        tracer = self

        class InstrumentedAgnoAgent:
            def run(self_, message: str, **kwargs) -> Any:
                return tracer._run_traced(
                    fn=lambda: agent.run(message, **kwargs),
                    input={"message": message},
                    framework="agno",
                )

            def print_response(self_, message: str, **kwargs) -> Any:
                return tracer._run_traced(
                    fn=lambda: agent.print_response(message, **kwargs),
                    input={"message": message},
                    framework="agno",
                )

            async def arun(self_, message: str, **kwargs) -> Any:
                import asyncio
                return await asyncio.get_event_loop().run_in_executor(
                    None, lambda: agent.run(message, **kwargs)
                )

            def __getattr__(self_, name: str) -> Any:
                return getattr(agent, name)

        return InstrumentedAgnoAgent()

    # ── AutoGen ───────────────────────────────────────────────────────────
    def _wrap_autogen(self, agent: Any) -> Any:
        """
        Wrap an AutoGen ConversableAgent / AssistantAgent.

        Usage:
            import autogen
            from cortexops import CortexTracer

            assistant = autogen.AssistantAgent("assistant", llm_config={...})
            tracer    = CortexTracer(project="payments-agent")
            wrapped   = tracer.wrap(assistant)

            user_proxy.initiate_chat(wrapped, message="Process refund")
        """
        tracer = self
        original_initiate = agent.initiate_chat

        class InstrumentedAutoGenAgent:
            def initiate_chat(self_, recipient: Any, message: str, **kwargs) -> Any:
                return tracer._run_traced(
                    fn=lambda: original_initiate(recipient, message=message, **kwargs),
                    input={"message": message},
                    framework="autogen",
                )

            def __getattr__(self_, name: str) -> Any:
                return getattr(agent, name)

        return InstrumentedAutoGenAgent()

    # ── Google ADK ────────────────────────────────────────────────────────
    def _wrap_google_adk(self, agent: Any) -> Any:
        """
        Wrap a Google Agent Development Kit (ADK) agent.

        Usage:
            from google.adk.agents import Agent
            from cortexops import CortexTracer

            my_agent = Agent(name="refund-agent", model="gemini-2.0-flash", ...)
            tracer   = CortexTracer(project="payments-agent")
            wrapped  = tracer.wrap(my_agent)

            result = wrapped.run("Process refund for order #4821")
        """
        tracer = self

        class InstrumentedGoogleADK:
            def run(self_, message: str, **kwargs) -> Any:
                return tracer._run_traced(
                    fn=lambda: agent.run(message, **kwargs),
                    input={"message": message},
                    framework="google_adk",
                )

            def __getattr__(self_, name: str) -> Any:
                return getattr(agent, name)

        return InstrumentedGoogleADK()

    # ── Smolagents (HuggingFace) ──────────────────────────────────────────
    def _wrap_smolagents(self, agent: Any) -> Any:
        """
        Wrap a HuggingFace Smolagents CodeAgent or ToolCallingAgent.

        Usage:
            from smolagents import CodeAgent, HfApiModel
            from cortexops import CortexTracer

            my_agent = CodeAgent(tools=[...], model=HfApiModel())
            tracer   = CortexTracer(project="payments-agent")
            wrapped  = tracer.wrap(my_agent)

            result = wrapped.run("Process refund for order #4821")
        """
        tracer = self

        class InstrumentedSmolagent:
            def run(self_, task: str, **kwargs) -> Any:
                return tracer._run_traced(
                    fn=lambda: agent.run(task, **kwargs),
                    input={"task": task},
                    framework="smolagents",
                )

            def __getattr__(self_, name: str) -> Any:
                return getattr(agent, name)

        return InstrumentedSmolagent()

    # ── LlamaIndex ────────────────────────────────────────────────────────
    def _wrap_llamaindex_query(self, engine: Any) -> Any:
        """
        Wrap a LlamaIndex query engine.

        Usage:
            from llama_index.core import VectorStoreIndex
            from cortexops import CortexTracer

            index  = VectorStoreIndex.from_documents(docs)
            engine = index.as_query_engine()
            tracer = CortexTracer(project="payments-agent")
            wrapped = tracer.wrap(engine)

            result = wrapped.query("What are the refund policies?")
        """
        tracer = self

        class InstrumentedQueryEngine:
            def query(self_, query_str: str, **kwargs) -> Any:
                return tracer._run_traced(
                    fn=lambda: engine.query(query_str, **kwargs),
                    input={"query": query_str},
                    framework="llamaindex",
                )

            def __getattr__(self_, name: str) -> Any:
                return getattr(engine, name)

        return InstrumentedQueryEngine()

    def _wrap_llamaindex_chat(self, engine: Any) -> Any:
        """
        Wrap a LlamaIndex chat engine.

        Usage:
            engine = index.as_chat_engine()
            tracer = CortexTracer(project="payments-agent")
            wrapped = tracer.wrap(engine)

            result = wrapped.chat("Process refund for order #4821")
        """
        tracer = self

        class InstrumentedChatEngine:
            def chat(self_, message: str, **kwargs) -> Any:
                return tracer._run_traced(
                    fn=lambda: engine.chat(message, **kwargs),
                    input={"message": message},
                    framework="llamaindex",
                )

            def __getattr__(self_, name: str) -> Any:
                return getattr(engine, name)

        return InstrumentedChatEngine()

    # ── Haystack ──────────────────────────────────────────────────────────
    def _wrap_haystack(self, pipeline: Any) -> Any:
        """
        Wrap a Haystack Pipeline.

        Usage:
            from haystack import Pipeline
            from cortexops import CortexTracer

            pipeline = Pipeline()
            pipeline.add_component("retriever", ...)
            pipeline.add_component("llm", ...)

            tracer  = CortexTracer(project="payments-agent")
            wrapped = tracer.wrap(pipeline)

            result = wrapped.run({"retriever": {"query": "refund policy"}})
        """
        tracer = self

        class InstrumentedHaystackPipeline:
            def run(self_, data: dict, **kwargs) -> Any:
                return tracer._run_traced(
                    fn=lambda: pipeline.run(data, **kwargs),
                    input=data,
                    framework="haystack",
                )

            def __getattr__(self_, name: str) -> Any:
                return getattr(pipeline, name)

        return InstrumentedHaystackPipeline()

    # ── DSPy ─────────────────────────────────────────────────────────────
    def _wrap_dspy(self, module: Any) -> Any:
        """
        Wrap a DSPy Module (any subclass with forward() / __call__()).

        Usage:
            import dspy
            from cortexops import CortexTracer

            class RefundClassifier(dspy.Module):
                def __init__(self):
                    self.predict = dspy.Predict("query -> action")

                def forward(self, query: str):
                    return self.predict(query=query)

            my_module = RefundClassifier()
            tracer    = CortexTracer(project="payments-agent")
            wrapped   = tracer.wrap(my_module)

            result = wrapped("Process refund for order #4821")
        """
        tracer = self

        class InstrumentedDSPyModule:
            def forward(self_, *args, **kwargs) -> Any:
                input_data = {"args": list(args), **kwargs}
                return tracer._run_traced(
                    fn=lambda: module.forward(*args, **kwargs),
                    input=input_data,
                    framework="dspy",
                )

            def __call__(self_, *args, **kwargs) -> Any:
                return self_.forward(*args, **kwargs)

            def __getattr__(self_, name: str) -> Any:
                return getattr(module, name)

        return InstrumentedDSPyModule()


    def _run_traced(self, fn: Callable, input: dict, framework: str) -> Any:
        import random
        if self.sample_rate < 1.0 and random.random() > self.sample_rate:
            return fn()

        trace = Trace(project=self.project, input=input)
        self._current_trace = trace
        t0 = time.perf_counter()

        try:
            result = fn()
            trace.total_latency_ms = (time.perf_counter() - t0) * 1000
            trace.status = RunStatus.COMPLETED
            trace.output = result if isinstance(result, dict) else {"result": str(result)}
        except Exception as exc:
            trace.total_latency_ms = (time.perf_counter() - t0) * 1000
            trace.status = RunStatus.FAILED
            trace.failure_kind = FailureKind.UNKNOWN
            trace.failure_detail = str(exc)
            raise
        finally:
            self._traces.append(trace)
            if self.api_key:
                self._flush_trace(trace)

        return result

    @contextmanager
    def trace_node(self, node_name: str):
        """Context manager to manually instrument a single node."""
        node = TraceNode(node_id=str(uuid.uuid4()), node_name=node_name)
        t0 = time.perf_counter()
        try:
            yield node
        finally:
            node.latency_ms = (time.perf_counter() - t0) * 1000
            if self._current_trace:
                self._current_trace.nodes.append(node)

    def record_tool_call(
        self,
        name: str,
        args: dict | None = None,
        result: Any = None,
        error: str | None = None,
        latency_ms: float = 0.0,
    ) -> ToolCall:
        """Manually record a tool call onto the current active trace."""
        tc = ToolCall(
            name=name, args=args or {}, result=result,
            status=ToolCallStatus.ERROR if error else ToolCallStatus.SUCCESS,
            latency_ms=latency_ms, error=error,
        )
        if self._current_trace and self._current_trace.nodes:
            self._current_trace.nodes[-1].tool_calls.append(tc)
        return tc

    def last_trace(self) -> Trace | None:
        return self._traces[-1] if self._traces else None

    def traces(self) -> list[Trace]:
        return list(self._traces)

    def clear(self) -> None:
        self._traces.clear()
        self._current_trace = None

    def _flush_trace(self, trace: Trace) -> None:
        try:
            import httpx
            httpx.post(
                f"{self.api_url}/v1/traces",
                json=trace.model_dump(mode="json"),
                headers={"X-API-Key": self.api_key},
                timeout=2.0,
            )
        except Exception:
            pass  # non-blocking — tracing never breaks the agent