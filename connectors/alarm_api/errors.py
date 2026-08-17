"""Typed exceptions for the Alarm Management API client.

The connector translates every failure into one of these before it leaves the
module. Callers branch on the exception type, never on an HTTP status code or a
message string, so a change to the API's wording cannot break error handling.

Each type maps onto exactly one stable MCP ``error_code`` — see
``alarm_mcp/mapping.py`` and LLD §8.
"""

from __future__ import annotations


class AlarmApiError(Exception):
    """Base for every failure reaching the caller from the Alarm Management API."""

    #: Stable code the MCP layer surfaces to the orchestrator.
    error_code: str = "UPSTREAM_ERROR"
    #: Whether retrying the identical request could plausibly succeed.
    retryable: bool = False

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        trace_id: str | None = None,
        upstream_code: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.trace_id = trace_id
        self.upstream_code = upstream_code

    def __str__(self) -> str:
        parts = [self.message]
        if self.status_code is not None:
            parts.append(f"status={self.status_code}")
        if self.trace_id:
            parts.append(f"trace_id={self.trace_id}")
        return " ".join(parts)


class AlarmApiAuthError(AlarmApiError):
    """401 — the bearer token is missing, malformed, or wrong.

    Never retried. A token that is wrong now will be wrong on the next attempt, and
    retrying only delays a clear signal that configuration is broken.
    """

    error_code = "AUTH_FAILED"
    retryable = False


class AlarmApiNotFound(AlarmApiError):
    """404 — the requested asset, alarm, or calculation does not exist."""

    error_code = "NOT_FOUND"
    retryable = False


class AlarmApiInvalidInput(AlarmApiError):
    """400 or 422 — the request failed validation.

    Not retried: the same arguments will fail identically. This is the signal the
    orchestrator uses to stop rather than to wait.
    """

    error_code = "INVALID_INPUT"
    retryable = False


class AlarmApiUpstreamError(AlarmApiError):
    """5xx — the source system failed. Worth retrying."""

    error_code = "UPSTREAM_5XX"
    retryable = True


class AlarmApiTimeout(AlarmApiError):
    """The request exceeded its deadline, or the connection could not be made."""

    error_code = "TIMEOUT"
    retryable = True
