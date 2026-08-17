"""Analytics algorithm tests.

These exercise the computation directly with hand-built alarms rather than through
HTTP, so a failure points at the algorithm rather than at routing, auth, or the
database. Every input here is constructed so the expected answer can be worked out
by hand — an analytics test that asserts whatever the code currently returns is
worthless.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from alarm_simulator.analytics import (
    compute_correlation,
    compute_flood_windows,
    compute_kpis,
    compute_priority_score,
    compute_rationalization,
    compute_summary,
    compute_trends,
    execute_calculation,
)
from alarm_simulator.models import Alarm, Asset

BASE = datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)


def make_asset(asset_id: str = "AST-0001", criticality: str = "high") -> Asset:
    return Asset(
        asset_id=asset_id,
        asset_name=f"Test Asset {asset_id}",
        asset_type="pump",
        unit="Unit 2",
        site="NorthPlant",
        criticality=criticality,
        manufacturer="TestCo",
        model="T-1000",
        install_date=BASE - timedelta(days=1000),
        last_maintenance=BASE - timedelta(days=30),
    )


def make_alarm(
    alarm_id: str,
    name: str,
    offset_minutes: float,
    *,
    asset_id: str = "AST-0001",
    severity: str = "high",
    status: str = "cleared",
    ack_delay: int | None = 60,
) -> Alarm:
    return Alarm(
        alarm_id=alarm_id,
        asset_id=asset_id,
        alarm_name=name,
        alarm_type="process",
        severity=severity,
        status=status,
        start_time=BASE + timedelta(minutes=offset_minutes),
        end_time=None,
        ack_time=None,
        ack_delay_seconds=ack_delay,
        value=100.0,
        setpoint=80.0,
        unit_of_measure="barg",
        operator_id="OP-001",
    )


# --------------------------------------------------------------------------- #
# KPIs
# --------------------------------------------------------------------------- #


class TestKpis:
    def test_alarm_and_critical_counts(self) -> None:
        alarms = [
            make_alarm("A1", "Pressure Low", 0, severity="critical"),
            make_alarm("A2", "Pressure Low", 5, severity="high"),
            make_alarm("A3", "Vibration High", 10, severity="critical"),
        ]
        kpis = compute_kpis(alarms, ["alarm_count", "critical_count"])
        assert kpis["alarm_count"] == 3
        assert kpis["critical_count"] == 2

    def test_recurring_rate_is_the_share_of_repeats(self) -> None:
        """Four alarms across two distinct names -> two are repeats -> 0.5."""
        alarms = [
            make_alarm("A1", "Pressure Low", 0),
            make_alarm("A2", "Pressure Low", 1),
            make_alarm("A3", "Vibration High", 2),
            make_alarm("A4", "Vibration High", 3),
        ]
        assert compute_kpis(alarms, ["recurring_rate"])["recurring_rate"] == 0.5

    def test_recurring_rate_is_zero_when_every_alarm_is_unique(self) -> None:
        alarms = [make_alarm(f"A{i}", f"Alarm {i}", i) for i in range(4)]
        assert compute_kpis(alarms, ["recurring_rate"])["recurring_rate"] == 0.0

    def test_avg_ack_delay_ignores_unacknowledged_alarms(self) -> None:
        alarms = [
            make_alarm("A1", "Pressure Low", 0, ack_delay=100),
            make_alarm("A2", "Pressure Low", 1, ack_delay=200),
            make_alarm("A3", "Pressure Low", 2, status="active", ack_delay=None),
        ]
        # Mean of 100 and 200, not of 100, 200 and 0.
        assert compute_kpis(alarms, ["avg_ack_delay"])["avg_ack_delay"] == 150.0

    def test_kpis_on_empty_input_do_not_divide_by_zero(self) -> None:
        kpis = compute_kpis([], ["alarm_count", "recurring_rate", "avg_ack_delay"])
        assert kpis == {"alarm_count": 0.0, "recurring_rate": 0.0, "avg_ack_delay": 0.0}


# --------------------------------------------------------------------------- #
# Summary
# --------------------------------------------------------------------------- #


class TestSummary:
    def test_groups_by_alarm_name_and_orders_by_size(self) -> None:
        alarms = [
            make_alarm("A1", "Pressure Low", 0),
            make_alarm("A2", "Pressure Low", 1),
            make_alarm("A3", "Pressure Low", 2),
            make_alarm("A4", "Vibration High", 3),
        ]
        groups = compute_summary(alarms, [make_asset()], ["alarm_name"], ["alarm_count"])
        assert [g.group["alarm_name"] for g in groups] == ["Pressure Low", "Vibration High"]
        assert groups[0].kpis["alarm_count"] == 3

    def test_multi_dimensional_grouping(self) -> None:
        alarms = [
            make_alarm("A1", "Pressure Low", 0, severity="high"),
            make_alarm("A2", "Pressure Low", 1, severity="critical"),
        ]
        groups = compute_summary(
            alarms, [make_asset()], ["alarm_name", "severity"], ["alarm_count"]
        )
        assert len(groups) == 2
        assert all("alarm_name" in g.group and "severity" in g.group for g in groups)

    def test_asset_name_grouping_resolves_the_name(self) -> None:
        groups = compute_summary(
            [make_alarm("A1", "Pressure Low", 0)], [make_asset()], ["asset_name"], ["alarm_count"]
        )
        assert groups[0].group["asset_name"] == "Test Asset AST-0001"


# --------------------------------------------------------------------------- #
# Correlation
# --------------------------------------------------------------------------- #


class TestCorrelation:
    def test_detects_a_pair_inside_the_lag_window(self) -> None:
        alarms = []
        for i in range(5):
            alarms.append(make_alarm(f"A{i}", "Discharge Pressure Low", i * 120))
            alarms.append(make_alarm(f"B{i}", "Suction Strainer DP High", i * 120 + 5))

        pairs = compute_correlation(
            alarms, lag_window_minutes=15, severity_threshold="medium", min_support=1
        )
        forward = next(
            p for p in pairs
            if p.alarm_a == "Discharge Pressure Low" and p.alarm_b == "Suction Strainer DP High"
        )
        assert forward.support == 5
        assert forward.mean_lag_seconds == 300.0  # exactly five minutes

    def test_ignores_pairs_outside_the_lag_window(self) -> None:
        alarms = [
            make_alarm("A1", "Discharge Pressure Low", 0),
            make_alarm("B1", "Suction Strainer DP High", 60),  # an hour later
        ]
        pairs = compute_correlation(
            alarms, lag_window_minutes=15, severity_threshold="medium", min_support=1
        )
        assert pairs == []

    def test_does_not_correlate_across_different_assets(self) -> None:
        """Two alarms on unrelated equipment firing together is coincidence."""
        alarms = [
            make_alarm("A1", "Discharge Pressure Low", 0, asset_id="AST-0001"),
            make_alarm("B1", "Suction Strainer DP High", 2, asset_id="AST-0002"),
        ]
        pairs = compute_correlation(
            alarms, lag_window_minutes=15, severity_threshold="medium", min_support=1
        )
        assert pairs == []

    def test_min_support_filters_weak_pairs(self) -> None:
        alarms = [
            make_alarm("A1", "Alpha", 0),
            make_alarm("B1", "Beta", 1),
        ]
        assert compute_correlation(alarms, 15, "medium", min_support=1)
        assert compute_correlation(alarms, 15, "medium", min_support=2) == []

    def test_severity_threshold_excludes_lower_severities(self) -> None:
        alarms = [
            make_alarm("A1", "Alpha", 0, severity="low"),
            make_alarm("B1", "Beta", 1, severity="low"),
        ]
        assert compute_correlation(alarms, 15, "high", 1) == []

    def test_same_alarm_name_is_not_correlated_with_itself(self) -> None:
        alarms = [make_alarm(f"A{i}", "Pressure Low", i) for i in range(5)]
        assert compute_correlation(alarms, 15, "medium", 1) == []


# --------------------------------------------------------------------------- #
# Flood analysis
# --------------------------------------------------------------------------- #


class TestFloodAnalysis:
    def test_detects_a_burst_above_the_threshold(self) -> None:
        # 12 alarms inside five minutes.
        alarms = [make_alarm(f"A{i}", "Pressure Low", i * 0.4) for i in range(12)]
        windows = compute_flood_windows(alarms, threshold_count=10, rolling_window_minutes=10)
        assert len(windows) == 1
        assert windows[0].alarm_count == 12

    def test_ignores_traffic_below_the_threshold(self) -> None:
        alarms = [make_alarm(f"A{i}", "Pressure Low", i * 0.4) for i in range(5)]
        assert compute_flood_windows(alarms, threshold_count=10, rolling_window_minutes=10) == []

    def test_evenly_spread_alarms_do_not_trigger_a_flood(self) -> None:
        """Twenty alarms spread over a day is not a flood, however many there are."""
        alarms = [make_alarm(f"A{i}", "Pressure Low", i * 72) for i in range(20)]
        assert compute_flood_windows(alarms, threshold_count=10, rolling_window_minutes=10) == []

    def test_overlapping_detections_merge_into_one_burst(self) -> None:
        """One burst must yield one window, not one window per alarm in it."""
        alarms = [make_alarm(f"A{i}", "Pressure Low", i * 0.2) for i in range(30)]
        windows = compute_flood_windows(alarms, threshold_count=10, rolling_window_minutes=10)
        assert len(windows) == 1
        assert windows[0].alarm_count == 30

    def test_separate_bursts_stay_separate(self) -> None:
        first = [make_alarm(f"A{i}", "Pressure Low", i * 0.3) for i in range(12)]
        second = [make_alarm(f"B{i}", "Pressure Low", 600 + i * 0.3) for i in range(12)]
        windows = compute_flood_windows(first + second, 10, 10)
        assert len(windows) == 2

    def test_reports_the_dominant_alarm_name(self) -> None:
        alarms = [make_alarm(f"A{i}", "Pressure Low", i * 0.3) for i in range(10)]
        alarms += [make_alarm(f"B{i}", "Vibration High", i * 0.3) for i in range(2)]
        windows = compute_flood_windows(alarms, 10, 10)
        assert windows[0].dominant_alarm_name == "Pressure Low"

    def test_empty_input_returns_no_windows(self) -> None:
        assert compute_flood_windows([], 10, 10) == []


# --------------------------------------------------------------------------- #
# Rationalization
# --------------------------------------------------------------------------- #


class TestRationalization:
    def test_flags_recurrence_at_the_threshold(self) -> None:
        alarms = [make_alarm(f"A{i}", "Pressure Low", i * 60) for i in range(5)]
        candidates = compute_rationalization(
            alarms, [make_asset()], recurrence_threshold=5,
            stale_minutes_threshold=180, now=BASE + timedelta(days=1)
        )
        assert len(candidates) == 1
        assert candidates[0].occurrences == 5
        assert "threshold" in candidates[0].reason

    def test_does_not_flag_below_the_threshold(self) -> None:
        alarms = [make_alarm(f"A{i}", "Pressure Low", i * 60) for i in range(4)]
        assert compute_rationalization(
            alarms, [make_asset()], 5, 180, BASE + timedelta(days=1)
        ) == []

    def test_flags_stale_active_alarms_independently_of_recurrence(self) -> None:
        """A single alarm left open is a workflow problem, not a tuning problem."""
        alarms = [make_alarm("A1", "Pressure Low", 0, status="active", ack_delay=None)]
        candidates = compute_rationalization(
            alarms, [make_asset()], recurrence_threshold=5,
            stale_minutes_threshold=180, now=BASE + timedelta(hours=10)
        )
        assert len(candidates) == 1
        assert candidates[0].stale_count == 1
        assert "unacknowledged" in candidates[0].recommendation

    def test_recent_active_alarm_is_not_stale(self) -> None:
        alarms = [make_alarm("A1", "Pressure Low", 0, status="active", ack_delay=None)]
        assert compute_rationalization(
            alarms, [make_asset()], 5, 180, BASE + timedelta(minutes=30)
        ) == []


# --------------------------------------------------------------------------- #
# Priority scoring
# --------------------------------------------------------------------------- #


class TestPriorityScore:
    def test_critical_on_a_critical_asset_scores_higher_than_low_on_a_low_asset(self) -> None:
        high, _, _ = compute_priority_score(
            make_alarm("A1", "Pressure Low", 0, severity="critical", ack_delay=3600),
            make_asset(criticality="high"),
            [make_alarm(f"H{i}", "Pressure Low", i) for i in range(20)],
        )
        low, _, _ = compute_priority_score(
            make_alarm("A2", "Pressure Low", 0, severity="low", ack_delay=0),
            make_asset(criticality="low"),
            [],
        )
        assert high > low
        assert high == 100.0  # every factor saturated
        assert low == 0.0

    def test_score_stays_within_bounds(self) -> None:
        score, _, _ = compute_priority_score(
            make_alarm("A1", "Pressure Low", 0, severity="critical", ack_delay=999_999),
            make_asset(criticality="high"),
            [make_alarm(f"H{i}", "Pressure Low", i) for i in range(500)],
        )
        assert 0.0 <= score <= 100.0

    def test_every_factor_is_explained(self) -> None:
        """A bare number is not actionable; the copilot needs the components."""
        _, _, factors = compute_priority_score(
            make_alarm("A1", "Pressure Low", 0), make_asset(), []
        )
        assert {f.factor for f in factors} == {
            "severity", "asset_criticality", "recurrence", "ack_delay"
        }
        assert all(f.explanation for f in factors)

    def test_contributions_sum_to_the_score(self) -> None:
        score, _, factors = compute_priority_score(
            make_alarm("A1", "Pressure Low", 0, severity="high", ack_delay=1800),
            make_asset(criticality="medium"),
            [make_alarm(f"H{i}", "Pressure Low", i) for i in range(10)],
        )
        assert round(sum(f.contribution for f in factors), 2) == score

    def test_band_follows_the_score(self) -> None:
        _, band, _ = compute_priority_score(
            make_alarm("A1", "Pressure Low", 0, severity="low", ack_delay=0),
            make_asset(criticality="low"), [],
        )
        assert band == "low"


# --------------------------------------------------------------------------- #
# Trends
# --------------------------------------------------------------------------- #


class TestTrends:
    def test_daily_buckets_group_by_calendar_day(self) -> None:
        alarms = [
            make_alarm("A1", "Pressure Low", 0),
            make_alarm("A2", "Pressure Low", 60),          # same day
            make_alarm("A3", "Pressure Low", 60 * 24),      # next day
        ]
        points = compute_trends(alarms, "daily", ["alarm_count"])
        assert len(points) == 2
        assert points[0].metrics["alarm_count"] == 2
        assert points[1].metrics["alarm_count"] == 1

    def test_points_are_chronological(self) -> None:
        alarms = [make_alarm(f"A{i}", "Pressure Low", -i * 60 * 24) for i in range(5)]
        points = compute_trends(alarms, "daily", ["alarm_count"])
        starts = [p.bucket_start for p in points]
        assert starts == sorted(starts)


# --------------------------------------------------------------------------- #
# Calculations
# --------------------------------------------------------------------------- #


class TestCalculations:
    def test_operator_response_efficiency_is_the_prompt_share(self) -> None:
        alarms = [
            make_alarm("A1", "X", 0, ack_delay=60),     # prompt
            make_alarm("A2", "X", 1, ack_delay=120),    # prompt
            make_alarm("A3", "X", 2, ack_delay=6000),   # slow
            make_alarm("A4", "X", 3, ack_delay=7000),   # slow
        ]
        value, _, _, _ = execute_calculation(
            "operator_response_efficiency", alarms, [make_asset()], days=30
        )
        assert value == 0.5

    def test_critical_alarm_density_is_per_asset_per_day(self) -> None:
        alarms = [make_alarm(f"A{i}", "X", i, severity="critical") for i in range(10)]
        value, _, _, _ = execute_calculation(
            "critical_alarm_density", alarms, [make_asset()], days=10
        )
        assert value == 1.0  # 10 critical / (1 asset * 10 days)

    def test_nuisance_score_counts_only_recurring_names(self) -> None:
        alarms = [make_alarm(f"A{i}", "Recurring", i) for i in range(8)]
        alarms += [make_alarm(f"B{i}", f"Unique {i}", 100 + i) for i in range(2)]
        value, _, _, _ = execute_calculation(
            "nuisance_alarm_score", alarms, [make_asset()], days=30
        )
        assert value == 0.8  # 8 of 10

    def test_calculations_on_empty_input_return_zero(self) -> None:
        for calc in (
            "alarm_flood_index", "critical_alarm_density",
            "operator_response_efficiency", "nuisance_alarm_score",
        ):
            value, _, _, _ = execute_calculation(calc, [], [make_asset()], days=30)
            assert value == 0.0
