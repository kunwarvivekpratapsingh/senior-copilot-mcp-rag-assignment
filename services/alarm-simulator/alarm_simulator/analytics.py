"""Analytics engine.

Everything the API computes rather than merely retrieves. Kept out of the routers so
each algorithm is unit-testable against a plain list of alarms with no HTTP or
database involved.

All functions are pure: they take alarms and parameters, and return values. Query
construction lives in the routers.
"""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta

from .models import Alarm, Asset
from .schemas import (
    SEVERITY_RANK,
    Bucket,
    CorrelationPair,
    FloodWindow,
    HistoricalPattern,
    KpiDefinition,
    PriorityFactor,
    RationalizationCandidate,
    RecommendedAction,
    SummaryGroup,
    TrendPoint,
)

# Recurrence at or above this count marks an alarm name as a suppression
# candidate for the `suppression_candidate_rate` KPI.
SUPPRESSION_RECURRENCE = 5

# An acknowledgement within this many seconds counts as prompt for the operator
# response-efficiency calculation.
PROMPT_ACK_SECONDS = 300


def _aware(value: datetime) -> datetime:
    """SQLite loses timezone information; restore UTC so arithmetic is safe."""
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


# --------------------------------------------------------------------------- #
# Summary
# --------------------------------------------------------------------------- #


def _group_key(alarm: Alarm, asset_names: dict[str, str], dimensions: list[str]) -> dict[str, str]:
    values: dict[str, str] = {}
    for dim in dimensions:
        if dim == "alarm_name":
            values[dim] = alarm.alarm_name
        elif dim == "asset_id":
            values[dim] = alarm.asset_id
        elif dim == "asset_name":
            values[dim] = asset_names.get(alarm.asset_id, alarm.asset_id)
        elif dim == "severity":
            values[dim] = alarm.severity
    return values


def compute_kpis(alarms: list[Alarm], kpis: list[str]) -> dict[str, float]:
    """Evaluate the requested KPIs over one group of alarms."""
    result: dict[str, float] = {}
    total = len(alarms)
    name_counts = Counter(a.alarm_name for a in alarms)

    for kpi in kpis:
        if kpi == "alarm_count":
            result[kpi] = float(total)
        elif kpi == "critical_count":
            result[kpi] = float(sum(1 for a in alarms if a.severity == "critical"))
        elif kpi == "avg_ack_delay":
            delays = [a.ack_delay_seconds for a in alarms if a.ack_delay_seconds is not None]
            result[kpi] = round(statistics.fmean(delays), 1) if delays else 0.0
        elif kpi == "recurring_rate":
            # Proportion of alarms that are repeats of a name already seen.
            # 0.0 means every alarm was unique; approaching 1.0 means the same
            # handful of alarms firing over and over.
            distinct = len(name_counts)
            result[kpi] = round((total - distinct) / total, 4) if total else 0.0
        elif kpi == "suppression_candidate_rate":
            flagged = sum(c for c in name_counts.values() if c >= SUPPRESSION_RECURRENCE)
            result[kpi] = round(flagged / total, 4) if total else 0.0
    return result


def compute_summary(
    alarms: list[Alarm], assets: list[Asset], group_by: list[str], kpis: list[str]
) -> list[SummaryGroup]:
    asset_names = {a.asset_id: a.asset_name for a in assets}
    buckets: dict[tuple[tuple[str, str], ...], list[Alarm]] = defaultdict(list)

    for alarm in alarms:
        key = _group_key(alarm, asset_names, group_by)
        buckets[tuple(sorted(key.items()))].append(alarm)

    groups = [
        SummaryGroup(group=dict(key), kpis=compute_kpis(group_alarms, kpis))
        for key, group_alarms in buckets.items()
    ]
    # Largest groups first — the interesting rows should not be buried.
    groups.sort(key=lambda g: g.kpis.get("alarm_count", 0), reverse=True)
    return groups


# --------------------------------------------------------------------------- #
# Trends
# --------------------------------------------------------------------------- #


def _bucket_start(moment: datetime, bucket: str) -> datetime:
    moment = _aware(moment)
    if bucket == Bucket.HOURLY:
        return moment.replace(minute=0, second=0, microsecond=0)
    if bucket == Bucket.WEEKLY:
        start_of_day = moment.replace(hour=0, minute=0, second=0, microsecond=0)
        return start_of_day - timedelta(days=start_of_day.weekday())
    return moment.replace(hour=0, minute=0, second=0, microsecond=0)


def compute_trends(alarms: list[Alarm], bucket: str, metrics: list[str]) -> list[TrendPoint]:
    buckets: dict[datetime, list[Alarm]] = defaultdict(list)
    for alarm in alarms:
        buckets[_bucket_start(alarm.start_time, bucket)].append(alarm)

    points: list[TrendPoint] = []
    for bucket_start in sorted(buckets):
        group = buckets[bucket_start]
        values: dict[str, float] = {}
        for metric in metrics:
            if metric == "alarm_count":
                values[metric] = float(len(group))
            elif metric == "avg_ack_delay":
                delays = [a.ack_delay_seconds for a in group if a.ack_delay_seconds is not None]
                values[metric] = round(statistics.fmean(delays), 1) if delays else 0.0
        points.append(TrendPoint(bucket_start=bucket_start, metrics=values))
    return points


# --------------------------------------------------------------------------- #
# Correlation
# --------------------------------------------------------------------------- #


def compute_correlation(
    alarms: list[Alarm], lag_window_minutes: int, severity_threshold: str, min_support: int
) -> list[CorrelationPair]:
    """Co-occurrence analysis over alarm names.

    Two alarms co-occur when they fire on the **same asset** within the lag window.
    Restricting to one asset is what keeps the result meaningful: two alarms on
    unrelated equipment happening to fire together is coincidence, not correlation.

    For each ordered pair the function reports:

    * **support**  — how many times they co-occurred
    * **confidence** — support divided by occurrences of the first alarm, i.e. given
      A fired, how often did B follow
    * **lift** — confidence divided by B's base rate. Lift near 1.0 means the pair
      is no more related than chance; above 1.0 means genuine association.

    Complexity is O(n log n) for the sort plus O(n · k) for the window scan, where k
    is the number of alarms inside one lag window.
    """
    threshold = SEVERITY_RANK.get(severity_threshold, 0)
    eligible = [a for a in alarms if SEVERITY_RANK.get(a.severity, 0) >= threshold]
    if not eligible:
        return []

    total = len(eligible)
    name_counts = Counter(a.alarm_name for a in eligible)
    window = timedelta(minutes=lag_window_minutes)

    by_asset: dict[str, list[Alarm]] = defaultdict(list)
    for alarm in eligible:
        by_asset[alarm.asset_id].append(alarm)

    pair_support: Counter[tuple[str, str]] = Counter()
    pair_lags: dict[tuple[str, str], list[float]] = defaultdict(list)

    for asset_alarms in by_asset.values():
        ordered = sorted(asset_alarms, key=lambda a: _aware(a.start_time))
        for i, first in enumerate(ordered):
            first_start = _aware(first.start_time)
            for second in ordered[i + 1 :]:
                second_start = _aware(second.start_time)
                if second_start - first_start > window:
                    break  # ordered by time, so nothing further can be in window
                if first.alarm_name == second.alarm_name:
                    continue
                key = (first.alarm_name, second.alarm_name)
                pair_support[key] += 1
                pair_lags[key].append((second_start - first_start).total_seconds())

    pairs: list[CorrelationPair] = []
    for (name_a, name_b), support in pair_support.items():
        if support < min_support:
            continue
        confidence = support / name_counts[name_a]
        base_rate_b = name_counts[name_b] / total
        lift = confidence / base_rate_b if base_rate_b else 0.0
        pairs.append(
            CorrelationPair(
                alarm_a=name_a,
                alarm_b=name_b,
                support=support,
                confidence=round(confidence, 4),
                lift=round(lift, 4),
                mean_lag_seconds=round(statistics.fmean(pair_lags[(name_a, name_b)]), 1),
            )
        )

    pairs.sort(key=lambda p: (p.support, p.lift), reverse=True)
    return pairs


# --------------------------------------------------------------------------- #
# Flood analysis
# --------------------------------------------------------------------------- #


def compute_flood_windows(
    alarms: list[Alarm], threshold_count: int, rolling_window_minutes: int
) -> list[FloodWindow]:
    """Detect periods where alarm arrivals exceed what an operator can process.

    A forward-looking rolling window over time-sorted alarms. Overlapping detections
    are merged so one burst yields one window rather than one per alarm, which is
    what makes the output actionable instead of a wall of near-duplicates.
    """
    if not alarms:
        return []

    ordered = sorted(alarms, key=lambda a: _aware(a.start_time))
    window = timedelta(minutes=rolling_window_minutes)

    raw: list[tuple[datetime, datetime, list[Alarm]]] = []
    right = 0
    for left in range(len(ordered)):
        start = _aware(ordered[left].start_time)
        right = max(right, left)
        while right + 1 < len(ordered) and _aware(ordered[right + 1].start_time) - start <= window:
            right += 1
        members = ordered[left : right + 1]
        if len(members) >= threshold_count:
            raw.append((start, _aware(members[-1].start_time), members))

    # Merge overlapping detections into single bursts.
    merged: list[tuple[datetime, datetime, list[Alarm]]] = []
    for start, end, members in raw:
        if merged and start <= merged[-1][1]:
            prev_start, prev_end, prev_members = merged[-1]
            combined = {a.alarm_id: a for a in prev_members + members}
            merged[-1] = (prev_start, max(prev_end, end), list(combined.values()))
        else:
            merged.append((start, end, list(members)))

    windows: list[FloodWindow] = []
    for start, end, members in merged:
        span_minutes = max((end - start).total_seconds() / 60, 1.0)
        names = Counter(a.alarm_name for a in members)
        windows.append(
            FloodWindow(
                start=start,
                end=end,
                alarm_count=len(members),
                peak_rate_per_minute=round(len(members) / span_minutes, 2),
                contributing_assets=sorted({a.asset_id for a in members}),
                dominant_alarm_name=names.most_common(1)[0][0] if names else None,
            )
        )
    windows.sort(key=lambda w: w.alarm_count, reverse=True)
    return windows


# --------------------------------------------------------------------------- #
# Rationalization
# --------------------------------------------------------------------------- #


def compute_rationalization(
    alarms: list[Alarm],
    assets: list[Asset],
    recurrence_threshold: int,
    stale_minutes_threshold: int,
    now: datetime,
) -> list[RationalizationCandidate]:
    """Flag alarms that recur excessively or sit unacknowledged.

    Two independent triggers, because they call for different remedies: a recurring
    alarm usually needs its setpoint or deadband re-tuned, while a stale one points
    at a workflow problem rather than an instrument problem.
    """
    asset_names = {a.asset_id: a.asset_name for a in assets}
    stale_cutoff = timedelta(minutes=stale_minutes_threshold)

    grouped: dict[tuple[str, str], list[Alarm]] = defaultdict(list)
    for alarm in alarms:
        grouped[(alarm.asset_id, alarm.alarm_name)].append(alarm)

    candidates: list[RationalizationCandidate] = []
    for (asset_id, alarm_name), group in grouped.items():
        occurrences = len(group)
        stale_count = sum(
            1
            for a in group
            if a.status == "active" and (now - _aware(a.start_time)) > stale_cutoff
        )

        recurs = occurrences >= recurrence_threshold
        is_stale = stale_count > 0
        if not (recurs or is_stale):
            continue

        reasons: list[str] = []
        if recurs:
            reasons.append(f"occurred {occurrences} times, at or above the threshold of {recurrence_threshold}")
        if is_stale:
            reasons.append(
                f"{stale_count} occurrence(s) still active beyond {stale_minutes_threshold} minutes"
            )

        if recurs and is_stale:
            recommendation = "Review setpoint and deadband, and investigate why occurrences are not being acknowledged."
        elif recurs:
            recommendation = "Candidate for setpoint or deadband re-tuning, or suppression during known transients."
        else:
            recommendation = "Investigate why this alarm remains unacknowledged; check operator workload and routing."

        candidates.append(
            RationalizationCandidate(
                asset_id=asset_id,
                asset_name=asset_names.get(asset_id, asset_id),
                alarm_name=alarm_name,
                occurrences=occurrences,
                stale_count=stale_count,
                reason="; ".join(reasons),
                recommendation=recommendation,
            )
        )

    candidates.sort(key=lambda c: (c.occurrences, c.stale_count), reverse=True)
    return candidates


# --------------------------------------------------------------------------- #
# Priority scoring
# --------------------------------------------------------------------------- #

PRIORITY_WEIGHTS = {
    "severity": 0.35,
    "asset_criticality": 0.25,
    "recurrence": 0.25,
    "ack_delay": 0.15,
}


def compute_priority_score(
    alarm: Alarm, asset: Asset, same_name_history: list[Alarm]
) -> tuple[float, str, list[PriorityFactor]]:
    """Weighted composite score in the range 0–100.

    The factor breakdown is returned alongside the number deliberately. A bare score
    is not actionable, and the copilot needs the components to explain *why* an
    alarm ranks where it does without inventing a rationale.
    """
    severity_norm = SEVERITY_RANK.get(alarm.severity, 0) / 3
    criticality_norm = {"low": 0.0, "medium": 0.5, "high": 1.0}.get(asset.criticality, 0.5)
    # Saturates at 20 occurrences; beyond that, more repetition adds no urgency.
    recurrence_norm = min(len(same_name_history) / 20, 1.0)
    # Saturates at one hour of acknowledgement delay.
    delay_norm = min((alarm.ack_delay_seconds or 0) / 3600, 1.0)

    raw = {
        "severity": severity_norm,
        "asset_criticality": criticality_norm,
        "recurrence": recurrence_norm,
        "ack_delay": delay_norm,
    }
    explanations = {
        "severity": f"Alarm severity is {alarm.severity}.",
        "asset_criticality": f"Asset criticality is {asset.criticality}.",
        "recurrence": f"This alarm name occurred {len(same_name_history)} times on this asset.",
        "ack_delay": (
            f"Acknowledged after {alarm.ack_delay_seconds} seconds."
            if alarm.ack_delay_seconds is not None
            else "Not yet acknowledged."
        ),
    }

    factors = [
        PriorityFactor(
            factor=name,
            weight=weight,
            raw_value=round(raw[name], 4),
            contribution=round(raw[name] * weight * 100, 2),
            explanation=explanations[name],
        )
        for name, weight in PRIORITY_WEIGHTS.items()
    ]

    score = round(sum(f.contribution for f in factors), 2)
    if score >= 70:
        band = "critical"
    elif score >= 50:
        band = "high"
    elif score >= 30:
        band = "medium"
    else:
        band = "low"
    return score, band, factors


# --------------------------------------------------------------------------- #
# Operator recommendations
# --------------------------------------------------------------------------- #

# Keyword-driven action templates. Ordered most specific first, because
# "Bearing Temperature High" should match the bearing rule, not the generic
# temperature one.
ACTION_RULES: list[tuple[str, list[tuple[str, str, str]]]] = [
    (
        "Suction Strainer DP",
        [
            ("Check suction strainer differential pressure against the clean-filter baseline.",
             "A rising differential indicates progressive blockage.",
             "Confirms whether the strainer is fouled."),
            ("Inspect and clean the suction strainer if differential exceeds the alarm setpoint.",
             "Restores suction conditions and prevents cavitation damage.",
             "Differential returns to baseline."),
            ("Verify discharge pressure recovers after cleaning.",
             "Links the strainer condition to the downstream pressure alarm.",
             "Discharge pressure returns to normal band."),
        ],
    ),
    (
        "Discharge Pressure Low",
        [
            ("Verify suction conditions, including strainer differential and tank level.",
             "Low discharge pressure most often originates upstream.",
             "Identifies whether the cause is suction-side."),
            ("Check for cavitation indicators — noise, vibration, erratic flow.",
             "Cavitation damages impellers quickly if left running.",
             "Cavitation confirmed or excluded."),
            ("If suction is normal, inspect the impeller and wear rings for wear.",
             "Internal wear reduces developed head.",
             "Mechanical condition established."),
        ],
    ),
    (
        "Bearing Temperature",
        [
            ("Check lubrication level and condition at the affected bearing.",
             "Inadequate or degraded lubricant is the most common cause.",
             "Lubrication confirmed adequate or replenished."),
            ("Measure vibration at the bearing housing.",
             "Rising temperature with rising vibration indicates mechanical degradation.",
             "Bearing condition classified."),
            ("Plan a shutdown if temperature continues rising after lubrication is corrected.",
             "Continued operation risks bearing seizure.",
             "Failure avoided through planned intervention."),
        ],
    ),
    (
        "Vibration High",
        [
            ("Take a vibration spectrum reading and compare against the machine baseline.",
             "Spectral content distinguishes imbalance, misalignment, and bearing defects.",
             "Fault mechanism identified."),
            ("Inspect coupling alignment and foundation bolts.",
             "Misalignment and soft foot are common and cheap to correct.",
             "Mechanical fit-up confirmed."),
        ],
    ),
    (
        "Surge",
        [
            ("Verify anti-surge valve position and controller response.",
             "Surge protection failing to act is the immediate safety concern.",
             "Anti-surge system confirmed functional."),
            ("Check suction pressure and flow against the surge line.",
             "Establishes how close the machine is operating to surge.",
             "Operating point relocated to a safe margin."),
        ],
    ),
    (
        "Winding Temperature",
        [
            ("Verify motor loading against nameplate rating.",
             "Sustained overload is the most common cause of winding temperature rise.",
             "Load confirmed within rating."),
            ("Check cooling air path and filters for restriction.",
             "Restricted cooling raises winding temperature at constant load.",
             "Cooling restored."),
        ],
    ),
    (
        "Lube Oil Pressure Low",
        [
            ("Confirm lube oil pump operation and filter differential pressure.",
             "Loss of lube oil pressure risks immediate bearing damage.",
             "Oil supply restored or machine tripped safely."),
            ("Verify oil level and check for external leaks.",
             "Level loss is the simplest cause and the quickest to confirm.",
             "Oil inventory confirmed."),
        ],
    ),
]

GENERIC_ACTIONS: list[tuple[str, str, str]] = [
    ("Acknowledge the alarm and confirm the current process value against its setpoint.",
     "Establishes whether the condition is still present or has already cleared.",
     "Alarm state confirmed."),
    ("Review recent alarms on the same asset for a related pattern.",
     "Alarms rarely occur in isolation; a pattern usually points at the root cause.",
     "Related conditions identified."),
    ("Escalate to the responsible maintenance discipline if the condition persists.",
     "Ensures the alarm is not simply acknowledged and forgotten.",
     "Ownership assigned."),
]


def build_recommendations(alarm: Alarm) -> list[RecommendedAction]:
    templates = GENERIC_ACTIONS
    for keyword, rules in ACTION_RULES:
        if keyword.lower() in alarm.alarm_name.lower():
            templates = rules
            break
    return [
        RecommendedAction(order=i, action=action, rationale=rationale, expected_outcome=outcome)
        for i, (action, rationale, outcome) in enumerate(templates, start=1)
    ]


def compute_historical_pattern(history: list[Alarm], now: datetime) -> HistoricalPattern:
    cutoff = now - timedelta(days=90)
    recent = sorted(
        (a for a in history if _aware(a.start_time) >= cutoff),
        key=lambda a: _aware(a.start_time),
    )
    intervals = [
        (_aware(b.start_time) - _aware(a.start_time)).total_seconds() / 3600
        for a, b in zip(recent, recent[1:], strict=False)
    ]
    delays = [a.ack_delay_seconds for a in recent if a.ack_delay_seconds is not None]
    return HistoricalPattern(
        occurrences_90d=len(recent),
        mean_interval_hours=round(statistics.fmean(intervals), 2) if intervals else None,
        typical_ack_delay_seconds=round(statistics.fmean(delays), 1) if delays else None,
        is_recurring=len(recent) >= SUPPRESSION_RECURRENCE,
    )


# --------------------------------------------------------------------------- #
# Calculation code
# --------------------------------------------------------------------------- #

CALCULATION_CODE: dict[str, str] = {
    "alarm_flood_index": '''def alarm_flood_index(alarms, window_minutes=10, threshold=10):
    """Share of alarms arriving during flood conditions."""
    flooded = alarms_in_flood_windows(alarms, window_minutes, threshold)
    return len(flooded) / len(alarms) if alarms else 0.0''',
    "critical_alarm_density": '''def critical_alarm_density(alarms, assets, days):
    """Critical alarms per asset per day."""
    critical = [a for a in alarms if a.severity == "critical"]
    return len(critical) / (len(assets) * days) if assets and days else 0.0''',
    "operator_response_efficiency": '''def operator_response_efficiency(alarms, prompt_seconds=300):
    """Share of acknowledged alarms answered within the prompt threshold."""
    acked = [a for a in alarms if a.ack_delay_seconds is not None]
    prompt = [a for a in acked if a.ack_delay_seconds <= prompt_seconds]
    return len(prompt) / len(acked) if acked else 0.0''',
    "nuisance_alarm_score": '''def nuisance_alarm_score(alarms, recurrence_threshold=5):
    """Share of alarms belonging to excessively recurring alarm names."""
    counts = Counter(a.alarm_name for a in alarms)
    nuisance = sum(c for c in counts.values() if c >= recurrence_threshold)
    return nuisance / len(alarms) if alarms else 0.0''',
}

CALCULATION_UNITS = {
    "alarm_flood_index": "ratio",
    "critical_alarm_density": "alarms/asset/day",
    "operator_response_efficiency": "ratio",
    "nuisance_alarm_score": "ratio",
}


def execute_calculation(
    calculation_type: str, alarms: list[Alarm], assets: list[Asset], days: int
) -> tuple[float, list[str], list[list[object]], str]:
    """Run a generated calculation and return value, table, and interpretation."""
    if calculation_type == "alarm_flood_index":
        windows = compute_flood_windows(alarms, threshold_count=10, rolling_window_minutes=10)
        flooded = sum(w.alarm_count for w in windows)
        value = round(flooded / len(alarms), 4) if alarms else 0.0
        columns = ["window_start", "window_end", "alarm_count"]
        rows: list[list[object]] = [
            [w.start.isoformat(), w.end.isoformat(), w.alarm_count] for w in windows[:10]
        ]
        interpretation = (
            f"{value:.1%} of alarms in scope arrived during flood conditions, across "
            f"{len(windows)} detected window(s). Above roughly 10% the operator is being "
            "asked to absorb more than the console can reasonably present."
        )

    elif calculation_type == "critical_alarm_density":
        critical = [a for a in alarms if a.severity == "critical"]
        denominator = len(assets) * days
        value = round(len(critical) / denominator, 4) if denominator else 0.0
        by_asset = Counter(a.asset_id for a in critical)
        columns = ["asset_id", "critical_alarms"]
        rows = [[asset_id, count] for asset_id, count in by_asset.most_common(10)]
        interpretation = (
            f"{len(critical)} critical alarms across {len(assets)} assets over {days} days, "
            f"or {value} per asset per day."
        )

    elif calculation_type == "operator_response_efficiency":
        acked = [a for a in alarms if a.ack_delay_seconds is not None]
        prompt = [a for a in acked if (a.ack_delay_seconds or 0) <= PROMPT_ACK_SECONDS]
        value = round(len(prompt) / len(acked), 4) if acked else 0.0
        delays = [a.ack_delay_seconds or 0 for a in acked]
        columns = ["metric", "value"]
        rows = [
            ["acknowledged_alarms", len(acked)],
            ["within_threshold", len(prompt)],
            ["median_delay_seconds", round(statistics.median(delays), 1) if delays else 0],
        ]
        interpretation = (
            f"{value:.1%} of acknowledged alarms were answered within "
            f"{PROMPT_ACK_SECONDS} seconds."
        )

    elif calculation_type == "nuisance_alarm_score":
        counts = Counter(a.alarm_name for a in alarms)
        nuisance = sum(c for c in counts.values() if c >= SUPPRESSION_RECURRENCE)
        value = round(nuisance / len(alarms), 4) if alarms else 0.0
        columns = ["alarm_name", "occurrences"]
        rows = [
            [name, count]
            for name, count in counts.most_common(10)
            if count >= SUPPRESSION_RECURRENCE
        ]
        interpretation = (
            f"{value:.1%} of alarms in scope come from names recurring at least "
            f"{SUPPRESSION_RECURRENCE} times — the primary rationalization backlog."
        )

    else:  # pragma: no cover — guarded by the CalculationType enum
        raise ValueError(f"Unknown calculation type: {calculation_type}")

    return value, columns, rows, interpretation


# --------------------------------------------------------------------------- #
# KPI reference data
# --------------------------------------------------------------------------- #

KPI_DEFINITIONS = [
    KpiDefinition(
        name="alarm_count",
        display_name="Alarm count",
        description="Total alarms in the selected scope and time range.",
        formula="count(alarms)",
        unit="alarms",
    ),
    KpiDefinition(
        name="recurring_rate",
        display_name="Recurring rate",
        description="Proportion of alarms that repeat an alarm name already seen in scope.",
        formula="(count(alarms) - count(distinct alarm_name)) / count(alarms)",
        unit="ratio",
    ),
    KpiDefinition(
        name="avg_ack_delay",
        display_name="Average acknowledgement delay",
        description="Mean seconds between alarm onset and operator acknowledgement.",
        formula="mean(ack_time - start_time)",
        unit="seconds",
    ),
    KpiDefinition(
        name="critical_count",
        display_name="Critical alarm count",
        description="Alarms at critical severity.",
        formula="count(alarms where severity = 'critical')",
        unit="alarms",
    ),
    KpiDefinition(
        name="suppression_candidate_rate",
        display_name="Suppression candidate rate",
        description=(
            "Proportion of alarms belonging to names that recur at or above the "
            "rationalization threshold."
        ),
        formula=f"count(alarms in names with count >= {SUPPRESSION_RECURRENCE}) / count(alarms)",
        unit="ratio",
    ),
]
