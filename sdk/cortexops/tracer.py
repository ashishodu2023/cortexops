from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from contextlib import contextmanager
from typing import Any

from .models import FailureKind, RunStatus, ToolCall, ToolCallStatus, Trace, TraceNode


class CortexTracer:
    """Instruments AI agents with zero-refactor tracing.

    Supports LangGraph StateGraph and CrewAI Crew out of the box.
    Falls back to a generic callable wrapper for any other agent type.

    Usage:
        tracer = CortexTracer(project="payments-agent")
        graph = tracer.wrap(your_langgraph_app)
        result = graph.invoke({"messages": [...]})
        trace  = tracer.last_trace()
    """

    def __init__(
        self,
        project: str,
        api_key: str | None = None,
        api_url: str = "https://api.getcortexops.com",
        environment: str = "development",
        sample_rate: float = 1.0,
        local_store: bool = True,
    ) -> None:
        self.project = project
        self.api_key = api_key
        self.api_url = api_url.rstrip("/")
        self.environment = environment
        self.sample_rate = sample_rate
        self.local_store = local_store
        self._traces: list[Trace] = []
        self._current_trace: Trace | None = None

    def wrap(self, agent: Any) -> Any:
        """Auto-detect agent type and return an instrumented wrapper."""
        agent_type = type(agent).__name__

        if agent_type == "CompiledStateGraph":
            return self._wrap_langgraph(agent)

        if agent_type == "Crew":
            return self._wrap_crewai(agent)

        if callable(agent) or hasattr(agent, "invoke"):
            return self._wrap_callable(agent)

        raise TypeError(
            f"CortexTracer.wrap() does not support {agent_type}. "
            "Pass a LangGraph CompiledStateGraph, CrewAI Crew, or any callable."
        )

    def _wrap_langgraph(self, graph: Any) -> Any:
        tracer = self

        class InstrumentedGraph:
            def invoke(self_, input: dict, config: dict | None = None, **kwargs) -> dict:
                return tracer._run_traced(
                    fn=lambda: graph.invoke(input, config, **kwargs),
                    input=input,
                    framework="langgraph",
                )

            async def ainvoke(self_, input: dict, config: dict | None = None, **kwargs) -> dict:
                import asyncio
                return await asyncio.get_event_loop().run_in_executor(
                    None, lambda: tracer._run_traced(
                        fn=lambda: graph.invoke(input, config, **kwargs),
                        input=input,
                        framework="langgraph",
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
                    input=inputs or {},
                    framework="crewai",
                )

            def __getattr__(self_, name: str):
                return getattr(crew, name)

        return InstrumentedCrew()

    def _wrap_callable(self, fn: Any) -> Any:
        tracer = self

        if hasattr(fn, "invoke"):
            # Object with .invoke() — wrap that method
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

        # Plain callable
        def wrapper(*args, **kwargs):
            input_data = {"args": list(args), "kwargs": kwargs}
            return tracer._run_traced(fn=lambda: fn(*args, **kwargs), input=input_data, framework="generic")

        return wrapper

    def _run_traced(self, fn: Callable, input: dict, framework: str) -> Any:
        trace = Trace(
            project=self.project,
            input=input,
        )
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
            name=name,
            args=args or {},
            result=result,
            status=ToolCallStatus.ERROR if error else ToolCallStatus.SUCCESS,
            latency_ms=latency_ms,
            error=error,
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
