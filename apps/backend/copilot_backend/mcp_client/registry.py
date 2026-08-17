"""MCP tool registry — runtime discovery across multiple servers.

At startup the registry connects to every configured MCP server, calls
``list_tools()``, and caches what it finds. **Nothing about alarms or issues is
compiled into the copilot**: adding a tool to a server makes it available to the
planner on the next restart, with no change here.

One cache serves three consumers, which is why it exists as its own component:

* the **planner** reasons over tool names, descriptions, and input schemas
* the **GUI** renders the same records as its tool-discovery view
* the **invoker** validates arguments against the cached input schema

A server that cannot be reached is recorded as degraded rather than fatal. The
planner is then told those tools are unavailable and plans around the gap, instead of
producing a plan that cannot run.
"""

from __future__ import annotations

from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from typing import Any

from mcp import Client

from ..telemetry import get_logger
from .errors import ServerUnavailableError, ToolNotFoundError

logger = get_logger(__name__)


@dataclass(frozen=True)
class McpServerConfig:
    """How to reach one MCP server.

    ``target`` is either a URL for streamable HTTP, or an in-process ``MCPServer``
    object. The SDK's ``Client`` accepts both, so tests exercise the real client
    against a real server without a socket.
    """

    name: str
    target: Any


@dataclass(frozen=True)
class ToolSpec:
    """One discovered tool, as advertised by its server."""

    server: str
    name: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any] | None = None

    @property
    def qualified_name(self) -> str:
        """``server/tool`` — what the GUI shows and the answer cites."""
        return f"{self.server}/{self.name}"

    def for_planner(self) -> dict[str, Any]:
        """The projection the planner sees. Output schema is omitted deliberately:
        the planner chooses tools and arguments, and showing it response shapes it
        cannot influence only spends context."""
        return {
            "server": self.server,
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }


@dataclass
class ServerStatus:
    name: str
    connected: bool
    tool_count: int = 0
    error: str | None = None


@dataclass
class ToolRegistry:
    """Discovered tools across every configured MCP server."""

    servers: list[McpServerConfig]
    _specs: dict[str, ToolSpec] = field(default_factory=dict)
    _clients: dict[str, Client] = field(default_factory=dict)
    _status: dict[str, ServerStatus] = field(default_factory=dict)
    _stack: AsyncExitStack | None = None

    async def __aenter__(self) -> ToolRegistry:
        """Enter as a context manager: connect on entry, close on exit.

        The MCP ``Client`` holds an anyio task group, which must be entered and
        exited from the **same task**. Using the registry as a context manager makes
        that structurally guaranteed rather than a convention callers must remember.

        In the backend this wraps the FastAPI lifespan, which is a single coroutine,
        so the guarantee holds naturally in production.
        """
        await self.connect()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def connect(self) -> None:
        """Open a session per server and discover its tools.

        Sessions are held open for the process lifetime rather than re-established
        per call, so a tool invocation costs one round trip instead of a full
        connect-initialise-call-teardown cycle.

        Prefer ``async with`` over calling this directly — see :meth:`__aenter__`.
        """
        self._stack = AsyncExitStack()
        for config in self.servers:
            try:
                client = await self._stack.enter_async_context(Client(config.target))
                result = await client.list_tools()
            except Exception as exc:  # noqa: BLE001 — any failure means unavailable
                # Degraded, not fatal. The copilot still runs with the tools it does
                # have, and says what it could not do.
                self._status[config.name] = ServerStatus(
                    name=config.name, connected=False, error=f"{type(exc).__name__}: {exc}"
                )
                logger.warning(
                    "mcp_server_unavailable", mcp_server=config.name, error=str(exc)
                )
                continue

            self._clients[config.name] = client
            discovered = 0
            for tool in result.tools:
                spec = ToolSpec(
                    server=config.name,
                    name=tool.name,
                    description=tool.description or "",
                    input_schema=dict(tool.input_schema or {}),
                    output_schema=dict(tool.output_schema) if tool.output_schema else None,
                )
                if spec.name in self._specs:
                    # Two servers offering the same tool name would make the planner's
                    # choice ambiguous. First registration wins and the clash is logged
                    # rather than silently shadowed.
                    logger.warning(
                        "duplicate_tool_name",
                        tool=spec.name,
                        kept=self._specs[spec.name].server,
                        ignored=config.name,
                    )
                    continue
                self._specs[spec.name] = spec
                discovered += 1

            self._status[config.name] = ServerStatus(
                name=config.name, connected=True, tool_count=discovered
            )
            logger.info(
                "mcp_server_connected", mcp_server=config.name, tool_count=discovered
            )

    async def aclose(self) -> None:
        if self._stack is not None:
            await self._stack.aclose()
            self._stack = None
        self._clients.clear()

    # -- lookup ------------------------------------------------------------- #

    def get(self, tool_name: str) -> ToolSpec:
        """Look up a tool, or explain that it is not available.

        The error message lists what *is* available, because the most common cause is
        a plan naming a tool that does not exist and the fix is knowing what does.
        """
        spec = self._specs.get(tool_name)
        if spec is None:
            available = ", ".join(sorted(self._specs)) or "none"
            raise ToolNotFoundError(
                f"No tool named {tool_name!r} is registered. Available tools: {available}"
            )
        return spec

    def client_for(self, tool_name: str) -> Client:
        spec = self.get(tool_name)
        client = self._clients.get(spec.server)
        if client is None:
            raise ServerUnavailableError(
                f"Tool {tool_name!r} lives on server {spec.server!r}, which is not connected"
            )
        return client

    def specs(self) -> list[ToolSpec]:
        return list(self._specs.values())

    def catalogue_for_planner(self) -> list[dict[str, Any]]:
        """Every available tool, in the shape the planner prompt embeds.

        Sorted by qualified name so the serialisation is byte-stable between
        requests — an unstable ordering would invalidate the prompt cache on every
        call and silently triple the planning cost.
        """
        return [
            spec.for_planner()
            for spec in sorted(self._specs.values(), key=lambda s: s.qualified_name)
        ]

    def server_status(self) -> list[ServerStatus]:
        return [
            self._status.get(config.name, ServerStatus(name=config.name, connected=False))
            for config in self.servers
        ]

    @property
    def tool_count(self) -> int:
        return len(self._specs)
