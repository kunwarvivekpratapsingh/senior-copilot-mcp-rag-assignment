"""Alarm Management MCP server.

Exposes the Alarm Management API as typed MCP tools. Independently runnable and
testable — it needs no copilot, no language model, and no GUI:

    python -m alarm_mcp                    # stdio
    python -m alarm_mcp --transport http   # streamable HTTP
"""

from .mapping import ERROR_CODES, ToolError, parse_error_code

__all__ = ["ERROR_CODES", "ToolError", "parse_error_code"]
