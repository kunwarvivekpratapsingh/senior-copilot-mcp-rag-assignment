"""End-to-end acceptance test — T-E2E-01..09.

Covers the mandated acceptance scenario over the **HTTP surface**, not the Python
objects: a POST to ``/chat``, an SSE stream parsed the way the browser parses it, and
assertions on what an evaluator would actually see.

The whole stack runs for real — FastAPI, the orchestrator, both MCP servers over the
MCP protocol, the alarm simulator, and a document index built from the real corpus.
Only two things are elided: the TCP socket (ASGI transport in its place) and the
Anthropic API (the deterministic provider in its place, so the test asserts on
grounded output rather than on generated prose).
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
import pytest
from alarm_api import AlarmApiClient
from alarm_mcp.server import mcp as alarm_server
from alarm_mcp.server import set_client
from alarm_simulator.main import app as simulator_app
from copilot_backend.api.app import create_app
from copilot_backend.llm import RuleBasedProvider
from copilot_backend.mcp_client import McpServerConfig, ToolInvoker, ToolRegistry
from copilot_backend.orchestrator import Copilot
from fastapi.testclient import TestClient
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
    persist = tmp_path_factory.mktemp("chroma-e2e")
    documents = load_corpus(CORPUS)
    embedder = HashingEmbedder()
    build_index(documents, chunk_corpus(documents), embedder, persist_path=persist, reset=True)
    return RetrievalService(DocumentIndex(embedder, persist_path=persist))


@asynccontextmanager
async def running_stack(retrieval: RetrievalService) -> AsyncIterator[TestClient]:
    """The backend, wired to live MCP servers and the simulator, served over ASGI."""
    set_client(
        AlarmApiClient(
            base_url="http://alarm-simulator",
            token="demo-token",  # noqa: S106 — the documented demo value
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
            app = create_app()
            # Injected, so this task keeps ownership of the MCP session lifetime.
            app.state.copilot = Copilot(
                registry=registry,
                invoker=ToolInvoker(registry=registry),
                provider=RuleBasedProvider(),
                retrieval=retrieval,
            )
            with TestClient(app) as client:
                yield client
    finally:
        set_client(None)


def parse_sse(body: str) -> list[tuple[str, dict[str, Any]]]:
    """Parse an SSE body the way the frontend does — frames split on a blank line.

    Line endings are normalised first: the SSE spec allows CRLF, LF, or a bare CR, and
    the server emits CRLF. A parser that only splits on ``\\n\\n`` silently merges every
    frame into one, which is exactly the bug this normalisation prevents.
    """
    events: list[tuple[str, dict[str, Any]]] = []
    for frame in body.replace("\r\n", "\n").replace("\r", "\n").split("\n\n"):
        name, data = "message", []
        for line in frame.splitlines():
            if line.startswith("event:"):
                name = line[6:].strip()
            elif line.startswith("data:"):
                data.append(line[5:].strip())
        if data:
            events.append((name, json.loads("\n".join(data))))
    return events


@pytest.fixture(scope="module")
def scenario(retrieval: RetrievalService, sim_client: object) -> Iterator[dict[str, Any]]:
    """Run the acceptance scenario once; every assertion below reads this result.

    ``sim_client`` is requested for its side effect: entering the simulator's lifespan
    creates and seeds its database. Without it the ASGI transport reaches a live app
    with no data behind it.
    """
    import anyio

    captured: dict[str, Any] = {}

    async def run() -> None:
        async with running_stack(retrieval) as client:
            response = client.post("/chat", json={"question": SCENARIO})
            captured["status"] = response.status_code
            captured["events"] = parse_sse(response.text)
            captured["health"] = client.get("/health").json()
            captured["tools"] = client.get("/mcp/tools").json()
            captured["servers"] = client.get("/mcp/servers").json()
            request_id = next(
                p for e, p in captured["events"] if e == "trace.started"
            )["request_id"]
            captured["trace"] = client.get(f"/traces/{request_id}").json()

    anyio.run(run)
    yield captured


def answer_of(scenario: dict[str, Any]) -> str:
    return "".join(p["text"] for e, p in scenario["events"] if e == "answer.delta")


def final_steps(scenario: dict[str, Any]) -> dict[str, dict[str, Any]]:
    steps: dict[str, dict[str, Any]] = {}
    for event, payload in scenario["events"]:
        if event.startswith("step.") or event == "confirmation.required":
            steps[payload["id"]] = payload
    return steps


# --------------------------------------------------------------------------- #


class TestSystemSurface:
    def test_health_reports_both_mcp_servers(self, scenario: dict[str, Any]) -> None:
        health = scenario["health"]
        assert health["status"] == "ok"
        assert health["tools"] == 17
        assert {s["name"] for s in health["servers"]} == {
            "alarm-management", "github-issues"
        }

    def test_the_tool_catalogue_exposes_schemas_for_inspection(
        self, scenario: dict[str, Any]
    ) -> None:
        """FR-31: the GUI's discovery view renders exactly this."""
        tools = scenario["tools"]["tools"]
        assert len(tools) == 17
        search = next(t for t in tools if t["name"] == "search_assets")
        assert search["input_schema"]["properties"]["query"]
        assert search["description"]
        assert search["qualified_name"] == "alarm-management/search_assets"

    def test_server_status_is_exposed_per_server(self, scenario: dict[str, Any]) -> None:
        statuses = {s["name"]: s for s in scenario["servers"]["servers"]}
        assert statuses["alarm-management"]["connected"]
        assert statuses["alarm-management"]["tool_count"] == 14
        assert statuses["github-issues"]["tool_count"] == 3


class TestAcceptanceScenario:
    def test_the_stream_completes(self, scenario: dict[str, Any]) -> None:
        assert scenario["status"] == 200
        names = [e for e, _ in scenario["events"]]
        assert names[0] == "trace.started"
        assert "plan.ready" in names
        assert names[-1] == "answer.completed"
        assert "error" not in names

    def test_the_execution_trace_is_streamed_step_by_step(
        self, scenario: dict[str, Any]
    ) -> None:
        """FR-21: the timeline fills in as work happens, which is what makes it
        evidence rather than a summary written afterwards."""
        names = [e for e, _ in scenario["events"]]
        assert names.count("step.started") >= 4
        assert names.index("step.started") < names.index("answer.delta")

    def test_both_evidence_sources_were_used_in_one_workflow(
        self, scenario: dict[str, Any]
    ) -> None:
        steps = final_steps(scenario)
        assert {s["kind"] for s in steps.values()} == {"tool", "retrieval"}
        assert all(s["status"] == "succeeded" for s in steps.values())

    def test_a_tool_output_became_a_later_tool_input(
        self, scenario: dict[str, Any]
    ) -> None:
        steps = final_steps(scenario)
        asset_id = (steps["s1"]["output"] or {})["results"][0]["asset_id"]
        assert steps["s2"]["arguments"]["asset_ids"] == [asset_id]

    def test_retrieval_was_scoped_by_the_resolved_asset(
        self, scenario: dict[str, Any]
    ) -> None:
        assert final_steps(scenario)["r1"]["arguments"]["asset"] == "Boiler Feed Pump 101"

    def test_the_answer_cites_both_a_tool_and_a_document(
        self, scenario: dict[str, Any]
    ) -> None:
        """The single assertion the brief cares about most."""
        answer = answer_of(scenario)
        assert "[tool:" in answer
        assert "[source:" in answer

    def test_the_answer_reports_the_correlated_alarm_pair(
        self, scenario: dict[str, Any]
    ) -> None:
        """The 'likely contributing factors' half of the question. The pair is an
        engineered property of the seed data, so this is a real finding, not a fixture."""
        answer = answer_of(scenario)
        assert "Suction Strainer DP High" in answer
        assert "Discharge Pressure Low" in answer

    def test_the_cited_procedure_is_the_right_one(
        self, scenario: dict[str, Any]
    ) -> None:
        completed = next(p for e, p in scenario["events"] if e == "answer.completed")
        assert not completed["low_confidence"]
        assert "OP-BFP-101" in {c["doc_id"] for c in completed["citations"]}

    def test_every_citation_resolves_to_a_retrieved_passage(
        self, scenario: dict[str, Any]
    ) -> None:
        """A marker pointing at nothing is worse than no marker: it looks like evidence."""
        completed = next(p for e, p in scenario["events"] if e == "answer.completed")
        known = {c["citation"] for c in completed["citations"]}
        answer = answer_of(scenario)
        cited = {
            part.split("]")[0].strip()
            for part in answer.split("[source:")[1:]
        }
        assert cited
        assert cited <= known

    def test_the_trace_endpoint_returns_the_same_run(
        self, scenario: dict[str, Any]
    ) -> None:
        """FR-17: the trace outlives the stream that produced it."""
        trace = scenario["trace"]
        assert trace["question"] == SCENARIO
        assert len(trace["steps"]) == len(final_steps(scenario))
        assert trace["answer"] == answer_of(scenario)
        assert trace["planner_provider"] == "rule_based"

    def test_no_secret_appears_anywhere_in_the_response(
        self, scenario: dict[str, Any]
    ) -> None:
        """The bearer token lives in the MCP server's config and must never traverse
        the tool boundary — not in an argument, an output, an error, or the answer."""
        body = json.dumps(scenario["events"]) + json.dumps(scenario["trace"])
        assert "demo-token" not in body
        assert "Authorization" not in body
        assert "ALARM_API_TOKEN" not in body


class TestErrorSurface:
    def test_an_unknown_trace_id_is_a_404(self, retrieval: RetrievalService) -> None:
        import anyio

        async def run() -> None:
            async with running_stack(retrieval) as client:
                assert client.get("/traces/req-does-not-exist").status_code == 404

        anyio.run(run)

    def test_an_empty_question_is_rejected_by_validation(
        self, retrieval: RetrievalService
    ) -> None:
        import anyio

        async def run() -> None:
            async with running_stack(retrieval) as client:
                assert client.post("/chat", json={"question": ""}).status_code == 422

        anyio.run(run)
