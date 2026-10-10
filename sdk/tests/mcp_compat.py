"""Connect to an in-process MCP server with whichever mcp major version is installed (tests only)."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import Any


@asynccontextmanager
async def connect(server: Any):
    """Yield an initialized client over the in-memory JSON-RPC transport.

    mcp 2.x: `mcp.Client` (legacy handshake mode keeps real JSON-RPC framing).
    mcp 1.x: a `ClientSession` from `create_connected_server_and_client_session`.
    """
    try:
        from mcp import Client
    except ImportError:
        from mcp.shared.memory import create_connected_server_and_client_session

        async with create_connected_server_and_client_session(server._mcp_server) as session:
            yield session
        return
    async with Client(server, mode="legacy") as client:
        yield client


def session_of(client: Any) -> Any:
    """The underlying ClientSession (mcp 2.x Client wraps one; mcp 1.x already is one)."""
    return getattr(client, "session", client)


def is_error(result: Any) -> bool:
    return bool(getattr(result, "is_error", None) or getattr(result, "isError", None))


def text(result: Any) -> str:
    return "\n".join(getattr(block, "text", "") for block in result.content)


def payload(result: Any) -> Any:
    assert not is_error(result), text(result)
    return json.loads(text(result))


def server_class() -> Any:
    try:
        from mcp.server.mcpserver import MCPServer

        return MCPServer
    except ImportError:
        from mcp.server.fastmcp import FastMCP

        return FastMCP


def tool_error_class() -> type[Exception]:
    """Exception a tool raises to return its message to the client (mcp 2.x hides other exception text)."""
    try:
        from mcp.server.mcpserver.exceptions import ToolError
    except ImportError:
        from mcp.server.fastmcp.exceptions import ToolError
    return ToolError
