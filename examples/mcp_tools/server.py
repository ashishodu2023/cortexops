"""A tiny billing MCP server used by agent.py (stdio transport). Works with mcp 1.x and 2.x."""

try:
    from mcp.server.mcpserver import MCPServer as Server
    from mcp.server.mcpserver.exceptions import ToolError
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP as Server
    from mcp.server.fastmcp.exceptions import ToolError

server = Server("billing")
_REFUNDED: set[str] = {"ORD-2"}


@server.tool()
def lookup_order(order_id: str) -> str:
    """Look up an order's amount and payment status."""
    return f"{order_id}: $42.00, paid, refunded={order_id in _REFUNDED}"


@server.tool()
def issue_refund(order_id: str, reason: str = "") -> str:
    """Refund an order. Fails if it was already refunded."""
    if order_id in _REFUNDED:
        raise ToolError(f"{order_id} was already refunded")
    _REFUNDED.add(order_id)
    return f"refund issued for {order_id}"


if __name__ == "__main__":
    server.run(transport="stdio")
