"""Schema-aware tool invocation.

Every call returns a :class:`ToolResult` — on success **and** on failure. One uniform
envelope is what lets the execution-timeline UI and the structured logs consume the
same object, so a field added for one is automatically available to the other.

Arguments are validated against the tool's published input schema **before** the
network call. Sending arguments we already know are invalid spends a round trip to
learn what the schema already told us, and the resulting error is worse: it arrives
as an upstream failure rather than as a clear statement that the plan was wrong.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any

from jsonschema import Draft202012Validator

from ..telemetry import get_logger
from .errors import (
    InvalidToolArgumentsError,
    McpClientError,
    ServerUnavailableError,
    ToolNotFoundError,
)
from .registry import ToolRegistry

logger = get_logger(__name__)

# Recovers the "[CODE] message" prefix the MCP servers attach, since the SDK wraps
# raised exceptions in its own type and discards custom attributes.
_ERROR_PREFIX = re.compile(r"\[([A-Z_0-9]+)\]\s*(.*)", re.DOTALL)


@dataclass
class ToolResult:
    """The outcome of one tool invocation, successful or not."""

    ok: bool
    server: str
    tool: str
    arguments: dict[str, Any]
    output: dict[str, Any] | None = None
    error_code: str | None = None
    error_message: str | None = None
    duration_ms: float = 0.0
    trace_id: str | None = None
    retry_count: int = 0

    def summary(self) -> str:
        """One line for the answer's evidence list and the timeline card."""
        if self.ok:
            return f"{self.server}/{self.tool} succeeded in {self.duration_ms:.0f}ms"
        return f"{self.server}/{self.tool} failed: {self.error_code} — {self.error_message}"

    def to_log_fields(self) -> dict[str, Any]:
        """The graded observability fields for this invocation."""
        return {
            "mcp_server": self.server,
            "mcp_tool": self.tool,
            "duration_ms": round(self.duration_ms, 2),
            "outcome": "success" if self.ok else "error",
            "error_code": self.error_code,
            "retry_count": self.retry_count,
            "trace_id": self.trace_id,
        }


@dataclass
class ToolInvoker:
    """Validates and invokes tools against a discovered registry."""

    registry: ToolRegistry
    _validators: dict[str, Draft202012Validator] = field(default_factory=dict)

    def _validator(self, tool_name: str) -> Draft202012Validator:
        """Compile once per tool. Schema compilation is not free and the schema is
        fixed for the process lifetime."""
        if tool_name not in self._validators:
            spec = self.registry.get(tool_name)
            self._validators[tool_name] = Draft202012Validator(spec.input_schema or {})
        return self._validators[tool_name]

    def validate(self, tool_name: str, arguments: dict[str, Any]) -> None:
        """Check arguments against the published schema, or explain exactly why not.

        Raises :class:`InvalidToolArgumentsError` listing every violation rather than
        the first, so a caller can fix one plan instead of iterating one field at a
        time.
        """
        validator = self._validator(tool_name)
        errors = sorted(validator.iter_errors(arguments), key=lambda e: list(e.path))
        if not errors:
            return
        violations = [
            f"{'.'.join(str(p) for p in err.path) or '<root>'}: {err.message}"
            for err in errors
        ]
        raise InvalidToolArgumentsError(
            f"Arguments for {tool_name!r} do not match its schema: " + "; ".join(violations),
            violations=violations,
        )

    async def invoke(
        self, tool_name: str, arguments: dict[str, Any], *, trace_id: str | None = None
    ) -> ToolResult:
        """Call a tool, returning a uniform result whatever happens.

        Client-side failures — unknown tool, invalid arguments, server not connected —
        are distinguished from tool failures, because the orchestrator responds to
        them differently: the former mean the plan was wrong, the latter mean the
        world was.
        """
        spec = None
        started = time.perf_counter()
        arguments = dict(arguments)

        # Propagate the request's trace id, but only into tools that actually declare
        # the parameter — injecting it blindly would fail schema validation on any
        # tool that does not accept it.
        if trace_id and "trace_id" in self._schema_properties(tool_name):
            arguments.setdefault("trace_id", trace_id)

        try:
            spec = self.registry.get(tool_name)
            self.validate(tool_name, arguments)
            client = self.registry.client_for(tool_name)
            result = await client.call_tool(tool_name, arguments)
        except (ToolNotFoundError, InvalidToolArgumentsError, ServerUnavailableError) as exc:
            return self._failure(
                spec.server if spec else "unknown", tool_name, arguments,
                exc.error_code, str(exc), started, trace_id,
            )
        except Exception as exc:  # noqa: BLE001 — transport-level failure
            code, message = self._parse_tool_error(str(exc))
            return self._failure(
                spec.server if spec else "unknown", tool_name, arguments,
                code, message, started, trace_id,
            )

        # A tool that raises does NOT propagate an exception through the client: the
        # SDK returns a CallToolResult with is_error set and the message in content.
        # Treating "no exception" as success would silently report failed steps as
        # successful — the demo would look fine while doing nothing.
        if getattr(result, "is_error", False):
            code, message = self._parse_tool_error(self._error_text(result))
            return self._failure(
                spec.server, tool_name, arguments, code, message, started, trace_id
            )

        output = self._structured(result)
        duration = (time.perf_counter() - started) * 1000
        tool_result = ToolResult(
            ok=True,
            server=spec.server,
            tool=tool_name,
            arguments=arguments,
            output=output,
            duration_ms=duration,
            trace_id=(output or {}).get("meta", {}).get("trace_id") or trace_id,
        )
        logger.info("tool_invoked", **tool_result.to_log_fields())
        return tool_result

    # -- helpers ------------------------------------------------------------ #

    def _schema_properties(self, tool_name: str) -> dict[str, Any]:
        try:
            return dict((self.registry.get(tool_name).input_schema or {}).get("properties", {}))
        except McpClientError:
            return {}

    @staticmethod
    def _parse_tool_error(message: str) -> tuple[str, str]:
        """Recover the MCP server's stable error code from a wrapped exception."""
        # The SDK prefixes "Error executing tool <name>: " before our own prefix.
        candidate = message.split("Error executing tool ", 1)[-1]
        candidate = candidate.split(": ", 1)[-1] if ": " in candidate else candidate
        match = _ERROR_PREFIX.match(candidate.strip())
        if match:
            return match.group(1), match.group(2)
        return "TOOL_ERROR", message

    @staticmethod
    def _error_text(result: Any) -> str:
        """Pull the failure message out of an errored CallToolResult."""
        parts = [
            text
            for block in (getattr(result, "content", None) or [])
            if (text := getattr(block, "text", None))
        ]
        return " ".join(parts) if parts else "tool reported an error with no message"

    @staticmethod
    def _structured(result: Any) -> dict[str, Any] | None:
        """Extract the structured payload from a CallToolResult.

        Tolerates several shapes so a change in the SDK's return convention does not
        break the orchestrator.
        """
        if isinstance(result, tuple) and len(result) == 2:
            return dict(result[1]) if result[1] is not None else None
        for attribute in ("structured_content", "structuredContent", "structured"):
            payload = getattr(result, attribute, None)
            if payload is not None:
                return dict(payload)
        if isinstance(result, dict):
            return result
        return None

    def _failure(
        self,
        server: str,
        tool: str,
        arguments: dict[str, Any],
        code: str,
        message: str,
        started: float,
        trace_id: str | None,
    ) -> ToolResult:
        result = ToolResult(
            ok=False,
            server=server,
            tool=tool,
            arguments=arguments,
            error_code=code,
            error_message=message,
            duration_ms=(time.perf_counter() - started) * 1000,
            trace_id=trace_id,
        )
        logger.warning("tool_failed", **result.to_log_fields())
        return result
