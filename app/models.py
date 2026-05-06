from datetime import datetime
from typing import Optional
import enum
from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint, Enum
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.utils.time import utc_now


class Community(Base):
    __tablename__ = "communities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    community_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)


class Building(Base):
    __tablename__ = "buildings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    building_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)


class BuildingUnit(Base):
    __tablename__ = "building_units"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    building_id: Mapped[str] = mapped_column(String(32), index=True)
    unit_id: Mapped[str] = mapped_column(String(32), index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now, index=True)

    __table_args__ = (UniqueConstraint("building_id", "unit_id", name="uq_building_unit"),)


class BuildingConfig(Base):
    __tablename__ = "building_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    building_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    peak_threshold_kwh: Mapped[float] = mapped_column(Float, nullable=False, default=3.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now, index=True)


class CommunitySimulationConfig(Base):
    __tablename__ = "community_simulation_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    community_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    simulation_enabled: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now, index=True)


class UserRole(str, enum.Enum):
    ADMIN = "ROLE_ADMIN"
    COORDINATOR = "ROLE_COORDINATOR"
    BUILDING_MANAGER = "ROLE_BUILDING_MANAGER"
    RESIDENT = "ROLE_RESIDENT"


class UserStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    PENDING = "PENDING"
    DELETED = "DELETED"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(128))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="user_role", values_callable=lambda x: [e.value for e in x], validate_strings=True),
        index=True,
    )
    status: Mapped[UserStatus] = mapped_column(Enum(UserStatus, name="user_status"), index=True, default=UserStatus.PENDING)
    community_id: Mapped[Optional[str]] = mapped_column(String(32), nullable=True, index=True)
    building_id: Mapped[Optional[str]] = mapped_column(String(32), nullable=True, index=True)
    unit_id: Mapped[Optional[str]] = mapped_column(String(32), nullable=True, index=True)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now, index=True)


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
    qty: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    controllable: Mapped[bool] = mapped_column(Boolean, default=False)
    schedules: Mapped[list] = mapped_column(JSON, nullable=True)

    __table_args__ = (UniqueConstraint("unit_id", "device_id", name="uq_device_unit_device"),)


class DeviceCatalog(Base):
    __tablename__ = "device_catalog"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    device_key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(128))
    default_power_watt: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    controllable: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now, index=True)


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
    is_simulation: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
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
    source: Mapped[str] = mapped_column(String(16), default="unknown", index=True)
    payload: Mapped[dict] = mapped_column(JSON)
    result: Mapped[dict] = mapped_column(JSON)
    error: Mapped[str] = mapped_column(String, default="")


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    notification_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    scope: Mapped[str] = mapped_column(String(16), index=True)  # community|building
    community_id: Mapped[Optional[str]] = mapped_column(String(32), nullable=True, index=True)
    building_id: Mapped[Optional[str]] = mapped_column(String(32), nullable=True, index=True)
    message: Mapped[str] = mapped_column(String)
    created_by_user_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, index=True)


class NotificationDelivery(Base):
    __tablename__ = "notification_deliveries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    notification_id: Mapped[str] = mapped_column(String(64), index=True)
    target_type: Mapped[str] = mapped_column(String(16), index=True)  # user|scope
    target_id: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(16), index=True, default="queued")
    delivered_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, index=True)
    error: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, index=True)


class NotificationRead(Base):
    __tablename__ = "notification_reads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    notification_id: Mapped[str] = mapped_column(String(64), index=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    read_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, index=True)

    __table_args__ = (UniqueConstraint("notification_id", "user_id", name="uq_notification_read_user"),)


class DeviceCommand(Base):
    __tablename__ = "device_commands"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    command_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    community_id: Mapped[str] = mapped_column(String(32), index=True)
    unit_id: Mapped[str] = mapped_column(String(32), index=True)
    device_id: Mapped[str] = mapped_column(String(64), index=True)
    action: Mapped[str] = mapped_column(String(8))  # on|off
    topic: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(16), index=True, default="sent")
    error: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_by_user_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, index=True)


class RevokedToken(Base):
    __tablename__ = "revoked_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    jti: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    token_type: Mapped[str] = mapped_column(String(16), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, index=True)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    log_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[Optional[str]] = mapped_column(String(64), index=True, nullable=True)
    role: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    action: Mapped[str] = mapped_column(String(16), index=True)
    resource: Mapped[str] = mapped_column(String(255))
    payload: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    ip_address: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, index=True)
