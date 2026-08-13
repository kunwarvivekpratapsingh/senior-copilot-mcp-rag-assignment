"""Structured logging for the GitHub Issues MCP server.

Reuses the alarm server's pipeline rather than duplicating it: redaction rules and
record shape must be identical across servers, or the execution trace is
inconsistent depending on which server handled a step.
"""

from alarm_mcp.logging import configure_logging, get_logger

__all__ = ["configure_logging", "get_logger"]
