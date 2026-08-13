"""Alarm Management API contract tests — T-SIM-01.

Covers FR-32 (simulator conforms to the Postman contract), FR-23 (authentication),
FR-26 (trace propagation), and FR-27 (pagination).

The four response paths asserted by the collections' own test scripts are checked
explicitly, because renaming any of them silently breaks `make contract`.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.conftest import AUTH_HEADERS, TRACE_HEADERS

# --------------------------------------------------------------------------- #
# Authentication — FR-23
# --------------------------------------------------------------------------- #


class TestAuthentication:
    def test_health_requires_no_token(self, sim_client: TestClient) -> None:
        """Container health checks must work without credentials."""
        response = sim_client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_missing_header_is_rejected(self, sim_client: TestClient) -> None:
        response = sim_client.get("/assets/search", params={"query": "pump"})
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "AUTH_FAILED"

    def test_wrong_token_is_rejected(self, sim_client: TestClient) -> None:
        response = sim_client.get(
            "/assets/search",
            params={"query": "pump"},
            headers={"Authorization": "Bearer not-the-token"},
        )
        assert response.status_code == 401

    def test_wrong_scheme_is_rejected(self, sim_client: TestClient) -> None:
        response = sim_client.get(
            "/assets/search",
            params={"query": "pump"},
            headers={"Authorization": "Basic demo-token"},
        )
        assert response.status_code == 401


# --------------------------------------------------------------------------- #
# Trace propagation — FR-26
# --------------------------------------------------------------------------- #


class TestTracePropagation:
    def test_supplied_trace_id_is_echoed(self, sim_client: TestClient) -> None:
        response = sim_client.get(
            "/assets/search", params={"query": "pump"}, headers=TRACE_HEADERS
        )
        assert response.headers["trace_id"] == "trace-test-0001"
        assert response.headers["x-client-id"] == "pytest-client"
        assert response.headers["x-metadata-tag"] == "unit-test"

    def test_trace_id_is_generated_when_absent(self, sim_client: TestClient) -> None:
        """A caller that supplies no trace id still gets one, so nothing is untraceable."""
        response = sim_client.get(
            "/assets/search", params={"query": "pump"}, headers=AUTH_HEADERS
        )
        assert response.headers["trace_id"].startswith("trace-")

    def test_trace_appears_in_analytical_response_bodies(
        self, sim_client: TestClient, bfp101_id: str, window: dict[str, str]
    ) -> None:
        """Body echo lets a caller confirm propagation without reading headers."""
        response = sim_client.post(
            "/alarms/summary",
            headers=TRACE_HEADERS,
            json={"asset_ids": [bfp101_id], "time_range": window},
        )
        assert response.json()["trace"]["trace_id"] == "trace-test-0001"

    def test_trace_id_is_present_on_error_responses(self, sim_client: TestClient) -> None:
        """A failure a caller cannot correlate is a failure they cannot debug."""
        response = sim_client.get("/alarms/NOPE-00000", headers=TRACE_HEADERS)
        assert response.status_code == 404
        assert response.json()["error"]["trace_id"] == "trace-test-0001"


# --------------------------------------------------------------------------- #
# Contract-critical response shapes
# --------------------------------------------------------------------------- #


class TestContractCriticalFieldNames:
    """The collections' test scripts index these exact paths."""

    def test_asset_search_returns_results_with_asset_id(self, sim_client: TestClient) -> None:
        body = sim_client.get(
            "/assets/search", params={"query": "Boiler Feed Pump 101"}, headers=AUTH_HEADERS
        ).json()
        assert "results" in body
        assert "asset_id" in body["results"][0]

    def test_alarm_list_returns_data_with_alarm_id(
        self, sim_client: TestClient, bfp101_id: str
    ) -> None:
        body = sim_client.get(
            "/alarms", params={"asset_id": bfp101_id}, headers=AUTH_HEADERS
        ).json()
        assert "data" in body, "the collections read body.data, not body.results"
        assert "alarm_id" in body["data"][0]

    def test_calculation_generate_returns_calculation_id(self, sim_client: TestClient) -> None:
        body = sim_client.post(
            "/calculation-code/generate",
            headers=AUTH_HEADERS,
            json={"calculation_type": "alarm_flood_index", "filters": {"unit": "Unit 3"}},
        ).json()
        assert "calculation_id" in body

    def test_flood_windows_have_start_and_end(
        self, sim_client: TestClient, window: dict[str, str]
    ) -> None:
        body = sim_client.post(
            "/alarms/flood-analysis",
            headers=AUTH_HEADERS,
            json={"unit": "Unit 2", "time_range": window, "threshold_count": 10,
                  "rolling_window_minutes": 10},
        ).json()
        assert body["flood_windows"], "seed data must produce flood windows in Unit 2"
        assert {"start", "end"} <= body["flood_windows"][0].keys()


# --------------------------------------------------------------------------- #
# Pagination — FR-27
# --------------------------------------------------------------------------- #


class TestPagination:
    def test_page_size_limits_returned_rows(
        self, sim_client: TestClient, bfp101_id: str
    ) -> None:
        body = sim_client.get(
            "/alarms",
            params={"asset_id": bfp101_id, "page": 1, "page_size": 5},
            headers=AUTH_HEADERS,
        ).json()
        assert len(body["data"]) == 5
        assert body["page_size"] == 5
        assert body["total_count"] > 5
        assert body["has_next"] is True

    def test_pages_do_not_overlap(self, sim_client: TestClient, bfp101_id: str) -> None:
        params = {"asset_id": bfp101_id, "page_size": 10, "sort_by": "start_time",
                  "sort_order": "desc"}
        first = sim_client.get("/alarms", params={**params, "page": 1}, headers=AUTH_HEADERS).json()
        second = sim_client.get("/alarms", params={**params, "page": 2}, headers=AUTH_HEADERS).json()
        first_ids = {a["alarm_id"] for a in first["data"]}
        second_ids = {a["alarm_id"] for a in second["data"]}
        assert not (first_ids & second_ids)

    def test_oversized_page_size_is_clamped_not_rejected(
        self, sim_client: TestClient, settings: object
    ) -> None:
        """Clamping keeps an otherwise valid chain working; rejecting would break it."""
        body = sim_client.get(
            "/alarms", params={"page_size": 100_000}, headers=AUTH_HEADERS
        ).json()
        assert body["page_size"] == 500

    def test_last_page_reports_no_next(self, sim_client: TestClient, bfp101_id: str) -> None:
        first = sim_client.get(
            "/alarms", params={"asset_id": bfp101_id, "page_size": 500}, headers=AUTH_HEADERS
        ).json()
        assert first["has_next"] is False


# --------------------------------------------------------------------------- #
# Filtering
# --------------------------------------------------------------------------- #


class TestFiltering:
    def test_status_filter(self, sim_client: TestClient) -> None:
        body = sim_client.get(
            "/alarms", params={"status": "active", "page_size": 50}, headers=AUTH_HEADERS
        ).json()
        assert body["data"]
        assert all(a["status"] == "active" for a in body["data"])

    def test_site_filter_only_present_in_the_chaining_collection(
        self, sim_client: TestClient
    ) -> None:
        body = sim_client.get(
            "/alarms", params={"site": "EastRefinery", "page_size": 20}, headers=AUTH_HEADERS
        ).json()
        assert body["total_count"] > 0

    def test_unit_filter_on_asset_search(self, sim_client: TestClient) -> None:
        body = sim_client.get(
            "/assets/search", params={"query": "motor", "unit": "Unit 5"}, headers=AUTH_HEADERS
        ).json()
        assert body["results"]
        assert all(a["unit"] == "Unit 5" for a in body["results"])

    def test_sort_order_is_honoured(self, sim_client: TestClient, bfp101_id: str) -> None:
        body = sim_client.get(
            "/alarms",
            params={"asset_id": bfp101_id, "sort_by": "start_time", "sort_order": "desc",
                    "page_size": 20},
            headers=AUTH_HEADERS,
        ).json()
        times = [a["start_time"] for a in body["data"]]
        assert times == sorted(times, reverse=True)

    def test_explicit_scope_matching_nothing_returns_nothing(
        self, sim_client: TestClient, window: dict[str, str]
    ) -> None:
        """An unmatched scope must not silently widen to the whole estate."""
        body = sim_client.post(
            "/alarms/summary",
            headers=AUTH_HEADERS,
            json={"asset_ids": ["AST-9999"], "time_range": window},
        ).json()
        assert body["total_alarms"] == 0


# --------------------------------------------------------------------------- #
# Error envelope — FR-25
# --------------------------------------------------------------------------- #


class TestErrorEnvelope:
    def test_unknown_asset_returns_not_found(self, sim_client: TestClient) -> None:
        response = sim_client.get("/assets/AST-9999/metadata", headers=AUTH_HEADERS)
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "NOT_FOUND"

    def test_unknown_alarm_returns_not_found(self, sim_client: TestClient) -> None:
        response = sim_client.post(
            "/alarms/priority-score", headers=AUTH_HEADERS, json={"alarm_id": "ALM-99999"}
        )
        assert response.status_code == 404

    def test_unknown_calculation_returns_not_found(self, sim_client: TestClient) -> None:
        response = sim_client.post(
            "/calculation-code/execute",
            headers=AUTH_HEADERS,
            json={"calculation_id": "CALC-does-not-exist", "filters": {}},
        )
        assert response.status_code == 404

    def test_invalid_enum_value_is_reported_as_invalid_input(
        self, sim_client: TestClient
    ) -> None:
        response = sim_client.post(
            "/calculation-code/generate",
            headers=AUTH_HEADERS,
            json={"calculation_type": "not_a_real_calculation", "filters": {}},
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "INVALID_INPUT"

    def test_every_error_uses_the_same_envelope(self, sim_client: TestClient) -> None:
        """One predictable shape is what lets the MCP server map errors reliably."""
        for response in (
            sim_client.get("/assets/search", params={"query": "x"}),  # 401
            sim_client.get("/alarms/NOPE", headers=AUTH_HEADERS),  # 404
        ):
            body = response.json()
            assert set(body) == {"error"}
            assert {"code", "message", "trace_id"} <= body["error"].keys()


# --------------------------------------------------------------------------- #
# Endpoint coverage — every one of the 15 responds
# --------------------------------------------------------------------------- #


def test_all_fifteen_endpoints_respond(
    sim_client: TestClient, bfp101_id: str, window: dict[str, str]
) -> None:
    """One assertion that the whole documented surface exists and works."""
    alarm_id = sim_client.get(
        "/alarms", params={"asset_id": bfp101_id, "page_size": 1}, headers=AUTH_HEADERS
    ).json()["data"][0]["alarm_id"]

    generated = sim_client.post(
        "/calculation-code/generate",
        headers=AUTH_HEADERS,
        json={"calculation_type": "nuisance_alarm_score", "filters": {"unit": "Unit 4"}},
    ).json()

    calls: list[tuple[str, str, dict[str, object] | None, dict[str, object] | None]] = [
        ("GET", "/health", None, None),
        ("GET", "/assets/search", {"query": "pump"}, None),
        ("GET", f"/assets/{bfp101_id}/metadata", None, None),
        ("GET", "/alarms", {"asset_id": bfp101_id}, None),
        ("GET", f"/alarms/{alarm_id}", None, None),
        ("POST", "/alarms/summary", None, {"asset_ids": [bfp101_id], "time_range": window}),
        ("POST", "/alarms/trends", None,
         {"asset_ids": [bfp101_id], "time_range": window, "bucket": "daily"}),
        ("POST", "/alarms/correlation", None, {"asset_ids": [bfp101_id], "time_range": window}),
        ("POST", "/alarms/flood-analysis", None, {"unit": "Unit 2", "time_range": window}),
        ("POST", "/alarms/rationalization-candidates", None,
         {"asset_ids": [bfp101_id], "time_range": window}),
        ("POST", "/alarms/priority-score", None, {"alarm_id": alarm_id}),
        ("POST", "/recommendations/operator-actions", None, {"alarm_id": alarm_id}),
        ("POST", "/calculation-code/generate", None,
         {"calculation_type": "alarm_flood_index", "filters": {}}),
        ("POST", "/calculation-code/execute", None,
         {"calculation_id": generated["calculation_id"], "filters": {}}),
        ("GET", "/analytics/kpi-definitions", None, None),
    ]

    for method, path, params, body in calls:
        response = sim_client.request(
            method, path, params=params, json=body, headers=AUTH_HEADERS
        )
        assert response.status_code == 200, f"{method} {path} -> {response.status_code}"
