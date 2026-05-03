"""baseline

Revision ID: 0001_baseline
Revises:
Create Date: 2026-05-03
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0001_baseline"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "units",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("community_id", sa.String(length=32), nullable=False),
        sa.Column("unit_id", sa.String(length=32), nullable=False),
        sa.Column("va", sa.Integer(), nullable=False),
        sa.UniqueConstraint("community_id", "unit_id", name="uq_unit_community_unit"),
    )
    op.create_index("ix_units_id", "units", ["id"])
    op.create_index("ix_units_community_id", "units", ["community_id"])
    op.create_index("ix_units_unit_id", "units", ["unit_id"])

    op.create_table(
        "devices",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("unit_id", sa.Integer(), sa.ForeignKey("units.id"), nullable=False),
        sa.Column("device_id", sa.String(length=64), nullable=False),
        sa.Column("controllable", sa.Boolean(), nullable=False),
        sa.Column("schedules", sa.JSON(), nullable=True),
        sa.UniqueConstraint("unit_id", "device_id", name="uq_device_unit_device"),
    )
    op.create_index("ix_devices_unit_id", "devices", ["unit_id"])
    op.create_index("ix_devices_device_id", "devices", ["device_id"])

    op.create_table(
        "device_state",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("device_pk", sa.Integer(), sa.ForeignKey("devices.id"), nullable=False),
        sa.Column("controllable", sa.Boolean(), nullable=False),
        sa.Column("schedules", sa.JSON(), nullable=True),
        sa.Column("recorded_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_device_state_device_pk", "device_state", ["device_pk"])
    op.create_index("ix_device_state_recorded_at", "device_state", ["recorded_at"])

    op.create_table(
        "tariff_lookup_by_va",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("va", sa.Integer(), nullable=False),
        sa.Column("tariff_per_kwh", sa.Float(), nullable=False),
        sa.UniqueConstraint("va"),
    )
    op.create_index("ix_tariff_lookup_by_va_va", "tariff_lookup_by_va", ["va"])

    op.create_table(
        "energy_readings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("community_id", sa.String(length=32), nullable=False),
        sa.Column("unit_id", sa.String(length=32), nullable=False),
        sa.Column("device_id", sa.String(length=64), nullable=False),
        sa.Column("timestamp", sa.DateTime(), nullable=False),
        sa.Column("kwh", sa.Float(), nullable=False),
        sa.Column("power_watt", sa.Float(), nullable=True),
        sa.Column("tariff_per_kwh", sa.Float(), nullable=False),
        sa.Column("estimated_cost", sa.Float(), nullable=False),
        sa.Column("raw_payload", sa.JSON(), nullable=False),
        sa.UniqueConstraint("community_id", "unit_id", "device_id", "timestamp", name="uq_reading_idempotent"),
    )
    op.create_index("ix_energy_readings_community_id", "energy_readings", ["community_id"])
    op.create_index("ix_energy_readings_unit_id", "energy_readings", ["unit_id"])
    op.create_index("ix_energy_readings_device_id", "energy_readings", ["device_id"])
    op.create_index("ix_energy_readings_timestamp", "energy_readings", ["timestamp"])

    op.create_table(
        "dead_letters",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("topic", sa.String(length=255), nullable=False),
        sa.Column("reason", sa.String(length=255), nullable=False),
        sa.Column("raw_payload", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_dead_letters_topic", "dead_letters", ["topic"])
    op.create_index("ix_dead_letters_created_at", "dead_letters", ["created_at"])

    op.create_table(
        "ai_analysis_results",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("community_id", sa.String(length=64), nullable=False),
        sa.Column("analyzed_at", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("stale", sa.Boolean(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("error", sa.String(), nullable=False),
    )
    op.create_index("ix_ai_analysis_results_community_id", "ai_analysis_results", ["community_id"])
    op.create_index("ix_ai_analysis_results_analyzed_at", "ai_analysis_results", ["analyzed_at"])
    op.create_index("ix_ai_analysis_results_status", "ai_analysis_results", ["status"])


def downgrade() -> None:
    op.drop_index("ix_ai_analysis_results_status", table_name="ai_analysis_results")
    op.drop_index("ix_ai_analysis_results_analyzed_at", table_name="ai_analysis_results")
    op.drop_index("ix_ai_analysis_results_community_id", table_name="ai_analysis_results")
    op.drop_table("ai_analysis_results")

    op.drop_index("ix_dead_letters_created_at", table_name="dead_letters")
    op.drop_index("ix_dead_letters_topic", table_name="dead_letters")
    op.drop_table("dead_letters")

    op.drop_index("ix_energy_readings_timestamp", table_name="energy_readings")
    op.drop_index("ix_energy_readings_device_id", table_name="energy_readings")
    op.drop_index("ix_energy_readings_unit_id", table_name="energy_readings")
    op.drop_index("ix_energy_readings_community_id", table_name="energy_readings")
    op.drop_table("energy_readings")

    op.drop_index("ix_tariff_lookup_by_va_va", table_name="tariff_lookup_by_va")
    op.drop_table("tariff_lookup_by_va")

    op.drop_index("ix_device_state_recorded_at", table_name="device_state")
    op.drop_index("ix_device_state_device_pk", table_name="device_state")
    op.drop_table("device_state")

    op.drop_index("ix_devices_device_id", table_name="devices")
    op.drop_index("ix_devices_unit_id", table_name="devices")
    op.drop_table("devices")

    op.drop_index("ix_units_unit_id", table_name="units")
    op.drop_index("ix_units_community_id", table_name="units")
    op.drop_index("ix_units_id", table_name="units")
    op.drop_table("units")