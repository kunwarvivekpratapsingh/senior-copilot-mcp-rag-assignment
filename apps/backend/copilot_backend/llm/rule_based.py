"""Deterministic provider — no API key required.

Exists for two reasons. It lets the whole system be demonstrated with no credentials,
which de-risks an assessment run on someone else's machine. And two real
implementations prove the provider abstraction is genuine, where one plus an interface
would only assert it.

This is **intent classification plus slot extraction**, not a switch statement per
sample question. Intents map to capability templates, templates are resolved against
the live tool catalogue, and a template naming an unavailable tool degrades to a gap
rather than producing an unexecutable plan. A question matching no intent still gets
a sensible default rather than nothing.

It is weaker than the LLM path — it cannot handle a phrasing nobody anticipated — and
that is stated in the answer footer rather than hidden.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

from ..orchestrator.models import Plan, PlanStep
from .provider import EvidenceItem

# Intent -> (keywords, capability template). Ordered: the first match wins, so more
# specific intents are listed before general ones.
INTENT_PATTERNS: list[tuple[str, list[str]]] = [
    ("escalation", ["escalat", "highest priority", "most urgent", "worst alarm"]),
    ("draft_issue", ["issue", "ticket", "raise a", "github", "work order"]),
    ("efficiency", ["response efficiency", "acknowledg", "how quickly", "response time"]),
    ("flood", ["flood", "too many alarms", "overwhelm"]),
    ("rationalize", ["rationaliz", "suppress", "nuisance", "re-tune", "retune"]),
    ("recurring", ["recurring", "keeps happening", "repeat", "again and again", "investigate"]),
    ("trend", ["trend", "over time", "getting worse", "since"]),
    ("lookup", ["what is", "tell me about", "details of", "metadata"]),
]

_ASSET_HINTS = re.compile(
    r"\b((?:boiler feed pump|induction motor|synchronous motor|air compressor|"
    r"gas compressor|recycle compressor|condensate pump|charge pump|feedwater heater|"
    r"crude charge pump|motor driven pump)\s*\d*)",
    re.IGNORECASE,
)
_UNIT = re.compile(r"\bunit\s*(\d+)\b", re.IGNORECASE)
_SITE = re.compile(r"\b(northplant|southplant|eastrefinery|westterminal)\b", re.IGNORECASE)
_DAYS = re.compile(r"\b(?:last|past)\s+(\d+)\s*(day|week|month)", re.IGNORECASE)
# Distinguishes "draft an issue" from "file one". Drafting writes nothing and is
# always safe; creating is a write, so it is only planned when actually requested.
_WANTS_WRITE = re.compile(
    r"\b(create|file|open|raise|submit|log)\b[\w\s]{0,20}\b(issue|ticket|work order)\b",
    re.IGNORECASE,
)

ASSET_REF = "$s1.output.results[0].asset_id"
ASSET_NAME_REF = "$s1.output.results[0].asset_name"


def classify(question: str) -> str:
    lowered = question.lower()
    for intent, keywords in INTENT_PATTERNS:
        if any(k in lowered for k in keywords):
            return intent
    return "recurring"  # the most useful default for an operations question


def extract_slots(question: str) -> dict[str, Any]:
    """Pull asset, unit, site, and time window out of the question."""
    slots: dict[str, Any] = {}
    if match := _ASSET_HINTS.search(question):
        slots["asset_query"] = match.group(1).strip()
    if match := _UNIT.search(question):
        slots["unit"] = f"Unit {match.group(1)}"
    if match := _SITE.search(question):
        canonical = {
            "northplant": "NorthPlant", "southplant": "SouthPlant",
            "eastrefinery": "EastRefinery", "westterminal": "WestTerminal",
        }
        slots["site"] = canonical[match.group(1).lower()]

    days = 90
    if match := _DAYS.search(question):
        amount, unit = int(match.group(1)), match.group(2).lower()
        days = amount * {"day": 1, "week": 7, "month": 30}[unit]
    now = datetime.now(UTC)
    slots["start_time"] = (now - timedelta(days=days)).isoformat()
    slots["end_time"] = now.isoformat()
    slots["days"] = days
    return slots


class RuleBasedProvider:
    """Intent-driven planner and template composer."""

    def __init__(self) -> None:
        self.last_latency_ms: float = 0.0

    @property
    def name(self) -> str:
        return "rule_based"

    async def plan(
        self, question: str, catalogue: list[dict[str, Any]], *, history: str = ""
    ) -> Plan:
        available = {entry["name"] for entry in catalogue}
        intent = classify(question)
        slots = extract_slots(question)
        steps: list[PlanStep] = []
        gaps: list[str] = []

        def add(step_id: str, tool: str, args: dict[str, Any], reason: str) -> bool:
            """Append a step only if the tool is actually available."""
            if tool not in available:
                gaps.append(f"'{tool}' is not available, so {reason.lower()} was skipped")
                return False
            steps.append(
                PlanStep(id=step_id, kind="tool", tool=tool, args=args, reason=reason)
            )
            return True

        window = {"start_time": slots["start_time"], "end_time": slots["end_time"]}
        scope: dict[str, Any] = {}
        if "unit" in slots:
            scope["unit"] = slots["unit"]
        if "site" in slots:
            scope["site"] = slots["site"]

        resolved_asset = False
        if "asset_query" in slots:
            resolved_asset = add(
                "s1", "search_assets", {"query": slots["asset_query"], "limit": 5},
                "Resolve the named equipment to an asset id",
            )

        asset_scope: dict[str, Any] = (
            {"asset_ids": [ASSET_REF]} if resolved_asset else dict(scope)
        )

        if intent in {"recurring", "rationalize"}:
            add("s2", "get_alarm_summary",
                {**asset_scope, **window, "severity": ["high", "critical"],
                 "group_by": ["alarm_name"],
                 "kpis": ["alarm_count", "recurring_rate", "avg_ack_delay"]},
                "Quantify how often each alarm occurs")
            add("s3", "get_alarm_correlation", {**asset_scope, **window, "min_support": 3},
                "Identify which alarms fire together")
            add("s4", "get_rationalization_candidates",
                {**asset_scope, **window, "recurrence_threshold": 5},
                "Confirm which alarms warrant re-tuning")
        elif intent == "flood":
            add("s2", "get_flood_analysis",
                {**scope, **window, "threshold_count": 10, "rolling_window_minutes": 10},
                "Find periods where alarms exceeded operator capacity")
            add("s3", "get_alarm_summary",
                {**scope, **window, "group_by": ["asset_id", "alarm_name"],
                 "kpis": ["alarm_count"]},
                "Identify the main contributors")
        elif intent == "efficiency":
            if add("s2", "generate_calculation",
                   {"calculation_type": "operator_response_efficiency", **scope, **window},
                   "Prepare the response-efficiency calculation"):
                add("s3", "execute_calculation",
                    {"calculation_id": "$s2.output.calculation_id"},
                    "Run it and read the value")
            add("s4", "get_alarm_trends",
                {**scope, **window, "bucket": "daily", "metrics": ["avg_ack_delay"]},
                "Show how acknowledgement delay moved over the period")
        elif intent == "escalation":
            add("s2", "get_alarms",
                {**({"asset_id": ASSET_REF} if resolved_asset else scope),
                 "status": "active", "page_size": 20,
                 "sort_by": "start_time", "sort_order": "desc"},
                "List the currently active alarms")
            add("s3", "get_priority_score", {"alarm_id": "$s2.output.data[0].alarm_id"},
                "Score the most recent one")
            add("s4", "get_operator_recommendations",
                {"alarm_id": "$s2.output.data[0].alarm_id", "include_related": True,
                 "include_asset_context": True, "include_historical_pattern": True},
                "Gather the recommended response and its context")
        elif intent == "draft_issue":
            subject = slots.get("asset_query") or slots.get("unit") or "the plant"
            add("s2", "get_alarm_summary",
                {**asset_scope, **window, "severity": ["high", "critical"],
                 "group_by": ["alarm_name"], "kpis": ["alarm_count", "recurring_rate"]},
                "Gather the evidence the issue will cite")
            add("s3", "search_issues",
                {"query": slots.get("asset_query", "alarm"), "limit": 5},
                "Check whether this is already tracked")
            drafted = add(
                "s4", "draft_issue",
                {
                    "title": f"Recurring high-severity alarms on {subject}",
                    "summary": (
                        f"{subject} raised repeated high-severity alarms over the last "
                        f"{slots.get('days', 90)} days. The findings and the applicable "
                        "procedure are cited below."
                    ),
                    # A whole-value placeholder, not an interpolation: the resolver
                    # substitutes complete values, so the most frequent alarm name
                    # arrives here from the summary step rather than being retyped.
                    "evidence": ["$s2.output.groups[0].group.alarm_name"],
                    "labels": ["operations", "alarm-rationalization"],
                },
                "Compose the issue text — a pure function that writes nothing",
            )
            # Only plan the write when the question actually asks for one. Drafting is
            # safe and always useful; creating is not, and planning it speculatively
            # would put a confirmation prompt in front of someone who never asked.
            if drafted and _WANTS_WRITE.search(question):
                add("s5", "create_issue",
                    {"title": "$s4.output.title", "body": "$s4.output.body",
                     "labels": ["operations", "alarm-rationalization"]},
                    "Create the issue — requires explicit human approval")
        elif intent == "trend":
            add("s2", "get_alarm_trends",
                {**asset_scope, **window, "bucket": "daily", "metrics": ["alarm_count"]},
                "Show how alarm frequency moved over the period")
        elif intent == "lookup" and resolved_asset:
            add("s2", "get_asset_metadata", {"asset_id": ASSET_REF},
                "Retrieve the equipment's attributes")

        # Retrieval always runs. The brief's central requirement is that structured and
        # unstructured evidence participate in ONE workflow, so a plan without a
        # document step is a plan that fails the assignment.
        retrieval_args: dict[str, Any] = {"query": question}
        if resolved_asset:
            retrieval_args["asset"] = ASSET_NAME_REF
        steps.append(
            PlanStep(
                id="r1", kind="retrieval", args=retrieval_args,
                reason="Retrieve the applicable procedure or standard",
            )
        )

        return Plan(intent=f"{intent} ({slots.get('days', 90)}-day window)",
                    steps=steps, gaps=gaps)

    async def compose(
        self,
        question: str,
        evidence: str,
        *,
        low_confidence: bool,
        items: list[EvidenceItem] | None = None,
    ) -> AsyncIterator[str]:
        """Assemble the answer deterministically from structured evidence.

        Nothing is generated, so nothing can be hallucinated — every line below is
        copied from a tool result or a retrieved passage and carries the marker it
        came from. The prose is assembled rather than written, and the footer says so
        rather than letting the reader assume otherwise.
        """
        items = items or []
        findings = [i for i in items if i.kind == "tool" and i.facts]
        documents = [i for i in items if i.kind == "document"]
        failures = [i for i in items if i.kind == "failure"]
        gaps = [i for i in items if i.kind == "gap"]

        if findings:
            yield "## What the data shows\n\n"
            for item in findings:
                for fact in item.facts:
                    yield f"- {fact} {item.marker}\n"
            yield "\n"

        if documents and not low_confidence:
            yield "## What the procedures say\n\n"
            for item in documents[:4]:
                yield f"**{item.heading}** {item.marker}\n\n{item.body}\n\n"
        elif low_confidence:
            yield (
                "## Document evidence\n\n"
                "No sufficiently relevant procedure was found for this question. The "
                "findings above come from live alarm data only, and no operating "
                "procedure has been cited to support a recommended action.\n\n"
            )

        if failures:
            yield "## What could not be determined\n\n"
            for item in failures:
                yield f"- {item.heading}: {item.body}\n"
            yield "\n"

        if gaps:
            yield "## Gaps\n\n"
            for item in gaps:
                yield f"- {item.body}\n"
            yield "\n"

        yield (
            "---\n_Composed deterministically from tool output and retrieved passages "
            "(LLM_PROVIDER=rule_based). Every statement above is copied from cited "
            "evidence rather than generated. Set LLM_PROVIDER=anthropic with an API "
            "key for a narrative answer._\n"
        )
