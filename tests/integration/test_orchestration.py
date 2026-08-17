"""Orchestration tests — T-ORCH-01..12.

Covers FR-05 (chaining), FR-11/FR-12 (cited, grounded answers), FR-13 (low
confidence), FR-15 (MCP and RAG in a single workflow), FR-16 (conversation context),
FR-19 (unavailable tools), FR-20 (partial failure), FR-30 (write approval).

This is the file that proves the assignment's central claim: that MCP and RAG are
**one workflow**, not two features demonstrated side by side. Every test here drives
the real orchestrator over the real MCP servers and the real document index — only
the socket and the LLM are elided.

The placeholder resolver is unit-tested separately in ``tests/unit/test_resolver.py``;
here it is exercised end to end, because "step 2 received the id step 1 produced" is a
claim about the pipeline, not about a function.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
import pytest
from alarm_api import AlarmApiClient
from alarm_mcp.server import mcp as alarm_server
from alarm_mcp.server import set_client
from alarm_simulator.main import app as simulator_app
from copilot_backend.llm import RuleBasedProvider
from copilot_backend.mcp_client import McpServerConfig, ToolInvoker, ToolRegistry
from copilot_backend.orchestrator import Copilot
from copilot_backend.orchestrator.models import Plan, PlanStep
from github_mcp.server import mcp as github_server

from rag.ingestion import DocumentIndex, HashingEmbedder, build_index, chunk_corpus, load_corpus
from rag.retrieval import RetrievalService

CORPUS = Path(__file__).resolve().parents[2] / "rag" / "documents"

SCENARIO = (
    "Investigate recurring high-severity alarms for Boiler Feed Pump 101 over the last "
    "90 days, identify likely contributing factors, retrieve the relevant operating "
    "procedure, and provide recommended actions with source evidence."
)


@pytest.fixture(scope="module")
def retrieval(tmp_path_factory: pytest.TempPathFactory) -> RetrievalService:
    """A real index over the real corpus, built once for this module."""
    persist = tmp_path_factory.mktemp("chroma-orchestration")
    documents = load_corpus(CORPUS)
    embedder = HashingEmbedder()
    build_index(documents, chunk_corpus(documents), embedder, persist_path=persist, reset=True)
    return RetrievalService(DocumentIndex(embedder, persist_path=persist))


@asynccontextmanager
async def copilot(
    retrieval: RetrievalService | None,
    *,
    provider: Any = None,
    confirmed: set[str] | None = None,
) -> AsyncIterator[Copilot]:
    """A copilot wired to both MCP servers and the simulator, in-process.

    The registry is opened inside the test body rather than in a fixture: the MCP
    client's task group must be entered and exited from the same task, and pytest
    tears fixtures down in a different one.
    """
    set_client(
        AlarmApiClient(
            base_url="http://alarm-simulator",
            token="demo-token",  # noqa: S106 — the simulator's documented demo value
            transport=httpx.ASGITransport(app=simulator_app),
            max_retries=0,
        )
    )
    servers = [
        McpServerConfig("alarm-management", alarm_server),
        McpServerConfig("github-issues", github_server),
    ]
    try:
        async with ToolRegistry(servers=servers) as registry:
            yield Copilot(
                registry=registry,
                invoker=ToolInvoker(registry=registry),
                provider=provider or RuleBasedProvider(),
                retrieval=retrieval,
            )
    finally:
        set_client(None)


async def collect(
    bot: Copilot, question: str, **kwargs: Any
) -> tuple[list[tuple[str, dict[str, Any]]], str]:
    """Drain the event stream, returning the events and the assembled answer."""
    events: list[tuple[str, dict[str, Any]]] = []
    answer = ""
    async for event, payload in bot.ask(question, **kwargs):
        events.append((event, payload))
        if event == "answer.delta":
            answer += payload["text"]
    return events, answer


def steps_of(events: list[tuple[str, dict[str, Any]]]) -> dict[str, dict[str, Any]]:
    """The final state of each step, keyed by step id."""
    final: dict[str, dict[str, Any]] = {}
    for event, payload in events:
        if event.startswith("step.") or event == "confirmation.required":
            final[payload["id"]] = payload
    return final


class ScriptedProvider:
    """A provider that returns a fixed plan. Lets a test target one execution path
    without depending on what the planner happens to choose."""

    def __init__(self, plan: Plan) -> None:
        self._plan = plan
        self.last_latency_ms = 0.0
        self._fallback = RuleBasedProvider()

    @property
    def name(self) -> str:
        return "scripted"

    async def plan(self, question: str, catalogue: list[dict[str, Any]], **_: Any) -> Plan:
        return self._plan

    def compose(self, *args: Any, **kwargs: Any) -> Any:
        return self._fallback.compose(*args, **kwargs)


# --------------------------------------------------------------------------- #
# The acceptance scenario — FR-05, FR-11, FR-12, FR-15
# --------------------------------------------------------------------------- #


class TestAcceptanceScenario:
    async def test_plan_covers_both_evidence_sources(
        self, retrieval: RetrievalService, sim_client: object
    ) -> None:
        async with copilot(retrieval) as bot:
            events, _ = await collect(bot, SCENARIO)

        plan = next(p for e, p in events if e == "plan.ready")
        kinds = {s["kind"] for s in plan["steps"]}
        assert kinds == {"tool", "retrieval"}, "one workflow must span both sources"

    async def test_every_step_succeeds(
        self, retrieval: RetrievalService, sim_client: object
    ) -> None:
        async with copilot(retrieval) as bot:
            events, _ = await collect(bot, SCENARIO)

        final = steps_of(events)
        assert len(final) >= 4
        failures = {k: v["error_code"] for k, v in final.items() if v["status"] != "succeeded"}
        assert not failures, f"unexpected failures: {failures}"

    async def test_the_asset_id_from_step_one_reaches_step_two(
        self, retrieval: RetrievalService, sim_client: object
    ) -> None:
        """Chaining, asserted on the wire: the id the resolver substituted is the id
        the first step actually returned, not a value the test supplied."""
        async with copilot(retrieval) as bot:
            events, _ = await collect(bot, SCENARIO)

        final = steps_of(events)
        resolved = (final["s1"]["output"] or {})["results"][0]["asset_id"]
        assert final["s2"]["arguments"]["asset_ids"] == [resolved]
        assert "$s1" not in str(final["s2"]["arguments"])

    async def test_retrieval_is_narrowed_by_what_a_tool_discovered(
        self, retrieval: RetrievalService, sim_client: object
    ) -> None:
        """The document search is filtered by an asset name no one typed — the
        clearest evidence that the two subsystems share one workflow."""
        async with copilot(retrieval) as bot:
            events, _ = await collect(bot, SCENARIO)

        retrieval_step = steps_of(events)["r1"]
        assert retrieval_step["arguments"]["asset"] == "Boiler Feed Pump 101"
        assert retrieval_step["output"]["asset_filter"] == "Boiler Feed Pump 101"

    async def test_answer_cites_both_a_tool_and_a_document(
        self, retrieval: RetrievalService, sim_client: object
    ) -> None:
        """FR-15: the combined answer, with both marker kinds present."""
        async with copilot(retrieval) as bot:
            _, answer = await collect(bot, SCENARIO)

        assert "[tool:" in answer
        assert "[source:" in answer

    async def test_the_correct_procedure_is_cited(
        self, retrieval: RetrievalService, sim_client: object
    ) -> None:
        async with copilot(retrieval) as bot:
            events, _ = await collect(bot, SCENARIO)

        completed = next(p for e, p in events if e == "answer.completed")
        assert not completed["low_confidence"]
        assert "OP-BFP-101" in {c["doc_id"] for c in completed["citations"]}

    async def test_the_trace_is_retrievable_afterwards(
        self, retrieval: RetrievalService, sim_client: object
    ) -> None:
        """FR-17, FR-21: the timeline survives the request that produced it."""
        async with copilot(retrieval) as bot:
            events, _ = await collect(bot, SCENARIO)
            request_id = next(p for e, p in events if e == "trace.started")["request_id"]
            trace = bot.trace(request_id)

        assert trace is not None
        assert trace.answer
        assert len(trace.steps) >= 4
        assert trace.to_dict()["total_duration_ms"] > 0


# --------------------------------------------------------------------------- #
# Degradation — FR-13, FR-19, FR-20
# --------------------------------------------------------------------------- #


class TestDegradation:
    async def test_a_failed_step_does_not_stop_independent_steps(
        self, retrieval: RetrievalService, sim_client: object
    ) -> None:
        plan = Plan(
            intent="partial failure",
            steps=[
                PlanStep(id="s1", kind="tool", tool="get_alarm_by_id",
                         args={"alarm_id": "ALM-99999"}, reason="will fail"),
                PlanStep(id="s2", kind="tool", tool="search_assets",
                         args={"query": "Boiler Feed Pump 101"}, reason="independent"),
                PlanStep(id="r1", kind="retrieval", args={"query": "boiler feed pump"},
                         reason="independent"),
            ],
        )
        async with copilot(retrieval, provider=ScriptedProvider(plan)) as bot:
            events, answer = await collect(bot, "anything")

        final = steps_of(events)
        assert final["s1"]["status"] == "failed"
        assert final["s1"]["error_code"] == "NOT_FOUND"
        assert final["s2"]["status"] == "succeeded"
        assert final["r1"]["status"] == "succeeded"
        assert "could not be determined" in answer

    async def test_a_dependent_step_is_skipped_rather_than_guessed(
        self, retrieval: RetrievalService, sim_client: object
    ) -> None:
        """Running a step whose input never arrived produces a plausible wrong answer.
        Skipping it produces an honest gap."""
        plan = Plan(
            intent="broken chain",
            steps=[
                PlanStep(id="s1", kind="tool", tool="get_alarm_by_id",
                         args={"alarm_id": "ALM-99999"}, reason="will fail"),
                PlanStep(id="s2", kind="tool", tool="get_priority_score",
                         args={"alarm_id": "$s1.output.alarm_id"}, reason="depends on s1"),
            ],
        )
        async with copilot(retrieval, provider=ScriptedProvider(plan)) as bot:
            events, _ = await collect(bot, "anything")

        assert steps_of(events)["s2"]["status"] == "skipped"
        assert steps_of(events)["s2"]["error_code"] == "DEPENDENCY_FAILED"

    async def test_a_plan_naming_an_unknown_tool_is_pruned_before_execution(
        self, retrieval: RetrievalService, sim_client: object
    ) -> None:
        """A hallucinated tool name becomes a declared gap, never an attempted call."""
        plan = Plan(
            intent="hallucinated tool",
            steps=[
                PlanStep(id="s1", kind="tool", tool="predict_failure",
                         args={}, reason="does not exist"),
                PlanStep(id="s2", kind="tool", tool="search_assets",
                         args={"query": "pump"}, reason="real"),
            ],
        )
        async with copilot(retrieval, provider=ScriptedProvider(plan)) as bot:
            events, _ = await collect(bot, "anything")

        assert "s1" not in steps_of(events)
        ready = next(p for e, p in events if e == "plan.ready")
        assert any("predict_failure" in gap for gap in ready["gaps"])

    async def test_retrieval_finding_nothing_relevant_is_stated_not_hidden(
        self, retrieval: RetrievalService, sim_client: object
    ) -> None:
        """FR-13: the honest failure mode. A confident answer built on no evidence is
        the worst outcome available here."""
        plan = Plan(
            intent="off-corpus",
            steps=[
                PlanStep(id="r1", kind="retrieval",
                         args={"query": "quarterly marketing budget for the retail division"},
                         reason="nothing in the corpus covers this"),
            ],
        )
        async with copilot(retrieval, provider=ScriptedProvider(plan)) as bot:
            events, answer = await collect(bot, "what is the marketing budget?")

        completed = next(p for e, p in events if e == "answer.completed")
        assert completed["low_confidence"]
        assert "No sufficiently relevant procedure" in answer

    async def test_the_copilot_runs_without_a_document_index(
        self, sim_client: object
    ) -> None:
        """An unavailable index degrades the answer; it does not break the request."""
        async with copilot(None) as bot:
            events, answer = await collect(bot, SCENARIO)

        assert steps_of(events)["r1"]["error_code"] == "RETRIEVAL_UNAVAILABLE"
        assert "[tool:" in answer  # the alarm findings still arrive


# --------------------------------------------------------------------------- #
# Conflicting evidence — FR-12, guidelines §13
# --------------------------------------------------------------------------- #


class TestConflictingEvidence:
    """What happens when the live data contradicts the written standard.

    This is a real conflict in the seeded estate, not a contrived one: the response
    standard requires high-severity alarms to be acknowledged within 300 seconds, and
    Boiler Feed Pump 101's measured mean acknowledgement delay is roughly four times
    that. The correct behaviour is to surface both, each attributed to its own source,
    so the reader can see the gap — not to harmonise them into one comfortable
    sentence.
    """

    async def _run(self, retrieval: RetrievalService) -> tuple[list[Any], str]:
        plan = Plan(
            intent="acknowledgement performance against the standard",
            steps=[
                PlanStep(id="s1", kind="tool", tool="search_assets",
                         args={"query": "Boiler Feed Pump 101"}, reason="Resolve the asset"),
                PlanStep(id="s2", kind="tool", tool="get_alarm_summary",
                         args={"asset_ids": ["$s1.output.results[0].asset_id"],
                               "severity": ["high", "critical"],
                               "group_by": ["alarm_name"],
                               "kpis": ["alarm_count", "avg_ack_delay"]},
                         reason="Measure what actually happened"),
                PlanStep(id="r1", kind="retrieval",
                         args={"query": "acknowledgement target for high severity alarms "
                                        "operator response standard"},
                         reason="Retrieve the standard the measurement is judged against"),
            ],
        )
        async with copilot(retrieval, provider=ScriptedProvider(plan)) as bot:
            return await collect(bot, "Are we meeting the acknowledgement standard on BFP-101?")

    async def test_both_sides_of_the_conflict_reach_the_answer(
        self, retrieval: RetrievalService, sim_client: object
    ) -> None:
        events, answer = await self._run(retrieval)

        steps = steps_of(events)
        measured = max(
            group["kpis"]["avg_ack_delay"]
            for group in (steps["s2"]["output"] or {})["groups"]
        )
        assert measured > 300, "the seeded estate must actually breach the standard"

        assert "mean acknowledgement" in answer, "the measurement is missing"
        assert "300" in answer, "the standard it breaches is missing"

    async def test_each_side_keeps_its_own_attribution(
        self, retrieval: RetrievalService, sim_client: object
    ) -> None:
        """A conflict is only legible if the reader can tell which source said what."""
        _, answer = await self._run(retrieval)

        data_section = answer.split("## What the procedures say")[0]
        document_section = answer.split("## What the procedures say")[-1]

        assert "[tool: alarm-management/get_alarm_summary]" in data_section
        assert "[source:" in document_section
        assert "[tool:" not in document_section

    async def test_the_conflict_is_not_resolved_by_dropping_a_source(
        self, retrieval: RetrievalService, sim_client: object
    ) -> None:
        events, answer = await self._run(retrieval)
        completed = next(p for e, p in events if e == "answer.completed")

        assert not completed["low_confidence"]
        assert len(completed["citations"]) >= 1
        # Every retrieved passage that was cited is still traceable from the trace,
        # so nothing was quietly discarded to make the answer tidier.
        for citation in completed["citations"]:
            assert citation["doc_id"]
            assert citation["excerpt"]


# --------------------------------------------------------------------------- #
# Write approval — FR-30
# --------------------------------------------------------------------------- #


class TestWriteApproval:
    def _plan(self) -> Plan:
        return Plan(
            intent="file an issue",
            steps=[
                PlanStep(id="s1", kind="tool", tool="create_issue",
                         args={"title": "Recurring alarms on BFP-101", "body": "Details."},
                         reason="write"),
            ],
        )

    async def test_an_unconfirmed_write_pauses_for_approval(
        self, retrieval: RetrievalService, sim_client: object
    ) -> None:
        async with copilot(retrieval, provider=ScriptedProvider(self._plan())) as bot:
            events, _ = await collect(bot, "file an issue")

        assert any(e == "confirmation.required" for e, _ in events)
        assert steps_of(events)["s1"]["status"] == "failed"
        assert steps_of(events)["s1"]["error_code"] == "CONFIRMATION_REQUIRED"

    async def test_a_confirmed_write_proceeds(
        self, retrieval: RetrievalService, sim_client: object
    ) -> None:
        async with copilot(retrieval, provider=ScriptedProvider(self._plan())) as bot:
            events, _ = await collect(
                bot, "file an issue", confirmed_actions={"create_issue"}
            )

        assert not any(e == "confirmation.required" for e, _ in events)
        assert steps_of(events)["s1"]["status"] == "succeeded"
        assert (steps_of(events)["s1"]["output"] or {})["created"] is True

    async def test_approval_does_not_persist_into_the_next_request(
        self, retrieval: RetrievalService, sim_client: object
    ) -> None:
        """A grant is per-request. Sticky approval would let one 'yes' authorise
        writes the user never saw."""
        async with copilot(retrieval, provider=ScriptedProvider(self._plan())) as bot:
            first, _ = await collect(bot, "file it", confirmed_actions={"create_issue"})
            conversation = next(p for e, p in first if e == "trace.started")["conversation_id"]
            second, _ = await collect(bot, "file it again", conversation_id=conversation)

        assert steps_of(second)["s1"]["error_code"] == "CONFIRMATION_REQUIRED"


# --------------------------------------------------------------------------- #
# Conversation memory — FR-16
# --------------------------------------------------------------------------- #


class TestConversation:
    async def test_a_follow_up_stays_in_the_same_conversation(
        self, retrieval: RetrievalService, sim_client: object
    ) -> None:
        async with copilot(retrieval) as bot:
            first, _ = await collect(bot, "What is Boiler Feed Pump 101?")
            conversation = next(p for e, p in first if e == "trace.started")["conversation_id"]
            second, _ = await collect(
                bot, "And its recent alarms?", conversation_id=conversation
            )

        started = next(p for e, p in second if e == "trace.started")
        assert started["conversation_id"] == conversation
        assert started["request_id"] != next(
            p for e, p in first if e == "trace.started"
        )["request_id"]
