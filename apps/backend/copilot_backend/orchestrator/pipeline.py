"""The copilot pipeline: plan → execute → compose.

One question in, one stream of events out. This is the object the API endpoint drives
and the end-to-end test exercises.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from typing import Any

from rag.retrieval import RetrievalService

from ..llm.provider import LLMError, LLMProvider
from ..mcp_client import ToolInvoker, ToolRegistry
from ..telemetry import get_logger, new_request_context
from .composer import AnswerComposer
from .executor import PlanExecutor
from .memory import ConversationMemory, Turn
from .models import ExecutionTrace, Plan
from .models import StepStatus as _StepStatus

logger = get_logger(__name__)


class Copilot:
    """Plans, executes, and composes an answer for one question."""

    def __init__(
        self,
        registry: ToolRegistry,
        invoker: ToolInvoker,
        provider: LLMProvider,
        retrieval: RetrievalService | None,
        memory: ConversationMemory | None = None,
    ) -> None:
        self._registry = registry
        self._invoker = invoker
        self._provider = provider
        self._retrieval = retrieval
        self._memory = memory or ConversationMemory()
        self._traces: dict[str, ExecutionTrace] = {}

    @property
    def registry(self) -> ToolRegistry:
        """The tool registry this copilot plans against, also served by ``/mcp/tools``."""
        return self._registry

    @property
    def provider_name(self) -> str:
        return self._provider.name

    def trace(self, request_id: str) -> ExecutionTrace | None:
        return self._traces.get(request_id)

    async def ask(
        self,
        question: str,
        *,
        conversation_id: str | None = None,
        confirmed_actions: set[str] | None = None,
    ) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        """Answer a question, yielding ``(event, payload)`` throughout.

        Events: ``trace.started``, ``plan.ready``, ``step.started``,
        ``step.succeeded``, ``step.failed``, ``confirmation.required``,
        ``answer.delta``, ``answer.completed``, ``error``.
        """
        request_id, conversation, trace_id = new_request_context(conversation_id)
        trace = ExecutionTrace(
            request_id=request_id,
            conversation_id=conversation,
            trace_id=trace_id,
            question=question,
            planner_provider=self._provider.name,
        )
        self._traces[request_id] = trace
        started = time.perf_counter()

        yield "trace.started", {
            "request_id": request_id,
            "conversation_id": conversation,
            "trace_id": trace_id,
            "question": question,
            "provider": self._provider.name,
        }

        # -- plan ------------------------------------------------------------ #
        try:
            plan: Plan = await self._provider.plan(
                question,
                self._registry.catalogue_for_planner(),
                history=self._memory.as_prompt(conversation),
            )
        except LLMError as exc:
            trace.answer = f"Planning failed: {exc}"
            yield "error", {"error_code": exc.kind, "message": str(exc)}
            yield "answer.completed", trace.to_dict()
            return

        # A plan naming a tool that does not exist is rejected before anything runs.
        known = {spec.name for spec in self._registry.specs()}
        unknown = [
            s.tool for s in plan.steps if s.kind == "tool" and s.tool and s.tool not in known
        ]
        if unknown:
            plan.steps = [
                s for s in plan.steps if not (s.kind == "tool" and s.tool in unknown)
            ]
            plan.gaps.append(
                f"the plan referenced unavailable tool(s): {', '.join(sorted(set(unknown)))}"
            )

        trace.intent = plan.intent
        trace.llm_latency_ms = getattr(self._provider, "last_latency_ms", 0.0)
        yield "plan.ready", {
            "intent": plan.intent,
            "gaps": plan.gaps,
            "steps": [
                {"id": s.id, "kind": s.kind, "tool": s.tool, "reason": s.reason, "args": s.args}
                for s in plan.steps
            ],
        }

        # -- execute --------------------------------------------------------- #
        executor = PlanExecutor(
            self._invoker, self._retrieval, confirmed_actions=confirmed_actions
        )
        async for event, payload in executor.run(plan, trace):
            yield event, payload
        outcome = executor.outcome

        # -- compose --------------------------------------------------------- #
        composer = AnswerComposer(self._provider)
        try:
            async for delta in composer.compose(trace, outcome):
                yield "answer.delta", {"text": delta}
        except LLMError as exc:
            trace.answer = (
                f"The evidence above was gathered successfully, but the answer could "
                f"not be composed: {exc}"
            )
            yield "error", {"error_code": exc.kind, "message": str(exc)}

        trace.llm_latency_ms = getattr(self._provider, "last_latency_ms", trace.llm_latency_ms)
        self._memory.add(conversation, Turn(question, trace.answer, trace.intent))

        logger.info(
            "request_completed",
            request_id=request_id,
            conversation_id=conversation,
            trace_id=trace_id,
            steps=len(trace.steps),
            failed=len(trace.failed_steps),
            low_confidence=trace.low_confidence,
            llm_latency_ms=round(trace.llm_latency_ms, 2),
            total_ms=round((time.perf_counter() - started) * 1000, 2),
        )
        yield "answer.completed", trace.to_dict()


__all__ = ["Copilot", "_StepStatus"]
