"""add qty column to devices

Revision ID: 0009_add_device_qty
Revises: 0008_full_backend
Create Date: 2026-05-05
"""

from alembic import op
import sqlalchemy as sa


revision = "0009_add_device_qty"
down_revision = "0008_full_backend"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("devices", sa.Column("qty", sa.Integer(), nullable=False, server_default="1"))
    op.create_check_constraint("ck_devices_qty_positive", "devices", "qty >= 1")
    op.alter_column("devices", "qty", server_default=None)


def downgrade() -> None:
    op.drop_constraint("ck_devices_qty_positive", "devices", type_="check")
    op.drop_column("devices", "qty")
