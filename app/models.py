from datetime import datetime
from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.utils.time import utc_now


class Unit(Base):
    __tablename__ = "units"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    community_id: Mapped[str] = mapped_column(String(32), index=True)
    unit_id: Mapped[str] = mapped_column(String(32), index=True)
    va: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (UniqueConstraint("community_id", "unit_id", name="uq_unit_community_unit"),)


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    unit_id: Mapped[int] = mapped_column(ForeignKey("units.id"), index=True)
    device_id: Mapped[str] = mapped_column(String(64), index=True)
    controllable: Mapped[bool] = mapped_column(Boolean, default=False)
    schedules: Mapped[list] = mapped_column(JSON, nullable=True)

    __table_args__ = (UniqueConstraint("unit_id", "device_id", name="uq_device_unit_device"),)


class DeviceStateHistory(Base):
    __tablename__ = "device_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_pk: Mapped[int] = mapped_column(ForeignKey("devices.id"), index=True)
    controllable: Mapped[bool] = mapped_column(Boolean)
    schedules: Mapped[list] = mapped_column(JSON, nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, index=True)


class TariffLookupByVA(Base):
    __tablename__ = "tariff_lookup_by_va"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    va: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    tariff_per_kwh: Mapped[float] = mapped_column(Float, nullable=False)


class EnergyReading(Base):
    __tablename__ = "energy_readings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    community_id: Mapped[str] = mapped_column(String(32), index=True)
    unit_id: Mapped[str] = mapped_column(String(32), index=True)
    device_id: Mapped[str] = mapped_column(String(64), index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, index=True)
    kwh: Mapped[float] = mapped_column(Float, nullable=False)
    power_watt: Mapped[float] = mapped_column(Float, nullable=True)
    tariff_per_kwh: Mapped[float] = mapped_column(Float, nullable=False)
    estimated_cost: Mapped[float] = mapped_column(Float, nullable=False)
    raw_payload: Mapped[dict] = mapped_column(JSON)

    __table_args__ = (UniqueConstraint("community_id", "unit_id", "device_id", "timestamp", name="uq_reading_idempotent"),)


class DeadLetter(Base):
    __tablename__ = "dead_letters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    topic: Mapped[str] = mapped_column(String(255), index=True)
    reason: Mapped[str] = mapped_column(String(255))
    raw_payload: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, index=True)


class AIAnalysisResult(Base):
    __tablename__ = "ai_analysis_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    community_id: Mapped[str] = mapped_column(String(64), index=True)
    analyzed_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, index=True)
    status: Mapped[str] = mapped_column(String(16), index=True)
    stale: Mapped[bool] = mapped_column(Boolean, default=False)
    payload: Mapped[dict] = mapped_column(JSON)
    result: Mapped[dict] = mapped_column(JSON)
    error: Mapped[str] = mapped_column(String, default="")
