"""Orchestration contracts.

The ``Plan`` is a first-class inspectable object rather than an emergent property of
a loop (ADR-02). That is what lets the GUI render an execution graph, the tests assert
on chaining without an LLM, and the schema validator reject a bad plan before any tool
runs.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field


class StepKind(StrEnum):
    TOOL = "tool"
    RETRIEVAL = "retrieval"


class PlanStep(BaseModel):
    """One step. ``args`` may contain ``$s1.output.path`` references to earlier steps."""

    id: str = Field(description="Short identifier such as s1, s2. Referenced by later steps.")
    kind: Literal["tool", "retrieval"] = Field(
        description="'tool' invokes an MCP tool; 'retrieval' searches the document corpus."
    )
    tool: str | None = Field(
        default=None, description="Tool name for kind='tool'. Must exist in the catalogue."
    )
    args: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Arguments. To use a value produced by an earlier step, write "
            '"$s1.output.results[0].asset_id" — it is substituted at execution time.'
        ),
    )
    reason: str = Field(default="", description="Why this step is needed. Shown in the trace.")


class Plan(BaseModel):
    """A validated, executable plan."""

    intent: str = Field(description="One line describing what the user is asking for.")
    steps: list[PlanStep] = Field(default_factory=list)
    gaps: list[str] = Field(
        default_factory=list,
        description="Anything the question needs that no available tool can provide.",
    )


class StepStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class StepRecord:
    """The executed form of a plan step — what the timeline renders."""

    id: str
    kind: str
    label: str
    status: StepStatus = StepStatus.PENDING
    server: str | None = None
    tool: str | None = None
    arguments: dict[str, Any] = field(default_factory=dict)
    output: dict[str, Any] | None = None
    error_code: str | None = None
    error_message: str | None = None
    duration_ms: float = 0.0
    trace_id: str | None = None
    reason: str = ""
    started_at: float = field(default_factory=time.time)

    def to_event(self) -> dict[str, Any]:
        """The SSE payload. Output is summarised, not dumped — the full object is
        available from the trace endpoint if the user expands the card."""
        return {
            "id": self.id,
            "kind": self.kind,
            "label": self.label,
            "status": self.status.value,
            "server": self.server,
            "tool": self.tool,
            "arguments": self.arguments,
            "output": self.output,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "duration_ms": round(self.duration_ms, 2),
            "trace_id": self.trace_id,
            "reason": self.reason,
        }


@dataclass
class ExecutionTrace:
    """Everything that happened during one request.

    The same object feeds the structured logs, the SSE stream, and the trace endpoint,
    so observability and GUI traceability cannot drift apart (ADR-06).
    """

    request_id: str
    conversation_id: str
    trace_id: str
    question: str
    intent: str = ""
    steps: list[StepRecord] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    citations: list[dict[str, Any]] = field(default_factory=list)
    answer: str = ""
    low_confidence: bool = False
    llm_latency_ms: float = 0.0
    planner_provider: str = ""
    created_at: float = field(default_factory=time.time)

    @property
    def succeeded_steps(self) -> list[StepRecord]:
        return [s for s in self.steps if s.status == StepStatus.SUCCEEDED]

    @property
    def failed_steps(self) -> list[StepRecord]:
        return [s for s in self.steps if s.status == StepStatus.FAILED]

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "conversation_id": self.conversation_id,
            "trace_id": self.trace_id,
            "question": self.question,
            "intent": self.intent,
            "steps": [s.to_event() for s in self.steps],
            "gaps": self.gaps,
            "citations": self.citations,
            "answer": self.answer,
            "low_confidence": self.low_confidence,
            "llm_latency_ms": round(self.llm_latency_ms, 2),
            "planner_provider": self.planner_provider,
            "total_duration_ms": round(sum(s.duration_ms for s in self.steps), 2),
        }
