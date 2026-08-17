"""Plan execution.

Runs steps in order: resolve placeholders, validate against the tool's schema, invoke,
record, emit. Retrieval is executed as an ordinary step, which is precisely what makes
MCP and RAG one workflow rather than two features — the document search is narrowed by
an ``asset_name`` an earlier tool call produced.

Failure is partial, not total. A failed step is recorded with its error code; steps
that do not depend on it still run; steps that do are **skipped rather than attempted**,
because running one with an unresolvable placeholder produces a plausible-looking wrong
answer instead of an honest gap.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from rag.retrieval import RetrievalService, build_citations

from ..mcp_client import ToolInvoker
from ..telemetry import get_logger
from .models import ExecutionTrace, Plan, PlanStep, StepRecord, StepStatus
from .resolver import PlaceholderError, referenced_steps, resolve_args

logger = get_logger(__name__)

# Tools that write to an external system, mapped to the argument their MCP contract
# uses to carry the user's approval. Keyed by tool name rather than inferred from the
# schema so that adding a write tool is a deliberate act, not an accident of naming.
WRITE_TOOLS: dict[str, str] = {"create_issue": "confirmed"}


@dataclass
class ExecutionOutcome:
    """What execution produced, for the composer."""

    trace: ExecutionTrace
    outputs: dict[str, dict[str, Any]] = field(default_factory=dict)
    retrieval_chunks: list[Any] = field(default_factory=list)
    low_confidence: bool = True
    retrieval_query: str = ""


class PlanExecutor:
    """Executes a plan, streaming a step event as each step starts and finishes."""

    def __init__(
        self,
        invoker: ToolInvoker,
        retrieval: RetrievalService | None = None,
        *,
        confirmed_actions: set[str] | None = None,
    ) -> None:
        self._invoker = invoker
        self._retrieval = retrieval
        # Tools the user has explicitly approved this request. Empty by default: a
        # write tool with no entry here is refused by the MCP server, which is where
        # the guarantee belongs.
        self._confirmed = confirmed_actions or set()

    async def run(
        self, plan: Plan, trace: ExecutionTrace
    ) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        """Execute the plan, yielding ``(event_name, payload)`` as it goes."""
        outcome = ExecutionOutcome(trace=trace)
        failed_steps: set[str] = set()

        for step in plan.steps:
            record = StepRecord(
                id=step.id,
                kind=step.kind,
                label=self._label(step),
                tool=step.tool,
                reason=step.reason,
                trace_id=trace.trace_id,
            )
            trace.steps.append(record)

            # Skip rather than attempt when a dependency failed.
            blocked = referenced_steps(step.args) & failed_steps
            if blocked:
                record.status = StepStatus.SKIPPED
                record.error_code = "DEPENDENCY_FAILED"
                record.error_message = (
                    f"skipped because {', '.join(sorted(blocked))} did not produce output"
                )
                yield "step.failed", record.to_event()
                failed_steps.add(step.id)
                continue

            record.status = StepStatus.RUNNING
            yield "step.started", record.to_event()

            started = time.perf_counter()
            try:
                arguments = resolve_args(step.args, outcome.outputs)
            except PlaceholderError as exc:
                record.status = StepStatus.FAILED
                record.error_code = "UNRESOLVED_REFERENCE"
                record.error_message = str(exc)
                record.duration_ms = (time.perf_counter() - started) * 1000
                failed_steps.add(step.id)
                yield "step.failed", record.to_event()
                continue

            record.arguments = arguments

            if step.kind == "retrieval":
                await self._run_retrieval(record, arguments, outcome, trace)
                yield (
                    "step.succeeded" if record.status == StepStatus.SUCCEEDED else "step.failed",
                    record.to_event(),
                )
                if record.status != StepStatus.SUCCEEDED:
                    failed_steps.add(step.id)
                continue

            if step.tool is None:
                record.status = StepStatus.FAILED
                record.error_code = "INVALID_PLAN"
                record.error_message = "a tool step must name a tool"
                failed_steps.add(step.id)
                yield "step.failed", record.to_event()
                continue

            # A write tool needs explicit approval. The MCP server enforces this too;
            # checking here means the user gets a confirmation prompt instead of an
            # error they cannot act on.
            if step.tool in WRITE_TOOLS:
                if step.tool not in self._confirmed:
                    record.status = StepStatus.FAILED
                    record.error_code = "CONFIRMATION_REQUIRED"
                    record.error_message = (
                        "This step writes to an external system and needs your approval."
                    )
                    failed_steps.add(step.id)
                    yield "confirmation.required", record.to_event()
                    continue
                # Carry the approval into the tool call. The server refuses without it,
                # so an approval the orchestrator swallowed would be indistinguishable
                # from no approval at all.
                arguments = {**arguments, WRITE_TOOLS[step.tool]: True}
                record.arguments = arguments

            result = await self._invoker.invoke(step.tool, arguments, trace_id=trace.trace_id)
            record.server = result.server
            record.duration_ms = result.duration_ms
            record.trace_id = result.trace_id or trace.trace_id

            if result.ok:
                record.status = StepStatus.SUCCEEDED
                record.output = result.output
                outcome.outputs[step.id] = result.output or {}
                yield "step.succeeded", record.to_event()
            else:
                record.status = StepStatus.FAILED
                record.error_code = result.error_code
                record.error_message = result.error_message
                failed_steps.add(step.id)
                yield "step.failed", record.to_event()

        trace.gaps = list(plan.gaps)
        self._outcome = outcome

    @property
    def outcome(self) -> ExecutionOutcome:
        return self._outcome

    # -- retrieval ---------------------------------------------------------- #

    async def _run_retrieval(
        self,
        record: StepRecord,
        arguments: dict[str, Any],
        outcome: ExecutionOutcome,
        trace: ExecutionTrace,
    ) -> None:
        started = time.perf_counter()
        if self._retrieval is None:
            record.status = StepStatus.FAILED
            record.error_code = "RETRIEVAL_UNAVAILABLE"
            record.error_message = "no document index is configured"
            return

        query = str(arguments.get("query") or trace.question)
        asset = arguments.get("asset")
        result = self._retrieval.search(
            query, asset=str(asset) if asset else None, top_k=int(arguments.get("top_k", 5))
        )
        citations = build_citations(result)

        record.server = "rag"
        record.status = StepStatus.SUCCEEDED
        record.duration_ms = (time.perf_counter() - started) * 1000
        record.output = {
            "query": query,
            "asset_filter": asset,
            "low_confidence": result.low_confidence,
            "best_score": result.best_score,
            "doc_ids": result.doc_ids,
            "citations": [c.__dict__ for c in citations],
        }

        outcome.retrieval_chunks = list(result.chunks)
        outcome.low_confidence = result.low_confidence
        outcome.retrieval_query = query
        trace.citations = [c.__dict__ for c in citations]
        trace.low_confidence = result.low_confidence

        logger.info(
            "retrieval_completed",
            retrieval_query=query,
            retrieved_doc_ids=result.doc_ids,
            retrieval_score=result.best_score,
            low_confidence=result.low_confidence,
            duration_ms=round(record.duration_ms, 2),
        )

    @staticmethod
    def _label(step: PlanStep) -> str:
        if step.kind == "retrieval":
            return "Retrieve supporting documents"
        return step.tool or "unknown"
