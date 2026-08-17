"""Answer composition — where the two evidence paths converge.

Structured tool output and unstructured document passages are rendered into one
evidence block, each item already carrying the marker the answer should cite. The
model is then asked to write an answer in which every claim carries one of those
markers.

Retrieved text is wrapped as inert data with an explicit trust-boundary instruction
before it reaches the prompt (``rag.retrieval.guard``). Whatever a document says, it is
evidence, never a command.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from rag.retrieval import TRUST_BOUNDARY_INSTRUCTION, verify_citations, wrap_for_prompt

from ..llm.provider import EvidenceItem, LLMProvider
from ..telemetry import get_logger
from .executor import ExecutionOutcome
from .models import ExecutionTrace, StepStatus

logger = get_logger(__name__)

# Long tool payloads are summarised before they reach the prompt. A raw 200-row alarm
# list crowds out the document evidence and adds nothing the answer can use.
MAX_LIST_ITEMS = 8


def summarise_output(payload: Any, *, depth: int = 0) -> Any:
    """Trim a tool result to what an answer can actually use."""
    if isinstance(payload, dict):
        return {
            key: summarise_output(value, depth=depth + 1)
            for key, value in payload.items()
            if key != "meta"  # trace metadata belongs in the trace, not the prompt
        }
    if isinstance(payload, list):
        trimmed = [summarise_output(item, depth=depth + 1) for item in payload[:MAX_LIST_ITEMS]]
        if len(payload) > MAX_LIST_ITEMS:
            trimmed.append(f"… and {len(payload) - MAX_LIST_ITEMS} more")
        return trimmed
    if isinstance(payload, str) and len(payload) > 600:
        return payload[:600] + "…"
    return payload


def build_evidence(trace: ExecutionTrace, outcome: ExecutionOutcome) -> str:
    """Render everything gathered into one evidence block.

    Each item is labelled with the marker the answer should cite, so attribution is a
    matter of copying a label rather than the model inventing one.
    """
    sections: list[str] = [TRUST_BOUNDARY_INSTRUCTION, ""]

    tool_steps = [
        s for s in trace.steps
        if s.kind == "tool" and s.status == StepStatus.SUCCEEDED and s.output
    ]
    if tool_steps:
        sections.append("## Live system data\n")
        for step in tool_steps:
            marker = f"[tool: {step.server}/{step.tool}]"
            payload = json.dumps(summarise_output(step.output), indent=2, default=str)
            sections.append(f"### {marker}\n{step.reason}\n\n```json\n{payload}\n```\n")

    failures = [s for s in trace.steps if s.status in {StepStatus.FAILED, StepStatus.SKIPPED}]
    if failures:
        sections.append("## Steps that did not complete\n")
        for step in failures:
            sections.append(f"- {step.label}: {step.error_code} — {step.error_message}")
        sections.append(
            "\nState plainly what could not be determined because of these, rather "
            "than working around them silently.\n"
        )

    if trace.gaps:
        sections.append("## Capability gaps\n")
        sections.extend(f"- {gap}" for gap in trace.gaps)
        sections.append("")

    if outcome.retrieval_chunks:
        sections.append("## Retrieved documents\n")
        sections.append(
            wrap_for_prompt([(c.citation, c.text) for c in outcome.retrieval_chunks])
        )
    else:
        sections.append(
            "## Retrieved documents\n\nNo document passages were retrieved for this "
            "question.\n"
        )

    return "\n".join(sections)


def _headline_facts(tool: str, output: dict[str, Any]) -> list[str]:
    """Pull the two or three facts an answer would actually quote from a tool result.

    Each tool's headline differs, so this is explicit rather than generic. A generic
    flattener would produce "results[0].asset_id = AST-0005", which is data, not a
    fact anyone would write in a sentence.
    """
    try:
        if tool == "search_assets" and output.get("results"):
            a = output["results"][0]
            return [f"{a['asset_name']} is {a['asset_id']}, {a['unit']} at {a['site']}, "
                    f"criticality {a['criticality']}"]
        if tool == "get_alarm_summary":
            facts = [f"{output.get('total_alarms', 0)} alarms in scope"]
            for group in output.get("groups", [])[:3]:
                name = next(iter(group.get("group", {}).values()), "?")
                kpis = group.get("kpis", {})
                bits = [f"{int(kpis['alarm_count'])} occurrences"] if "alarm_count" in kpis else []
                if "avg_ack_delay" in kpis:
                    bits.append(f"mean acknowledgement {kpis['avg_ack_delay']:.0f}s")
                if "recurring_rate" in kpis:
                    bits.append(f"recurring rate {kpis['recurring_rate']:.0%}")
                facts.append(f"{name}: {', '.join(bits)}")
            return facts
        if tool == "get_alarm_correlation":
            pairs = output.get("pairs", [])
            if not pairs:
                return ["no co-occurring alarm pairs met the support threshold"]
            return [
                f"{p['alarm_a']} is followed by {p['alarm_b']} {p['support']} times "
                f"(lift {p['lift']:.2f}, mean lag {p['mean_lag_seconds']:.0f}s)"
                for p in pairs[:3]
            ]
        if tool == "get_rationalization_candidates":
            cands = output.get("candidates", [])
            return [f"{c['alarm_name']} on {c['asset_name']}: {c['reason']}" for c in cands[:3]] \
                or ["no rationalization candidates met the thresholds"]
        if tool == "get_priority_score":
            return [f"priority {output.get('priority_score')} ({output.get('band')} band)"] + [
                f"{f['factor']}: {f['explanation']}" for f in output.get("factors", [])[:2]
            ]
        if tool == "get_operator_recommendations":
            return [f"{a['order']}. {a['action']} — {a['rationale']}"
                    for a in output.get("actions", [])[:4]]
        if tool == "execute_calculation":
            return [f"{output.get('calculation_type')} = {output.get('value')} "
                    f"{output.get('unit')}", str(output.get("interpretation", ""))]
        if tool == "get_flood_analysis":
            windows = output.get("flood_windows", [])
            if not windows:
                return ["no flood windows detected in scope"]
            return [f"{len(windows)} flood window(s); the largest held "
                    f"{windows[0]['alarm_count']} alarms between "
                    f"{windows[0]['start'][:16]} and {windows[0]['end'][:16]}"]
        if tool == "get_alarms":
            return [f"{output.get('total_count', 0)} alarms matched; "
                    f"{len(output.get('data', []))} returned on this page"]
        if tool == "get_alarm_trends":
            return [f"{len(output.get('points', []))} {output.get('bucket', 'daily')} buckets"]
        if tool == "search_issues":
            return [f"{output.get('count', 0)} existing issue(s) matched"]
    except (KeyError, IndexError, TypeError, ValueError):
        pass
    return []


def build_items(trace: ExecutionTrace, outcome: ExecutionOutcome) -> list[EvidenceItem]:
    """The same evidence, structured — what a deterministic composer needs."""
    items: list[EvidenceItem] = []
    for step in trace.steps:
        if step.kind == "tool" and step.status == StepStatus.SUCCEEDED and step.output:
            items.append(
                EvidenceItem(
                    marker=f"[tool: {step.server}/{step.tool}]",
                    kind="tool",
                    heading=step.reason or (step.tool or ""),
                    body="",
                    facts=_headline_facts(step.tool or "", step.output),
                )
            )
        elif step.status in {StepStatus.FAILED, StepStatus.SKIPPED}:
            items.append(
                EvidenceItem(
                    marker=f"[step: {step.id}]", kind="failure", heading=step.label,
                    body=f"{step.error_code} — {step.error_message}",
                )
            )
    for chunk in outcome.retrieval_chunks:
        items.append(
            EvidenceItem(
                marker=f"[source: {chunk.citation}]", kind="document",
                heading=f"{chunk.title} — {chunk.section}", body=chunk.excerpt(600),
            )
        )
    items.extend(
        EvidenceItem(marker="[gap]", kind="gap", heading="Capability gap", body=gap)
        for gap in trace.gaps
    )
    return items


class AnswerComposer:
    """Streams a grounded answer and checks its citations."""

    def __init__(self, provider: LLMProvider) -> None:
        self._provider = provider

    async def compose(
        self, trace: ExecutionTrace, outcome: ExecutionOutcome
    ) -> AsyncIterator[str]:
        evidence = build_evidence(trace, outcome)
        items = build_items(trace, outcome)
        collected: list[str] = []

        async for delta in self._provider.compose(
            trace.question, evidence, low_confidence=outcome.low_confidence, items=items
        ):
            collected.append(delta)
            yield delta

        answer = "".join(collected)
        trace.answer = answer

        # A citation naming a document that was never retrieved looks like evidence
        # while being invented, so it is checked rather than trusted.
        valid, hallucinated = verify_citations(answer, outcome.retrieval_chunks)
        if hallucinated:
            logger.warning(
                "hallucinated_citations", citations=hallucinated, request_id=trace.request_id
            )
            yield (
                "\n\n> **Citation warning:** this answer referenced "
                f"{', '.join(hallucinated)}, which was not among the retrieved "
                "documents. Treat those statements as unverified."
            )
        logger.info(
            "answer_composed",
            valid_citations=len(valid),
            hallucinated_citations=len(hallucinated),
            low_confidence=outcome.low_confidence,
            answer_chars=len(answer),
        )
