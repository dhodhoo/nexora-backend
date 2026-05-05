"""add building_configs

Revision ID: 0006_add_building_configs
Revises: 0005_add_building_units
Create Date: 2026-05-05
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0006_add_building_configs"
down_revision: Union[str, None] = "0005_add_building_units"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "building_configs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("building_id", sa.String(length=32), nullable=False),
        sa.Column("peak_threshold_kwh", sa.Float(), nullable=False, server_default=sa.text("3.0")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_building_configs_id", "building_configs", ["id"], unique=False)
    op.create_index("ix_building_configs_building_id", "building_configs", ["building_id"], unique=True)
    op.create_index("ix_building_configs_created_at", "building_configs", ["created_at"], unique=False)
    op.create_index("ix_building_configs_updated_at", "building_configs", ["updated_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_building_configs_updated_at", table_name="building_configs")
    op.drop_index("ix_building_configs_created_at", table_name="building_configs")
    op.drop_index("ix_building_configs_building_id", table_name="building_configs")
    op.drop_index("ix_building_configs_id", table_name="building_configs")
    op.drop_table("building_configs")
