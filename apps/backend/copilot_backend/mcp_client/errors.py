"""MCP client failure modes.

The brief names four failure modes explicitly — invalid arguments, unavailable
tools, unreachable servers, and partial failure mid-chain. Each gets its own type so
the orchestrator can respond appropriately rather than treating every failure as
equally fatal.
"""

from __future__ import annotations


class McpClientError(Exception):
    """Base for failures originating in the client rather than in a tool."""

    error_code = "MCP_CLIENT_ERROR"


class ServerUnavailableError(McpClientError):
    """An MCP server could not be reached.

    The registry marks the server degraded and the planner is told its tools are
    unavailable, so it plans around the gap instead of producing a plan that cannot
    run.
    """

    error_code = "SERVER_UNAVAILABLE"


class ToolNotFoundError(McpClientError):
    """The requested tool is not in the discovered registry.

    Raised before any network call. A plan naming a tool that does not exist is
    rejected rather than attempted.
    """

    error_code = "TOOL_NOT_FOUND"


class InvalidToolArgumentsError(McpClientError):
    """Arguments failed validation against the tool's published input schema.

    Raised **before** the network call. Sending arguments we already know are invalid
    wastes a round trip to learn what the schema already told us.
    """

    error_code = "INVALID_INPUT"

    def __init__(self, message: str, *, violations: list[str] | None = None) -> None:
        super().__init__(message)
        self.violations = violations or []
