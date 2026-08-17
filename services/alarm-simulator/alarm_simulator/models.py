"""SQLAlchemy ORM models — the simulator's persistence layer.

Three tables. Every query in this service goes through the ORM with bound
parameters; no SQL is ever built by string concatenation. "Unsafe SQL" is listed
as a red flag in the submission guidelines, and the ORM makes the safe path the
only path.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Declarative base for every simulator table."""


class Asset(Base):
    """A physical item of plant equipment.

    ``asset_id`` is the natural key used throughout the API and is the value the
    Postman collections chain into every downstream request.
    """

    __tablename__ = "assets"

    asset_id: Mapped[str] = mapped_column(String(16), primary_key=True)
    asset_name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    asset_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    unit: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    site: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    criticality: Mapped[str] = mapped_column(String(16), nullable=False)
    manufacturer: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(64), nullable=False)
    install_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_maintenance: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    alarms: Mapped[list[Alarm]] = relationship(back_populates="asset")

    # Asset search matches on name and type together, so index the pair.
    __table_args__ = (Index("ix_assets_search", "asset_name", "asset_type"),)


class Alarm(Base):
    """A single abnormal-condition event on an asset."""

    __tablename__ = "alarms"

    alarm_id: Mapped[str] = mapped_column(String(16), primary_key=True)
    asset_id: Mapped[str] = mapped_column(
        String(16), ForeignKey("assets.asset_id"), nullable=False, index=True
    )
    alarm_name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    alarm_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, index=True)

    start_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    end_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ack_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Denormalised so acknowledgement-delay KPIs do not recompute a difference
    # per row on every summary request.
    ack_delay_seconds: Mapped[int | None] = mapped_column(Integer)

    value: Mapped[float | None] = mapped_column(Float)
    setpoint: Mapped[float | None] = mapped_column(Float)
    unit_of_measure: Mapped[str | None] = mapped_column(String(16))
    operator_id: Mapped[str | None] = mapped_column(String(32))

    asset: Mapped[Asset] = relationship(back_populates="alarms")

    __table_args__ = (
        # The dominant access pattern: alarms for an asset within a time window,
        # newest first.
        Index("ix_alarms_asset_time", "asset_id", "start_time"),
        # Flood analysis and correlation scan a window across a whole unit.
        Index("ix_alarms_time_severity", "start_time", "severity"),
    )


class Calculation(Base):
    """A generated KPI calculation.

    The API models calculation as two steps — generate, then execute — because the
    second is impossible without the identifier the first returns. That makes it the
    cleanest demonstration of tool chaining in the whole surface, so the generated
    code string is stored for display even though execution runs real logic.
    """

    __tablename__ = "calculations"

    calculation_id: Mapped[str] = mapped_column(String(24), primary_key=True)
    calculation_type: Mapped[str] = mapped_column(String(64), nullable=False)
    generated_code: Mapped[str] = mapped_column(Text, nullable=False)
    filters_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
