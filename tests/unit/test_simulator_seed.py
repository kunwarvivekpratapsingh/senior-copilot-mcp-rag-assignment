"""Seed-data guarantees — NFR-05 and risk R-6.

Four flows in the supplied chaining collection assert non-empty results, and several
analytics endpoints are meaningless on uniformly random data. The seed generator
plants each required pattern deliberately; these tests fail loudly if a change to
the generator removes one.

Without these, a regression in the generator would surface as a confusing newman
failure in CI rather than as a clear statement of what is missing.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from alarm_simulator.config import Settings
from alarm_simulator.seed import SeedGenerator
from fastapi.testclient import TestClient

from tests.conftest import AUTH_HEADERS

FIXED_NOW = datetime(2026, 8, 13, 12, 0, 0, tzinfo=UTC)


def generate(seed: int = 20260811) -> tuple[list[object], list[object]]:
    settings = Settings(alarm_sim_seed=seed)
    return SeedGenerator(settings, now=FIXED_NOW).generate()  # type: ignore[return-value]


# --------------------------------------------------------------------------- #
# Reproducibility — NFR-05
# --------------------------------------------------------------------------- #


class TestReproducibility:
    def test_same_seed_produces_identical_ids(self) -> None:
        first_assets, first_alarms = generate()
        second_assets, second_alarms = generate()
        assert [a.asset_id for a in first_assets] == [a.asset_id for a in second_assets]  # type: ignore[attr-defined]
        assert [a.alarm_id for a in first_alarms] == [a.alarm_id for a in second_alarms]  # type: ignore[attr-defined]

    def test_same_seed_produces_identical_alarm_names(self) -> None:
        _, first = generate()
        _, second = generate()
        assert [a.alarm_name for a in first] == [a.alarm_name for a in second]  # type: ignore[attr-defined]

    def test_different_seed_produces_different_data(self) -> None:
        _, default_alarms = generate()
        _, other_alarms = generate(seed=999)
        assert [a.alarm_name for a in default_alarms] != [a.alarm_name for a in other_alarms]  # type: ignore[attr-defined]


# --------------------------------------------------------------------------- #
# Assets the chaining collection requires
# --------------------------------------------------------------------------- #


class TestRequiredAssets:
    def test_boiler_feed_pump_101_exists(self) -> None:
        """CHAIN-01 and the mandatory acceptance scenario both resolve this by name."""
        assets, _ = generate()
        names = {a.asset_name for a in assets}  # type: ignore[attr-defined]
        assert "Boiler Feed Pump 101" in names
        assert "Boiler Feed Pump 102" in names  # CHAIN-05

    def test_compressor_assets_exist(self) -> None:
        """CHAIN-03 asserts the compressor search returns more than zero results."""
        assets, _ = generate()
        matches = [a for a in assets if "compressor" in a.asset_name.lower()]  # type: ignore[attr-defined]
        assert len(matches) >= 3

    def test_motors_exist_in_unit_5(self) -> None:
        """CHAIN-08 searches for motors restricted to Unit 5 and asserts non-empty."""
        assets, _ = generate()
        matches = [
            a for a in assets  # type: ignore[attr-defined]
            if "motor" in a.asset_name.lower() and a.unit == "Unit 5"
        ]
        assert len(matches) >= 3

    def test_every_site_and_unit_referenced_by_the_collections_exists(self) -> None:
        assets, _ = generate()
        sites = {a.site for a in assets}  # type: ignore[attr-defined]
        units = {a.unit for a in assets}  # type: ignore[attr-defined]
        assert {"NorthPlant", "SouthPlant", "EastRefinery"} <= sites
        assert {f"Unit {n}" for n in range(1, 6)} <= units


# --------------------------------------------------------------------------- #
# Alarm patterns the analytics endpoints need
# --------------------------------------------------------------------------- #


class TestEngineeredPatterns:
    def test_bfp101_has_a_recurring_co_occurring_pair(self) -> None:
        """The acceptance scenario needs correlation to return a real finding."""
        assets, alarms = generate()
        bfp = next(a for a in assets if a.asset_name == "Boiler Feed Pump 101")  # type: ignore[attr-defined]
        own = [a for a in alarms if a.asset_id == bfp.asset_id]  # type: ignore[attr-defined]

        primary = [a for a in own if a.alarm_name == "Discharge Pressure Low"]  # type: ignore[attr-defined]
        secondary = [a for a in own if a.alarm_name == "Suction Strainer DP High"]  # type: ignore[attr-defined]
        assert len(primary) >= 25
        assert len(secondary) >= 25

        # The pair must actually fall inside the 15-minute correlation window.
        secondary_times = sorted(a.start_time for a in secondary)  # type: ignore[attr-defined]
        close_pairs = sum(
            1
            for p in primary
            if any(
                timedelta(0) < (s - p.start_time) <= timedelta(minutes=15)  # type: ignore[attr-defined]
                for s in secondary_times
            )
        )
        assert close_pairs >= 20, "the engineered pair must fall inside the lag window"

    def test_bfp101_alarms_are_high_severity_and_recent(self) -> None:
        assets, alarms = generate()
        bfp = next(a for a in assets if a.asset_name == "Boiler Feed Pump 101")  # type: ignore[attr-defined]
        own = [a for a in alarms if a.asset_id == bfp.asset_id]  # type: ignore[attr-defined]
        cutoff = FIXED_NOW - timedelta(days=90)
        recent_high = [
            a for a in own  # type: ignore[attr-defined]
            if a.severity in {"high", "critical"} and a.start_time >= cutoff
        ]
        assert len(recent_high) >= 50

    def test_flood_bursts_exist_in_unit_2(self) -> None:
        assets, alarms = generate()
        unit2 = {a.asset_id for a in assets if a.unit == "Unit 2" and a.site == "NorthPlant"}  # type: ignore[attr-defined]
        scoped = sorted(
            (a for a in alarms if a.asset_id in unit2),  # type: ignore[attr-defined]
            key=lambda a: a.start_time,
        )
        window = timedelta(minutes=10)
        densest = max(
            (
                sum(1 for b in scoped if 0 <= (b.start_time - a.start_time).total_seconds() <= window.total_seconds())
                for a in scoped
            ),
            default=0,
        )
        assert densest >= 10, "flood analysis needs a burst above the default threshold"

    def test_stale_active_alarms_exist_in_northplant_unit_1(self) -> None:
        assets, alarms = generate()
        scoped = {
            a.asset_id for a in assets  # type: ignore[attr-defined]
            if a.site == "NorthPlant" and a.unit == "Unit 1"
        }
        stale = [
            a for a in alarms  # type: ignore[attr-defined]
            if a.asset_id in scoped
            and a.status == "active"
            and (FIXED_NOW - a.start_time) > timedelta(minutes=180)
        ]
        assert len(stale) >= 5

    def test_east_refinery_has_active_alarms(self) -> None:
        """CHAIN-09 asserts this list is non-empty before reading data[0]."""
        assets, alarms = generate()
        scoped = {a.asset_id for a in assets if a.site == "EastRefinery"}  # type: ignore[attr-defined]
        active = [a for a in alarms if a.asset_id in scoped and a.status == "active"]  # type: ignore[attr-defined]
        assert len(active) >= 5

    def test_unit_4_has_nuisance_repetition(self) -> None:
        from collections import Counter

        assets, alarms = generate()
        scoped = {
            a.asset_id for a in assets  # type: ignore[attr-defined]
            if a.site == "SouthPlant" and a.unit == "Unit 4"
        }
        counts = Counter(
            a.alarm_name for a in alarms if a.asset_id in scoped  # type: ignore[attr-defined]
        )
        assert any(c >= 8 for c in counts.values())

    def test_alarm_types_include_safety_and_device(self) -> None:
        """CHAIN-08 filters summary on alarm_types ["safety", "device"]."""
        _, alarms = generate()
        types = {a.alarm_type for a in alarms}  # type: ignore[attr-defined]
        assert {"safety", "device", "process"} <= types


# --------------------------------------------------------------------------- #
# Invariants
# --------------------------------------------------------------------------- #


class TestSeedInvariants:
    def test_active_alarms_are_never_acknowledged(self) -> None:
        _, alarms = generate()
        for alarm in alarms:
            if alarm.status == "active":  # type: ignore[attr-defined]
                assert alarm.ack_delay_seconds is None  # type: ignore[attr-defined]
                assert alarm.ack_time is None  # type: ignore[attr-defined]

    def test_cleared_alarms_end_after_they_start(self) -> None:
        _, alarms = generate()
        for alarm in alarms:
            if alarm.end_time is not None:  # type: ignore[attr-defined]
                assert alarm.end_time > alarm.start_time  # type: ignore[attr-defined]

    def test_every_alarm_references_a_real_asset(self) -> None:
        assets, alarms = generate()
        known = {a.asset_id for a in assets}  # type: ignore[attr-defined]
        assert all(a.asset_id in known for a in alarms)  # type: ignore[attr-defined]

    def test_identifiers_are_unique(self) -> None:
        assets, alarms = generate()
        assert len({a.asset_id for a in assets}) == len(assets)  # type: ignore[attr-defined]
        assert len({a.alarm_id for a in alarms}) == len(alarms)  # type: ignore[attr-defined]


# --------------------------------------------------------------------------- #
# The same guarantees, through the live API
# --------------------------------------------------------------------------- #


def test_chaining_preconditions_hold_through_the_api(sim_client: TestClient) -> None:
    """The four searches the chaining collection asserts on must return results."""
    checks = [
        ({"query": "Boiler Feed Pump 101"}, "CHAIN-01"),
        ({"query": "compressor"}, "CHAIN-03"),
        ({"query": "motor", "unit": "Unit 5"}, "CHAIN-08"),
    ]
    for params, flow in checks:
        body = sim_client.get("/assets/search", params=params, headers=AUTH_HEADERS).json()
        assert body["results"], f"{flow} asserts this search returns more than zero results"

    active = sim_client.get(
        "/alarms",
        params={"site": "EastRefinery", "status": "active", "page_size": 50},
        headers=AUTH_HEADERS,
    ).json()
    assert active["data"], "CHAIN-09 asserts EastRefinery has active alarms"
