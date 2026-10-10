"""Trace Model Context Protocol (MCP) tool calls with CortexOps.

Works with `mcp.ClientSession` (mcp 1.x and 2.x) and `mcp.Client` (mcp 2.x), or any object
exposing an async `call_tool(name, arguments)`. This module never imports `mcp` itself.

Usage:
    from mcp import ClientSession
    from cortexops import CortexTracer
    from cortexops.integrations.mcp import instrument_mcp_session, trace_run

    tracer = CortexTracer(project="support-agent")

    async with ClientSession(read, write) as session:
        await session.initialize()
        instrument_mcp_session(session, tracer, server_name="github")

        async with trace_run(tracer, input={"task": "triage issue 42"}) as trace:
            issue = await session.call_tool("get_issue", {"number": 42})
            trace.output = {"summary": "..."}

Where a call is recorded:
  1. Inside `mcp_node(tracer, name)`: appended to that node's tool_calls.
  2. Inside a running trace (`trace_run(...)`, or a `tracer.wrap(...)` run in progress): a new
     node `mcp:<server>/<tool>` holding that single tool call is appended, so every call gets
     its own latency bar in the waterfall.
  3. No active trace: nothing is recorded on any trace. The call still runs and `on_tool_call`
     still fires. Orphan calls are not promoted to standalone traces because that would spend
     trace quota and detach them from the agent run they belong to.
"""
from __future__ import annotations

import inspect
import logging
import random as _random
import time
import uuid
from collections.abc import Awaitable, Callable, Iterable
from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ..models import FailureKind, RunStatus, ToolCall, ToolCallStatus, Trace, TraceNode

if TYPE_CHECKING:
    from ..tracer import CortexTracer

__all__ = [
    "DEFAULT_REDACT_KEYS",
    "MCPToolError",
    "instrument_mcp_session",
    "mcp_node",
    "trace_run",
    "truncate_value",
    "uninstrument_mcp_session",
]

logger = logging.getLogger(__name__)

# Argument keys whose values are replaced with "[REDACTED]" before a call is recorded.
# Matched case-insensitively on the whole key, its suffix, or a "<key>_" prefix.
DEFAULT_REDACT_KEYS: tuple[str, ...] = (
    "password", "passwd", "secret", "token", "api_key", "apikey",
    "authorization", "credential", "credentials", "cookie", "private_key",
)
_REDACTED = "[REDACTED]"
_MAX_ITEMS = 50
_MAX_DEPTH = 6
_PATCHED_ATTR = "_cortexops_mcp_patched"
# MCP REQUEST_TIMEOUT error codes: mcp 2.x uses JSON-RPC -32001, mcp 1.x uses HTTP 408
_TIMEOUT_CODES = frozenset({-32001, 408})


class MCPToolError(RuntimeError):
    """An MCP tool returned `isError=true` and the session was instrumented with `raise_on_error=True`."""

    def __init__(self, tool: str, message: str, result: Any = None) -> None:
        super().__init__(f"MCP tool {tool!r} returned an error: {message}")
        self.tool = tool
        self.message = message
        self.result = result


@dataclass
class _RunState:
    tracer: Any
    trace: Trace
    tool_errors: int = 0
    last_tool_exception: BaseException | None = None


_active_run: ContextVar[_RunState | None] = ContextVar("cortexops_mcp_run", default=None)
_active_node: ContextVar[tuple[Any, TraceNode] | None] = ContextVar("cortexops_mcp_node", default=None)
_in_call: ContextVar[bool] = ContextVar("cortexops_mcp_in_call", default=False)


# ── Value shaping ──────────────────────────────────────────────────────────

def truncate_value(value: Any, max_chars: int = 1000, _depth: int = 0) -> Any:
    """Return a JSON-friendly copy of `value` with long strings and large containers truncated."""
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        if len(value) <= max_chars:
            return value
        return f"{value[:max_chars]}...[truncated {len(value) - max_chars} chars]"
    if _depth >= _MAX_DEPTH:
        return truncate_value(repr(value), max_chars)
    if isinstance(value, dict):
        items = list(value.items())
        out: dict[str, Any] = {str(k): truncate_value(v, max_chars, _depth + 1) for k, v in items[:_MAX_ITEMS]}
        if len(items) > _MAX_ITEMS:
            out["..."] = f"[{len(items) - _MAX_ITEMS} more keys]"
        return out
    if isinstance(value, (list, tuple, set, frozenset)):
        seq = list(value)
        out_list = [truncate_value(v, max_chars, _depth + 1) for v in seq[:_MAX_ITEMS]]
        if len(seq) > _MAX_ITEMS:
            out_list.append(f"...[{len(seq) - _MAX_ITEMS} more items]")
        return out_list
    if hasattr(value, "model_dump"):
        try:
            dumped = value.model_dump(mode="json", by_alias=True, exclude_none=True)
        except Exception:
            dumped = None
        if dumped is not None:
            return truncate_value(dumped, max_chars, _depth + 1)
    return truncate_value(repr(value), max_chars)


def _is_sensitive_key(key: str, keys: tuple[str, ...]) -> bool:
    k = key.lower().replace("-", "_")
    return any(k == s or k.endswith(s) or k.startswith(s + "_") for s in keys)


def _redact_keys(value: Any, keys: tuple[str, ...], _depth: int = 0) -> Any:
    if not keys or _depth > _MAX_DEPTH:
        return value
    if isinstance(value, dict):
        return {
            k: _REDACTED if isinstance(k, str) and _is_sensitive_key(k, keys) else _redact_keys(v, keys, _depth + 1)
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_redact_keys(v, keys, _depth + 1) for v in value]
    return value


def _attr(obj: Any, *names: str) -> Any:
    for name in names:
        value = getattr(obj, name, None)
        if value is not None:
            return value
    return None


def _content_text(content: Any) -> str:
    parts: list[str] = []
    for block in content or []:
        kind = getattr(block, "type", None)
        if kind == "text":
            parts.append(str(getattr(block, "text", "")))
        elif kind in ("image", "audio"):
            parts.append(f"[{kind} {_attr(block, 'mime_type', 'mimeType') or ''}]".replace(" ]", "]"))
        elif kind == "resource":
            resource = getattr(block, "resource", None)
            text = getattr(resource, "text", None)
            parts.append(text if isinstance(text, str) else f"[resource {getattr(resource, 'uri', '')}]")
        elif kind == "resource_link":
            parts.append(f"[resource_link {getattr(block, 'uri', '')}]")
        elif isinstance(block, dict) and block.get("type") == "text":
            parts.append(str(block.get("text", "")))
        else:
            parts.append(f"[{kind or type(block).__name__}]")
    return "\n".join(parts)


def _summarize_result(result: Any) -> tuple[bool, Any, str | None]:
    """Return (is_error, result_summary, error_text) for an MCP CallToolResult (1.x or 2.x) or any value."""
    is_error = bool(_attr(result, "is_error", "isError"))
    content = getattr(result, "content", None)
    structured = _attr(result, "structured_content", "structuredContent")
    text = _content_text(content) if content is not None else None
    if is_error:
        return True, None, text or "MCP tool returned isError=true"
    if structured is not None:
        return False, structured, None
    if content is not None:
        return False, text, None
    return False, result, None


def _is_timeout(exc: BaseException) -> bool:
    if isinstance(exc, TimeoutError):
        return True
    code = getattr(exc, "code", None)
    if code is None:
        code = getattr(getattr(exc, "error", None), "code", None)
    return code in _TIMEOUT_CODES


def _caused_by(exc: BaseException, target: BaseException | None) -> bool:
    seen = 0
    current: BaseException | None = exc
    while current is not None and seen < 8:
        if current is target:
            return True
        current = current.__cause__ or current.__context__
        seen += 1
    return False


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


# ── Trace targeting ────────────────────────────────────────────────────────

def _active_trace(tracer: Any) -> Trace | None:
    """The trace MCP calls should land on for this tracer in the current context, if any."""
    state = _active_run.get()
    if state is not None and state.tracer is tracer:
        return state.trace
    current = getattr(tracer, "_current_trace", None)
    if current is None:
        return None
    finished = getattr(tracer, "_traces", None) or []
    # A sync tracer.wrap(...) run appends its trace to tracer._traces only when it finishes.
    if finished and finished[-1] is current:
        return None
    return current


def _detect_server_name(session: Any) -> str | None:
    try:
        info = getattr(session, "server_info", None)
    except Exception:
        return None
    name = getattr(info, "name", None)
    return name if isinstance(name, str) and name else None


# ── Instrumentation ────────────────────────────────────────────────────────

class _Recorder:
    def __init__(
        self,
        session: Any,
        tracer: CortexTracer,
        server_name: str | None,
        qualify_names: bool,
        redact_keys: tuple[str, ...],
        redact: Callable[[Any], Any] | None,
        max_value_chars: int,
        raise_on_error: bool,
        on_tool_call: Callable[[ToolCall], None] | None,
    ) -> None:
        self.session = session
        self.tracer = tracer
        self.server_name = server_name
        self.qualify_names = qualify_names
        self.redact_keys = redact_keys
        self.redact = redact
        self.max_value_chars = max_value_chars
        self.raise_on_error = raise_on_error
        self.on_tool_call = on_tool_call

    def _shape(self, value: Any, *, redact_keys: bool) -> Any:
        if redact_keys:
            value = _redact_keys(value, self.redact_keys)
        if self.redact is not None:
            try:
                value = self.redact(value)
            except Exception:
                logger.debug("cortexops mcp: redact callback failed", exc_info=True)
                value = _REDACTED
        return truncate_value(value, self.max_value_chars)

    async def run(
        self,
        tool: str,
        arguments: Any,
        invoke: Callable[[], Awaitable[Any] | Any],
        summarize: Callable[[Any], tuple[bool, Any, str | None]],
    ) -> Any:
        if _in_call.get():
            # Already inside an instrumented call (e.g. mcp.Client -> its own ClientSession): record once.
            return await _maybe_await(invoke())
        token = _in_call.set(True)
        t0 = time.perf_counter()
        try:
            result = await _maybe_await(invoke())
        except Exception as exc:
            status = ToolCallStatus.TIMEOUT if _is_timeout(exc) else ToolCallStatus.ERROR
            self._record(tool, arguments, None, status, f"{type(exc).__name__}: {exc}", t0, exc)
            raise
        finally:
            _in_call.reset(token)

        is_error, summary, error = summarize(result)
        if not is_error:
            self._record(tool, arguments, summary, ToolCallStatus.SUCCESS, None, t0, None)
            return result
        failure = MCPToolError(tool, error or "", result) if self.raise_on_error else None
        self._record(tool, arguments, None, ToolCallStatus.ERROR, error, t0, failure)
        if failure is not None:
            raise failure
        return result

    def _record(
        self,
        tool: str,
        arguments: Any,
        summary: Any,
        status: ToolCallStatus,
        error: str | None,
        t0: float,
        exc: BaseException | None,
    ) -> ToolCall:
        latency_ms = (time.perf_counter() - t0) * 1000
        server = self.server_name or _detect_server_name(self.session)
        name = f"{server}/{tool}" if server and self.qualify_names else tool
        if arguments is None:
            args: dict[str, Any] = {}
        elif isinstance(arguments, dict):
            args = dict(arguments)
        else:
            args = {"arguments": arguments}
        tc = ToolCall(
            name=name,
            args=self._shape(args, redact_keys=True),
            result=self._shape(summary, redact_keys=True) if summary is not None else None,
            status=status,
            latency_ms=latency_ms,
            error=truncate_value(error, self.max_value_chars) if error else None,
        )
        self._attach(tc, server, exc)
        if self.on_tool_call is not None:
            try:
                self.on_tool_call(tc)
            except Exception:
                logger.debug("cortexops mcp: on_tool_call callback failed", exc_info=True)
        return tc

    def _attach(self, tc: ToolCall, server: str | None, exc: BaseException | None) -> None:
        state = _active_run.get()
        if state is not None and state.tracer is self.tracer and tc.status != ToolCallStatus.SUCCESS:
            state.tool_errors += 1
            if exc is not None:
                state.last_tool_exception = exc

        open_node = _active_node.get()
        if open_node is not None and open_node[0] is self.tracer:
            open_node[1].tool_calls.append(tc)
            return

        trace = _active_trace(self.tracer)
        if trace is None:
            logger.debug("cortexops mcp: no active trace, %s not recorded", tc.name)
            return
        node_input: dict[str, Any] = {"arguments": tc.args}
        if server:
            node_input["server"] = server
        trace.nodes.append(TraceNode(
            node_id=str(uuid.uuid4()),
            node_name=f"mcp:{tc.name}",
            input=node_input,
            output={"error": tc.error} if tc.error else {"result": tc.result},
            tool_calls=[tc],
            latency_ms=tc.latency_ms,
        ))


def instrument_mcp_session(
    session: Any,
    tracer: CortexTracer,
    server_name: str | None = None,
    *,
    trace_list_tools: bool = False,
    qualify_names: bool = True,
    redact_keys: Iterable[str] = DEFAULT_REDACT_KEYS,
    redact: Callable[[Any], Any] | None = None,
    max_value_chars: int = 1000,
    raise_on_error: bool = False,
    on_tool_call: Callable[[ToolCall], None] | None = None,
) -> Any:
    """Record every `session.call_tool(...)` as a CortexOps `ToolCall`. Patches `session` in place and returns it.

    Args:
        session:          an initialized `mcp.ClientSession`, an `mcp.Client` (mcp 2.x), or any object
                          with an async `call_tool(name, arguments=None, ...)`.
        tracer:           the `CortexTracer` whose traces receive the calls.
        server_name:      label for the MCP server; tool calls are named `<server_name>/<tool>`.
                          Defaults to the server's advertised name when the session exposes it (mcp 2.x).
        trace_list_tools: also record `list_tools()` as a `<server>/list_tools` call (off by default
                          because it is not an agent action and would skew tool-accuracy metrics).
        qualify_names:    set False to record the bare tool name. Not needed for evals: ToolAccuracyMetric
                          matches a bare expected name against `<server>/<tool>` calls.
        redact_keys:      argument keys whose values are replaced with "[REDACTED]" (secrets, tokens).
                          Pass `()` to disable. The hosted API also redacts PII patterns on ingest.
        redact:           optional callable applied to recorded args and results after key redaction.
        max_value_chars:  strings longer than this are truncated (traces are capped at 128KB on ingest).
        raise_on_error:   raise `MCPToolError` when a tool returns `isError=true` instead of returning it.
        on_tool_call:     callback invoked with every recorded `ToolCall`, even when no trace is active.
    """
    if getattr(session, _PATCHED_ATTR, None) is not None:
        uninstrument_mcp_session(session)

    recorder = _Recorder(
        session, tracer, server_name, qualify_names, tuple(s.lower() for s in redact_keys),
        redact, max_value_chars, raise_on_error, on_tool_call,
    )
    instance_attrs = getattr(session, "__dict__", None)
    if instance_attrs is None:
        raise TypeError(f"cannot instrument {type(session).__name__}: instance attributes are not writable")
    original_call = session.call_tool
    patched: dict[str, tuple[bool, Any]] = {
        "call_tool": ("call_tool" in instance_attrs, instance_attrs.get("call_tool")),
    }

    async def call_tool(name: str, arguments: dict[str, Any] | None = None, *args: Any, **kwargs: Any) -> Any:
        return await recorder.run(
            name, arguments, lambda: original_call(name, arguments, *args, **kwargs), _summarize_result,
        )

    call_tool.__doc__ = getattr(original_call, "__doc__", None)
    session.call_tool = call_tool

    if trace_list_tools and hasattr(session, "list_tools"):
        original_list = session.list_tools
        patched["list_tools"] = ("list_tools" in instance_attrs, instance_attrs.get("list_tools"))

        def _summarize_tools(result: Any) -> tuple[bool, Any, str | None]:
            tools = getattr(result, "tools", None) or []
            return False, {"tools": [getattr(t, "name", str(t)) for t in tools]}, None

        async def list_tools(*args: Any, **kwargs: Any) -> Any:
            return await recorder.run("list_tools", None, lambda: original_list(*args, **kwargs), _summarize_tools)

        session.list_tools = list_tools

    setattr(session, _PATCHED_ATTR, patched)
    return session


def uninstrument_mcp_session(session: Any) -> None:
    """Undo `instrument_mcp_session`. Safe to call on a session that was never instrumented."""
    patched = getattr(session, _PATCHED_ATTR, None)
    if patched is None:
        return
    for attr, (had_own, value) in patched.items():
        if had_own:
            setattr(session, attr, value)
        else:
            try:
                delattr(session, attr)
            except AttributeError:
                pass
    delattr(session, _PATCHED_ATTR)


# ── Run / node scopes ──────────────────────────────────────────────────────

class trace_run:
    """Open a CortexOps trace around an agent run that calls MCP tools. Use with `async with` or `with`.

    Honors the tracer's sample_rate / sample_errors, tags the trace with the active prompt
    version, and ships it to the hosted API on exit. Each asyncio task gets its own trace,
    so concurrent runs on one tracer do not mix tool calls.

        async with trace_run(tracer, input={"question": q}) as trace:
            ...
            trace.output = {"answer": answer}

    A run that raises is marked failed. Its failure_kind is `tool_error` (or `timeout`) when the
    exception came from an instrumented MCP call, `unknown` otherwise. Runs that complete despite
    tool errors stay completed and carry `metadata["mcp_tool_errors"]`.
    """

    def __init__(self, tracer: CortexTracer, input: dict | None = None, *, framework: str = "mcp") -> None:
        self.tracer = tracer
        self.input = dict(input or {})
        self.framework = framework
        self.trace: Trace | None = None
        self._state: _RunState | None = None
        self._token: Token[_RunState | None] | None = None
        self._previous: Trace | None = None
        self._sampled = True
        self._t0 = 0.0

    def _enter(self) -> Trace:
        tracer = self.tracer
        self._sampled = tracer.sample_rate >= 1.0 or _random.random() < tracer.sample_rate
        # Unsampled runs are still buffered so that a failure can be shipped with its tool calls.
        trace = tracer._new_trace(self.input, sampled=self._sampled)
        trace.metadata["framework"] = self.framework
        self.trace = trace
        self._state = _RunState(tracer=tracer, trace=trace)
        self._token = _active_run.set(self._state)
        self._previous = tracer._current_trace
        tracer._current_trace = trace
        self._t0 = time.perf_counter()
        return trace

    def _exit(self, exc: BaseException | None) -> bool:
        """Finalize the trace; return True when it should be flushed to the hosted API."""
        tracer, trace, state = self.tracer, self.trace, self._state
        assert trace is not None and state is not None and self._token is not None
        trace.total_latency_ms = (time.perf_counter() - self._t0) * 1000
        _active_run.reset(self._token)
        if tracer._current_trace is trace:
            tracer._current_trace = self._previous

        if exc is not None:
            trace.status = RunStatus.FAILED
            if state.last_tool_exception is not None and _caused_by(exc, state.last_tool_exception):
                trace.failure_kind = FailureKind.TIMEOUT if _is_timeout(exc) else FailureKind.TOOL_ERROR
            else:
                trace.failure_kind = FailureKind.UNKNOWN
            trace.failure_detail = str(exc) or type(exc).__name__
        if state.tool_errors:
            trace.metadata["mcp_tool_errors"] = state.tool_errors

        if not self._sampled:
            if exc is None or not tracer.sample_errors:
                return False
            trace.metadata["captured_reason"] = "error"
        tracer._traces.append(trace)
        return bool(tracer.api_key)

    def __enter__(self) -> Trace:
        return self._enter()

    def __exit__(self, exc_type: Any, exc: BaseException | None, tb: Any) -> bool:
        if self._exit(exc) and self.trace is not None:
            self.tracer._flush_trace(self.trace)
        return False

    async def __aenter__(self) -> Trace:
        return self._enter()

    async def __aexit__(self, exc_type: Any, exc: BaseException | None, tb: Any) -> bool:
        if self._exit(exc) and self.trace is not None:
            import anyio.to_thread

            await anyio.to_thread.run_sync(self.tracer._flush_trace, self.trace)
        return False


class mcp_node:
    """Group the MCP calls made inside the block into one named trace node. Use with `async with` or `with`.

        async with trace_run(tracer, input=...):
            async with mcp_node(tracer, "research") as node:
                await session.call_tool("search", {"q": "refund policy"})
                await session.call_tool("fetch", {"url": url})
                node.output = {"sources": 2}
    """

    def __init__(self, tracer: CortexTracer, name: str) -> None:
        self.tracer = tracer
        self.name = name
        self.node: TraceNode | None = None
        self._token: Token[tuple[Any, TraceNode] | None] | None = None
        self._t0 = 0.0

    def __enter__(self) -> TraceNode:
        self.node = TraceNode(node_id=str(uuid.uuid4()), node_name=self.name)
        self._token = _active_node.set((self.tracer, self.node))
        self._t0 = time.perf_counter()
        return self.node

    def __exit__(self, exc_type: Any, exc: BaseException | None, tb: Any) -> bool:
        assert self.node is not None and self._token is not None
        self.node.latency_ms = (time.perf_counter() - self._t0) * 1000
        _active_node.reset(self._token)
        trace = _active_trace(self.tracer)
        if trace is not None:
            trace.nodes.append(self.node)
        return False

    async def __aenter__(self) -> TraceNode:
        return self.__enter__()

    async def __aexit__(self, exc_type: Any, exc: BaseException | None, tb: Any) -> bool:
        return self.__exit__(exc_type, exc, tb)
