"""Deterministic synthetic-data generator.

Two properties matter more than realism.

**Reproducibility.** A fixed seed produces identical asset and alarm identifiers on
every run, so the demo, the tests, and the Postman collections all see the same
data. Timestamps are anchored to the current date so "last 90 days" queries always
return something; identifiers never move.

**Engineered patterns.** Four flows in the supplied chaining collection assert
non-empty results, and several analytics endpoints are meaningless on uniformly
random data — correlation over independent events finds nothing, and a flood
detector never fires if arrivals are evenly spread. So the generator deliberately
plants each pattern the API is supposed to surface:

===========================  =======================================  ===============
Pattern                      Where                                    Why
===========================  =======================================  ===============
Recurring co-occurring pair  Boiler Feed Pump 101, NorthPlant Unit 2  CHAIN-01, acceptance scenario
Compressor assets            SouthPlant Units 3 and 4                 CHAIN-03 asserts > 0
Motors in Unit 5             EastRefinery Unit 5                      CHAIN-08 asserts > 0
Active alarms at a site      EastRefinery                             CHAIN-09 asserts > 0
Flood bursts                 NorthPlant Unit 2                        Flood analysis
Stale active alarms          NorthPlant Unit 1                        CHAIN-06 rationalization
Nuisance repetition          SouthPlant Unit 4                        CHAIN-10
Spread acknowledgement delay SouthPlant                               CHAIN-07 efficiency
===========================  =======================================  ===============
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from .config import Settings
from .models import Alarm, Asset

# --------------------------------------------------------------------------- #
# Estate definition
# --------------------------------------------------------------------------- #

# (asset_name, asset_type, unit, site, criticality)
ASSET_SPECS: list[tuple[str, str, str, str, str]] = [
    # NorthPlant / Unit 1 — home of the stale active alarms
    ("Feedwater Heater 201", "heater", "Unit 1", "NorthPlant", "medium"),
    ("Condensate Pump 301", "pump", "Unit 1", "NorthPlant", "medium"),
    ("Deaerator 401", "vessel", "Unit 1", "NorthPlant", "high"),
    ("Circulating Pump 302", "pump", "Unit 1", "NorthPlant", "low"),
    # NorthPlant / Unit 2 — the acceptance scenario and the flood bursts
    ("Boiler Feed Pump 101", "pump", "Unit 2", "NorthPlant", "high"),
    ("Boiler Feed Pump 102", "pump", "Unit 2", "NorthPlant", "high"),
    ("Boiler Feed Pump 103", "pump", "Unit 2", "NorthPlant", "medium"),
    ("Forced Draft Fan 701", "fan", "Unit 2", "NorthPlant", "medium"),
    ("Induced Draft Fan 702", "fan", "Unit 2", "NorthPlant", "medium"),
    ("Superheater 801", "heater", "Unit 2", "NorthPlant", "high"),
    # SouthPlant / Unit 3 — compressors, critical-density calculations
    ("Air Compressor 501", "compressor", "Unit 3", "SouthPlant", "high"),
    ("Gas Compressor 502", "compressor", "Unit 3", "SouthPlant", "high"),
    ("Instrument Air Compressor 504", "compressor", "Unit 3", "SouthPlant", "medium"),
    ("Cooling Tower Fan 901", "fan", "Unit 3", "SouthPlant", "low"),
    # SouthPlant / Unit 4 — nuisance repetition
    ("Recycle Compressor 503", "compressor", "Unit 4", "SouthPlant", "medium"),
    ("Charge Pump 305", "pump", "Unit 4", "SouthPlant", "medium"),
    ("Reflux Pump 306", "pump", "Unit 4", "SouthPlant", "low"),
    ("Vacuum Pump 307", "pump", "Unit 4", "SouthPlant", "low"),
    # EastRefinery / Unit 5 — motors, and the site with live active alarms
    ("Induction Motor 601", "motor", "Unit 5", "EastRefinery", "high"),
    ("Induction Motor 602", "motor", "Unit 5", "EastRefinery", "medium"),
    ("Synchronous Motor 603", "motor", "Unit 5", "EastRefinery", "high"),
    ("Motor Driven Pump 604", "motor", "Unit 5", "EastRefinery", "medium"),
    ("Crude Charge Pump 308", "pump", "Unit 5", "EastRefinery", "high"),
    ("Reactor Feed Heater 202", "heater", "Unit 5", "EastRefinery", "high"),
    # WestTerminal — background estate so filters have something to exclude
    ("Transfer Pump 309", "pump", "Unit 1", "WestTerminal", "medium"),
    ("Booster Pump 310", "pump", "Unit 1", "WestTerminal", "low"),
    ("Loading Arm 1001", "valve", "Unit 2", "WestTerminal", "medium"),
    ("Storage Tank 1101", "tank", "Unit 2", "WestTerminal", "high"),
    ("Vapour Recovery Compressor 505", "compressor", "Unit 2", "WestTerminal", "medium"),
    ("Fire Water Pump 311", "pump", "Unit 3", "WestTerminal", "high"),
]

MANUFACTURERS = ["Flowserve", "Siemens", "ABB", "Sulzer", "Atlas Copco", "Emerson"]

# Alarm vocabulary by asset type. Realistic names matter because the RAG corpus
# references them, and the copilot's answers read better when the two agree.
ALARM_NAMES: dict[str, list[str]] = {
    "pump": [
        "Discharge Pressure Low",
        "Suction Strainer DP High",
        "Bearing Temperature High",
        "Seal Leak Detected",
        "Vibration High",
        "Motor Current High",
    ],
    "compressor": [
        "Surge Detected",
        "Discharge Temperature High",
        "Suction Pressure Low",
        "Lube Oil Pressure Low",
        "Vibration High",
    ],
    "motor": [
        "Winding Temperature High",
        "Vibration High",
        "Bearing Temperature High",
        "Overcurrent Trip",
    ],
    "fan": ["Vibration High", "Bearing Temperature High", "Motor Current High"],
    "heater": ["Tube Temperature High", "Level Low", "Pressure High"],
    "vessel": ["Level High", "Level Low", "Pressure High"],
    "tank": ["Level High", "Level Low", "Temperature High"],
    "valve": ["Position Deviation", "Actuator Fault", "Leak Detected"],
}

# Safety-classified alarm names; everything else is process or device. The
# chaining collection filters on alarm_types ["safety", "device"], so the
# distribution has to include both.
SAFETY_ALARMS = {"Overcurrent Trip", "Surge Detected", "Leak Detected", "Seal Leak Detected"}
DEVICE_ALARMS = {"Actuator Fault", "Position Deviation", "Vibration High"}

# The engineered pair for Boiler Feed Pump 101. These two co-occur inside the
# 15-minute lag window so /alarms/correlation returns a real finding, and they
# dominate the asset's alarm count so rationalization flags them.
BFP101_PAIR = ("Discharge Pressure Low", "Suction Strainer DP High")

UOM_BY_KEYWORD = [
    ("Pressure", "barg"),
    ("Temperature", "degC"),
    ("Vibration", "mm/s"),
    ("Current", "A"),
    ("Level", "%"),
    ("DP", "mbar"),
]


def _unit_of_measure(alarm_name: str) -> str | None:
    for keyword, uom in UOM_BY_KEYWORD:
        if keyword in alarm_name:
            return uom
    return None


def _alarm_type(alarm_name: str) -> str:
    if alarm_name in SAFETY_ALARMS:
        return "safety"
    if alarm_name in DEVICE_ALARMS:
        return "device"
    return "process"


class _IdFactory:
    """Sequential, zero-padded identifiers so IDs are stable and readable."""

    def __init__(self) -> None:
        self._asset = 0
        self._alarm = 0

    def asset(self) -> str:
        self._asset += 1
        return f"AST-{self._asset:04d}"

    def alarm(self) -> str:
        self._alarm += 1
        return f"ALM-{self._alarm:05d}"


class SeedGenerator:
    """Builds the synthetic estate and its alarm history."""

    def __init__(self, settings: Settings, now: datetime | None = None) -> None:
        self.settings = settings
        self.rng = random.Random(settings.alarm_sim_seed)  # noqa: S311 — not cryptographic
        self.ids = _IdFactory()
        self.now = now or datetime.now(UTC)
        self.window_start = self.now - timedelta(days=settings.alarm_sim_days)
        self.assets: list[Asset] = []
        self.alarms: list[Alarm] = []
        self._by_name: dict[str, Asset] = {}

    # -- assets ------------------------------------------------------------- #

    def _build_assets(self) -> None:
        for name, atype, unit, site, criticality in ASSET_SPECS:
            asset = Asset(
                asset_id=self.ids.asset(),
                asset_name=name,
                asset_type=atype,
                unit=unit,
                site=site,
                criticality=criticality,
                manufacturer=self.rng.choice(MANUFACTURERS),
                model=f"{atype[:3].upper()}-{self.rng.randint(1000, 9999)}",
                install_date=self.now - timedelta(days=self.rng.randint(900, 5000)),
                last_maintenance=self.now - timedelta(days=self.rng.randint(20, 400)),
            )
            self.assets.append(asset)
            self._by_name[name] = asset

    def asset_by_name(self, name: str) -> Asset:
        return self._by_name[name]

    def assets_in(self, *, site: str | None = None, unit: str | None = None) -> list[Asset]:
        return [
            a
            for a in self.assets
            if (site is None or a.site == site) and (unit is None or a.unit == unit)
        ]

    # -- alarm construction -------------------------------------------------- #

    def _make_alarm(
        self,
        asset: Asset,
        alarm_name: str,
        start: datetime,
        *,
        severity: str,
        status: str,
        ack_delay_seconds: int | None = None,
        duration_minutes: int | None = None,
    ) -> Alarm:
        ack_time: datetime | None = None
        end_time: datetime | None = None

        if status != "active":
            if ack_delay_seconds is None:
                ack_delay_seconds = self.rng.randint(20, 1800)
            ack_time = start + timedelta(seconds=ack_delay_seconds)
        else:
            # An active alarm has not been acknowledged, so it has no delay yet.
            ack_delay_seconds = None

        if status == "cleared":
            duration = duration_minutes or self.rng.randint(5, 240)
            end_time = start + timedelta(minutes=duration)

        setpoint = round(self.rng.uniform(40, 120), 1)
        return Alarm(
            alarm_id=self.ids.alarm(),
            asset_id=asset.asset_id,
            alarm_name=alarm_name,
            alarm_type=_alarm_type(alarm_name),
            severity=severity,
            status=status,
            start_time=start,
            end_time=end_time,
            ack_time=ack_time,
            ack_delay_seconds=ack_delay_seconds,
            value=round(setpoint * self.rng.uniform(1.05, 1.6), 1),
            setpoint=setpoint,
            unit_of_measure=_unit_of_measure(alarm_name),
            operator_id=None if status == "active" else f"OP-{self.rng.randint(1, 12):03d}",
        )

    def _random_time(self, days_back_max: int | None = None) -> datetime:
        span = days_back_max or self.settings.alarm_sim_days
        seconds = self.rng.randint(0, span * 24 * 3600)
        return self.now - timedelta(seconds=seconds)

    # -- engineered patterns ------------------------------------------------- #

    def _seed_bfp101_recurring_pair(self) -> None:
        """The acceptance scenario.

        Roughly 30 co-occurrences of two alarms inside the correlation lag window,
        spread across the last 90 days, all high or critical. This is what makes
        summary, correlation, and rationalization each return a real finding for
        Boiler Feed Pump 101.
        """
        asset = self.asset_by_name("Boiler Feed Pump 101")
        primary, secondary = BFP101_PAIR

        for i in range(30):
            # Spread across 88 days so everything lands inside a 90-day query.
            offset_days = 88 - (i * 88 / 30)
            start = self.now - timedelta(days=offset_days, hours=self.rng.randint(0, 23))
            severity = "critical" if i % 5 == 0 else "high"

            self.alarms.append(
                self._make_alarm(
                    asset, primary, start, severity=severity, status="cleared",
                    ack_delay_seconds=self.rng.randint(240, 1500),
                )
            )
            # The partner alarm follows within the 15-minute lag window, which is
            # what makes the co-occurrence detectable rather than coincidental.
            follow = start + timedelta(minutes=self.rng.randint(2, 12))
            self.alarms.append(
                self._make_alarm(
                    asset, secondary, follow, severity="high", status="cleared",
                    ack_delay_seconds=self.rng.randint(300, 1800),
                )
            )

        # A few unrelated alarms so the pair stands out against a background
        # rather than being the only thing present.
        for _ in range(8):
            self.alarms.append(
                self._make_alarm(
                    asset,
                    self.rng.choice(["Bearing Temperature High", "Vibration High"]),
                    self._random_time(85),
                    severity=self.rng.choice(["medium", "high"]),
                    status="cleared",
                )
            )

        # One live alarm so the asset has something currently open.
        self.alarms.append(
            self._make_alarm(
                asset, primary, self.now - timedelta(hours=3), severity="high", status="active"
            )
        )

    def _seed_flood_bursts(self) -> None:
        """Bursts in NorthPlant Unit 2 that exceed the flood threshold."""
        unit_assets = self.assets_in(site="NorthPlant", unit="Unit 2")
        for burst in range(4):
            burst_start = self.now - timedelta(days=10 + burst * 18, hours=self.rng.randint(0, 20))
            count = self.rng.randint(16, 26)
            for _ in range(count):
                asset = self.rng.choice(unit_assets)
                names = ALARM_NAMES[asset.asset_type]
                # Squeeze the whole burst inside an 8-minute span so a 10-minute
                # rolling window definitely contains more than the threshold.
                start = burst_start + timedelta(seconds=self.rng.randint(0, 8 * 60))
                self.alarms.append(
                    self._make_alarm(
                        asset,
                        self.rng.choice(names),
                        start,
                        severity=self.rng.choices(
                            ["medium", "high", "critical"], weights=[3, 4, 2]
                        )[0],
                        status="cleared",
                        ack_delay_seconds=self.rng.randint(600, 3600),
                    )
                )

    def _seed_stale_alarms(self) -> None:
        """Active alarms open far longer than the stale threshold."""
        for asset in self.assets_in(site="NorthPlant", unit="Unit 1"):
            for _ in range(self.rng.randint(2, 4)):
                start = self.now - timedelta(hours=self.rng.randint(6, 96))
                self.alarms.append(
                    self._make_alarm(
                        asset,
                        self.rng.choice(ALARM_NAMES[asset.asset_type]),
                        start,
                        severity=self.rng.choice(["medium", "high"]),
                        status="active",
                    )
                )

    def _seed_east_refinery_active(self) -> None:
        """Live alarms at EastRefinery — CHAIN-09 asserts this is non-empty."""
        for asset in self.assets_in(site="EastRefinery"):
            for _ in range(self.rng.randint(2, 4)):
                start = self.now - timedelta(hours=self.rng.randint(1, 72))
                self.alarms.append(
                    self._make_alarm(
                        asset,
                        self.rng.choice(ALARM_NAMES[asset.asset_type]),
                        start,
                        severity=self.rng.choices(
                            ["medium", "high", "critical"], weights=[2, 4, 2]
                        )[0],
                        status="active",
                    )
                )

    def _seed_nuisance_repetition(self) -> None:
        """One alarm name repeating well past the nuisance threshold."""
        for asset in self.assets_in(site="SouthPlant", unit="Unit 4"):
            nuisance = ALARM_NAMES[asset.asset_type][0]
            for _ in range(self.rng.randint(12, 20)):
                self.alarms.append(
                    self._make_alarm(
                        asset,
                        nuisance,
                        self._random_time(90),
                        severity=self.rng.choice(["low", "medium"]),
                        status="cleared",
                        ack_delay_seconds=self.rng.randint(15, 180),
                    )
                )

    def _seed_response_efficiency_spread(self) -> None:
        """A wide spread of acknowledgement delays across SouthPlant."""
        for asset in self.assets_in(site="SouthPlant"):
            for _ in range(self.rng.randint(6, 12)):
                # Bimodal: mostly prompt, occasionally very slow. A single uniform
                # distribution would make the efficiency KPI uninteresting.
                delay = (
                    self.rng.randint(10, 120)
                    if self.rng.random() < 0.7
                    else self.rng.randint(1800, 10800)
                )
                self.alarms.append(
                    self._make_alarm(
                        asset,
                        self.rng.choice(ALARM_NAMES[asset.asset_type]),
                        self._random_time(90),
                        severity=self.rng.choice(["low", "medium", "high"]),
                        status="cleared",
                        ack_delay_seconds=delay,
                    )
                )

    def _seed_background(self, target_total: int) -> None:
        """Fill the remainder with ordinary traffic across the whole estate."""
        while len(self.alarms) < target_total:
            asset = self.rng.choice(self.assets)
            status = self.rng.choices(
                ["cleared", "acknowledged", "active"], weights=[80, 15, 5]
            )[0]
            self.alarms.append(
                self._make_alarm(
                    asset,
                    self.rng.choice(ALARM_NAMES[asset.asset_type]),
                    self._random_time(),
                    severity=self.rng.choices(
                        ["low", "medium", "high", "critical"], weights=[35, 35, 22, 8]
                    )[0],
                    status=status,
                )
            )

    # -- entry point --------------------------------------------------------- #

    def generate(self) -> tuple[list[Asset], list[Alarm]]:
        self._build_assets()
        self._seed_bfp101_recurring_pair()
        self._seed_flood_bursts()
        self._seed_stale_alarms()
        self._seed_east_refinery_active()
        self._seed_nuisance_repetition()
        self._seed_response_efficiency_spread()
        self._seed_background(self.settings.alarm_sim_alarm_count)
        return self.assets, self.alarms


def seed_database(session: Session, settings: Settings, now: datetime | None = None) -> None:
    """Populate an empty database. No-op if assets already exist."""
    if session.query(Asset).first() is not None:
        return

    assets, alarms = SeedGenerator(settings, now=now).generate()
    session.add_all(assets)
    session.add_all(alarms)
    session.commit()
