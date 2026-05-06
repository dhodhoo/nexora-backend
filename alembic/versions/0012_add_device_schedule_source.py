"""add schedule_source to devices

Revision ID: 0012_add_device_schedule_source
Revises: 0011_add_unit_device_is_active
Create Date: 2026-05-07
"""

from alembic import op
import sqlalchemy as sa


revision = "0012_add_device_schedule_source"
down_revision = "0011_add_unit_device_is_active"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "devices",
        sa.Column("schedule_source", sa.String(length=16), nullable=False, server_default="mqtt"),
    )
    op.create_index("ix_devices_schedule_source", "devices", ["schedule_source"], unique=False)
    op.alter_column("devices", "schedule_source", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_devices_schedule_source", table_name="devices")
    op.drop_column("devices", "schedule_source")

