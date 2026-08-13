"""Copilot backend — HTTP surface.

Six endpoints. ``/chat`` streams Server-Sent Events so the execution timeline fills in
as work happens rather than appearing all at once when the request finishes; watching
a step run is most of what makes the trace convincing.

The MCP registry is opened in the lifespan, which is a single coroutine — the MCP
client holds an anyio task group that must be entered and exited from the same task,
and the lifespan is the natural place that holds.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from rag.ingestion import DocumentIndex, build_embedder
from rag.retrieval import RetrievalService

from ..config import Settings, get_settings
from ..llm import AnthropicProvider, RuleBasedProvider
from ..llm.provider import LLMProvider
from ..mcp_client import McpServerConfig, ToolInvoker, ToolRegistry
from ..orchestrator import ConversationMemory, Copilot
from ..telemetry import configure_logging, get_logger

logger = get_logger(__name__)
VERSION = "1.0.0"


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    conversation_id: str | None = None
    confirmed_actions: list[str] = Field(
        default_factory=list,
        description="Tool names the user has approved for this request, e.g. "
        "['create_issue']. Write tools refuse without this.",
    )


class ConfirmRequest(BaseModel):
    request_id: str
    tool: str
    approved: bool


def build_provider(settings: Settings) -> LLMProvider:
    if settings.use_anthropic:
        return AnthropicProvider(
            api_key=settings.anthropic_api_key,
            model=settings.llm_model,
            effort=settings.llm_effort,
        )
    if settings.llm_provider.lower() == "anthropic":
        logger.warning(
            "anthropic_requested_without_key",
            detail="falling back to the deterministic provider",
        )
    return RuleBasedProvider()


def build_retrieval(settings: Settings) -> RetrievalService | None:
    """Open the document index, degrading rather than failing if it is missing."""
    try:
        index = DocumentIndex(
            build_embedder(settings.embedding_model),
            persist_path=settings.chroma_path,
            collection_name=settings.chroma_collection,
        )
        if index.count == 0:
            logger.warning(
                "empty_document_index",
                detail="run: python -m rag.ingestion.cli --docs ./rag/documents --reset",
            )
        return RetrievalService(
            index, top_k=settings.retrieval_top_k, min_score=settings.retrieval_min_score
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("retrieval_unavailable", error=str(exc))
        return None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level, json_output=settings.log_format == "json")

    registry = ToolRegistry(
        servers=[
            McpServerConfig("alarm-management", settings.mcp_alarm_url),
            McpServerConfig("github-issues", settings.mcp_github_url),
        ]
    )
    # Held open for the process lifetime, inside this single coroutine.
    async with registry:
        app.state.registry = registry
        app.state.copilot = Copilot(
            registry=registry,
            invoker=ToolInvoker(registry=registry),
            provider=build_provider(settings),
            retrieval=build_retrieval(settings),
            memory=ConversationMemory(),
        )
        logger.info(
            "backend_ready",
            tools=registry.tool_count,
            provider=app.state.copilot._provider.name,  # noqa: SLF001 — startup log
        )
        yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Multi-MCP Enterprise Operations Copilot",
        description="Answers operations questions from live alarm data and operating "
        "procedures, with a visible tool trace and source citations.",
        version=VERSION,
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health", tags=["system"])
    async def health() -> dict[str, Any]:
        registry: ToolRegistry | None = getattr(app.state, "registry", None)
        servers = registry.server_status() if registry else []
        return {
            "status": "ok" if any(s.connected for s in servers) else "degraded",
            "version": VERSION,
            "tools": registry.tool_count if registry else 0,
            "servers": [
                {"name": s.name, "connected": s.connected, "tools": s.tool_count,
                 "error": s.error}
                for s in servers
            ],
        }

    @app.get("/mcp/servers", tags=["mcp"])
    async def mcp_servers() -> dict[str, Any]:
        """Which MCP servers are connected — the GUI's discovery view header."""
        registry: ToolRegistry = app.state.registry
        return {
            "servers": [
                {"name": s.name, "connected": s.connected, "tool_count": s.tool_count,
                 "error": s.error}
                for s in registry.server_status()
            ]
        }

    @app.get("/mcp/tools", tags=["mcp"])
    async def mcp_tools() -> dict[str, Any]:
        """Every discovered tool with its schemas — powers schema inspection."""
        registry: ToolRegistry = app.state.registry
        return {
            "tools": [
                {
                    "server": spec.server,
                    "name": spec.name,
                    "qualified_name": spec.qualified_name,
                    "description": spec.description,
                    "input_schema": spec.input_schema,
                    "output_schema": spec.output_schema,
                }
                for spec in sorted(registry.specs(), key=lambda s: s.qualified_name)
            ]
        }

    @app.get("/traces/{request_id}", tags=["trace"])
    async def get_trace(request_id: str) -> dict[str, Any]:
        copilot: Copilot = app.state.copilot
        trace = copilot.trace(request_id)
        if trace is None:
            raise HTTPException(status_code=404, detail=f"no trace for {request_id}")
        return trace.to_dict()

    @app.post("/actions/confirm", tags=["actions"])
    async def confirm(request: ConfirmRequest) -> dict[str, Any]:
        """Record a user's approval of a write.

        The approval is returned to the caller, which re-issues the question with the
        tool in ``confirmed_actions``. Keeping the grant per-request rather than
        sticky means one approval cannot silently authorise later writes.
        """
        return {
            "request_id": request.request_id,
            "tool": request.tool,
            "approved": request.approved,
            "next": (
                f"re-send the question with confirmed_actions=['{request.tool}']"
                if request.approved
                else "the action was declined and will not run"
            ),
        }

    @app.post("/chat", tags=["chat"])
    async def chat(request: ChatRequest) -> EventSourceResponse:
        """Answer a question, streaming the plan, each step, and the answer."""
        copilot: Copilot = app.state.copilot

        async def stream() -> AsyncIterator[dict[str, str]]:
            try:
                async for event, payload in copilot.ask(
                    request.question,
                    conversation_id=request.conversation_id,
                    confirmed_actions=set(request.confirmed_actions),
                ):
                    yield {"event": event, "data": json.dumps(payload, default=str)}
            except Exception as exc:  # noqa: BLE001 — the stream must always close cleanly
                logger.exception("chat_stream_failed", error=str(exc))
                yield {
                    "event": "error",
                    "data": json.dumps(
                        {"error_code": "INTERNAL_ERROR", "message": str(exc)}
                    ),
                }

        return EventSourceResponse(stream())

    return app


app = create_app()
