"""Anthropic implementation of :class:`LLMProvider`.

Three details that are easy to get wrong against the current API:

* ``temperature``, ``top_p`` and ``thinking.budget_tokens`` were removed and now
  return 400. None appear here.
* The plan is obtained with a **schema-constrained** call, so a structurally invalid
  plan cannot come back — validation happens before the object reaches our code.
* ``stop_reason`` is checked before reading ``content``. Safety classifiers can return
  HTTP 200 with an empty body, and indexing ``content[0]`` would raise instead of
  degrading.

The tool catalogue sits in a cached system block. It is stable between requests and
is the largest part of the prompt, so caching it is the difference between paying for
it once and paying for it on every question.
"""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator
from typing import Any

from anthropic import AsyncAnthropic

from ..orchestrator.models import Plan
from ..telemetry import get_logger
from .provider import CITATION_RULES, STYLE_RULES, LLMError

logger = get_logger(__name__)

DEFAULT_MODEL = "claude-opus-5"

PLANNER_SYSTEM = """\
You plan tool calls for a plant-operations copilot.

Given an operator's question and a catalogue of available tools, produce a plan: an
ordered list of steps that will gather the evidence needed to answer it.

How to plan well:

- Most questions that name equipment need search_assets first, because almost every
  other tool needs an asset_id and only that tool produces one from a human name.
- To use a value produced by an earlier step, reference it as a placeholder:
  "$s1.output.results[0].asset_id". It is substituted at execution time.
- Include a retrieval step (kind: "retrieval") whenever the answer should be grounded
  in an operating procedure, a standard, or a troubleshooting guide — that is, almost
  any question asking what to do about something.
- For a retrieval step, args should be {"query": "...", "asset": "$s1.output.results[0].asset_name"}
  when an asset has been resolved, so retrieval is narrowed to documents for that
  equipment.
- Only use tools that appear in the catalogue. If the question needs something no tool
  provides, record it in "gaps" rather than inventing a step.
- Keep plans as short as the question allows. Every step costs time."""


class AnthropicProvider:
    """Planning and answer composition via the Anthropic API."""

    def __init__(
        self,
        api_key: str | None = None,
        *,
        model: str = DEFAULT_MODEL,
        effort: str = "high",
        max_plan_tokens: int = 8000,
        max_answer_tokens: int = 16000,
    ) -> None:
        self._client = AsyncAnthropic(api_key=api_key) if api_key else AsyncAnthropic()
        self._model = model
        self._effort = effort
        self._max_plan_tokens = max_plan_tokens
        self._max_answer_tokens = max_answer_tokens
        self.last_latency_ms: float = 0.0

    @property
    def name(self) -> str:
        return f"anthropic:{self._model}"

    # -- planning ----------------------------------------------------------- #

    async def plan(
        self, question: str, catalogue: list[dict[str, Any]], *, history: str = ""
    ) -> Plan:
        started = time.perf_counter()

        # Stable content first, volatile last. The catalogue is byte-identical between
        # requests (the registry sorts it), so it caches; the question does not and
        # therefore sits after the breakpoint.
        system = [
            {
                "type": "text",
                "text": (
                    f"{PLANNER_SYSTEM}\n\n## Available tools\n\n"
                    f"{json.dumps(catalogue, indent=2, sort_keys=True)}"
                ),
                "cache_control": {"type": "ephemeral"},
            }
        ]
        user = f"{history}\n\nQuestion: {question}" if history else f"Question: {question}"

        try:
            response = await self._client.messages.parse(
                model=self._model,
                max_tokens=self._max_plan_tokens,
                output_format=Plan,
                output_config={"effort": self._effort},
                system=system,
                messages=[{"role": "user", "content": user}],
            )
        except Exception as exc:  # noqa: BLE001 — surfaced as a typed provider error
            raise LLMError(f"planning failed: {type(exc).__name__}: {exc}") from exc

        self.last_latency_ms = (time.perf_counter() - started) * 1000

        if getattr(response, "stop_reason", None) == "refusal":
            raise LLMError(
                "the model declined to plan this request", kind="REFUSAL"
            )

        usage = getattr(response, "usage", None)
        logger.info(
            "plan_generated",
            llm_latency_ms=round(self.last_latency_ms, 2),
            cache_read_input_tokens=getattr(usage, "cache_read_input_tokens", None),
            cache_creation_input_tokens=getattr(usage, "cache_creation_input_tokens", None),
        )

        plan = getattr(response, "parsed_output", None)
        if plan is None:
            raise LLMError("the model returned no parsable plan")
        return plan

    # -- composition -------------------------------------------------------- #

    async def compose(
        self,
        question: str,
        evidence: str,
        *,
        low_confidence: bool,
        items: list[Any] | None = None,
    ) -> AsyncIterator[str]:
        # `items` is the structured form, which a generative provider does not need:
        # it writes prose from `evidence`. Accepted so both providers share one
        # signature.
        confidence_note = (
            "\n\nIMPORTANT: document retrieval returned nothing sufficiently relevant. "
            "Say so explicitly and do not substitute general knowledge."
            if low_confidence
            else ""
        )
        system = (
            "You answer plant-operations questions for a control-room operator, using "
            "only the evidence supplied.\n\n"
            f"{CITATION_RULES}\n\n{STYLE_RULES}{confidence_note}"
        )
        started = time.perf_counter()
        try:
            async with self._client.messages.stream(
                model=self._model,
                max_tokens=self._max_answer_tokens,
                output_config={"effort": self._effort},
                system=system,
                messages=[
                    {
                        "role": "user",
                        "content": f"Question: {question}\n\n## Evidence\n\n{evidence}",
                    }
                ],
            ) as stream:
                async for text in stream.text_stream:
                    yield text
                final = await stream.get_final_message()
        except Exception as exc:  # noqa: BLE001
            raise LLMError(f"composition failed: {type(exc).__name__}: {exc}") from exc

        self.last_latency_ms += (time.perf_counter() - started) * 1000
        if getattr(final, "stop_reason", None) == "refusal":
            yield (
                "\n\n_The model declined to complete this answer. "
                "The evidence gathered above is still shown._"
            )
