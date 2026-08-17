"""Shared pytest fixtures."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from alarm_simulator.config import Settings
from alarm_simulator.main import app
from fastapi.testclient import TestClient

AUTH_TOKEN = "demo-token"
AUTH_HEADERS = {"Authorization": f"Bearer {AUTH_TOKEN}"}
TRACE_HEADERS = {
    **AUTH_HEADERS,
    "trace_id": "trace-test-0001",
    "x-client-id": "pytest-client",
    "x-metadata-tag": "unit-test",
}


@pytest.fixture(scope="session")
def sim_client() -> Iterator[TestClient]:
    """A simulator instance backed by a seeded in-memory database.

    Session-scoped because seeding 3000 alarms per test would dominate the run
    time. The simulator is read-only apart from calculation registration, which
    only ever appends, so tests cannot interfere with each other.
    """
    with TestClient(app) as client:
        yield client


@pytest.fixture(scope="session")
def settings() -> Settings:
    return Settings()


@pytest.fixture(scope="session")
def window() -> dict[str, str]:
    """A 90-day time range ending now, matching the acceptance scenario."""
    now = datetime.now(UTC)
    return {
        "start_time": (now - timedelta(days=90)).isoformat(),
        "end_time": now.isoformat(),
    }


@pytest.fixture(scope="session")
def bfp101_id(sim_client: TestClient) -> str:
    """The asset id for Boiler Feed Pump 101, resolved the way a caller would."""
    response = sim_client.get(
        "/assets/search", params={"query": "Boiler Feed Pump 101"}, headers=AUTH_HEADERS
    )
    results = response.json()["results"]
    assert results, "seed data must contain Boiler Feed Pump 101"
    return str(results[0]["asset_id"])
