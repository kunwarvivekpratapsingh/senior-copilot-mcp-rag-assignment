"""Error mapping — source-system failures to stable MCP tool errors.

The orchestrator must be able to branch on *why* a tool failed: an invalid argument
means stop and rephrase, a timeout means the step is degraded but the run continues,
an auth failure means configuration is broken. Branching on prose would break the
first time a message was reworded.

So every failure is raised with a machine-readable prefix::

    [TIMEOUT] Request exceeded 5.0s (trace_id=trace-abc123)

The prefix is the contract. :func:`parse_error_code` on the client side reads it back.
See LLD §8 for the full mapping table.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from functools import wraps
from typing import Any, ParamSpec, TypeVar

from alarm_api import AlarmApiError

from .logging import get_logger

P = ParamSpec("P")
R = TypeVar("R")

logger = get_logger(__name__)

#: Matches the machine-readable prefix on a tool error message.
ERROR_CODE_PATTERN = re.compile(r"^\[([A-Z_0-9]+)\]\s*(.*)", re.DOTALL)

#: Every code a tool on this server can raise. The orchestrator switches on these.
ERROR_CODES = frozenset(
    {
        "AUTH_FAILED",      # bearer token missing, malformed, or rejected
        "NOT_FOUND",        # asset, alarm, or calculation does not exist
        "INVALID_INPUT",    # arguments failed validation upstream
        "UPSTREAM_5XX",     # source system failed after retries
        "TIMEOUT",          # deadline exceeded or connection refused
        "INTERNAL_ERROR",   # defect in this server
    }
)


class ToolError(RuntimeError):
    """A tool failure carrying a stable, machine-readable code."""

    def __init__(self, error_code: str, message: str, *, trace_id: str | None = None) -> None:
        self.error_code = error_code
        self.trace_id = trace_id
        suffix = f" (trace_id={trace_id})" if trace_id else ""
        super().__init__(f"[{error_code}] {message}{suffix}")


def parse_error_code(message: str) -> tuple[str, str]:
    """Recover ``(error_code, message)`` from a formatted tool error.

    Returns ``("INTERNAL_ERROR", message)`` when the prefix is absent, so an
    unexpected failure is still classified rather than crashing the caller.
    """
    match = ERROR_CODE_PATTERN.match(message.strip())
    if not match:
        return "INTERNAL_ERROR", message
    code, remainder = match.group(1), match.group(2)
    return (code if code in ERROR_CODES else "INTERNAL_ERROR"), remainder


def to_tool_error(exc: Exception, *, trace_id: str | None = None) -> ToolError:
    """Translate any exception into a :class:`ToolError`."""
    if isinstance(exc, ToolError):
        return exc
    if isinstance(exc, AlarmApiError):
        return ToolError(
            exc.error_code, exc.message, trace_id=exc.trace_id or trace_id
        )
    # An unexpected failure is a defect here, not upstream. Say so rather than
    # blaming the source system.
    return ToolError("INTERNAL_ERROR", f"{type(exc).__name__}: {exc}", trace_id=trace_id)


def tool_errors(
    tool_name: str,
) -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Awaitable[R]]]:
    """Decorator: translate failures and log one structured record per invocation.

    Applied to every tool so error handling and observability are uniform. A tool
    that forgot to log would be invisible in the execution trace, which is the one
    thing the GUI cannot render around.
    """

    def decorator(func: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
        @wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            import time

            trace_id = kwargs.get("trace_id")
            started = time.perf_counter()
            try:
                result = await func(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001 — deliberately total
                error = to_tool_error(exc, trace_id=trace_id if isinstance(trace_id, str) else None)
                logger.warning(
                    "mcp_tool_failed",
                    mcp_server="alarm-management",
                    mcp_tool=tool_name,
                    error_code=error.error_code,
                    # The upstream status, when the failure came from the API rather
                    # than from us. It is the field that separates "the source system
                    # rejected this" from "we never reached it".
                    api_status_code=getattr(exc, "status_code", None),
                    duration_ms=round((time.perf_counter() - started) * 1000, 2),
                    trace_id=error.trace_id,
                    outcome="error",
                )
                raise error from exc

            logger.info(
                "mcp_tool_succeeded",
                mcp_server="alarm-management",
                mcp_tool=tool_name,
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
                trace_id=_extract_trace(result),
                outcome="success",
            )
            return result

        return wrapper

    return decorator


def _extract_trace(result: Any) -> str | None:
    meta = getattr(result, "meta", None)
    return getattr(meta, "trace_id", None)
