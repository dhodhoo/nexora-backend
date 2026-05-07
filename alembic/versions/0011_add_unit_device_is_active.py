"""add is_active to unit devices

Revision ID: 0011_add_unit_device_is_active
Revises: 0010_add_notification_reads
Create Date: 2026-05-06
"""

from alembic import op
import sqlalchemy as sa


revision = "0011_add_unit_device_is_active"
down_revision = "0010_add_notification_reads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("devices", sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.create_index("ix_devices_is_active", "devices", ["is_active"], unique=False)
    op.alter_column("devices", "is_active", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_devices_is_active", table_name="devices")
    op.drop_column("devices", "is_active")

