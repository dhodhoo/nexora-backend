"""add building_units table

Revision ID: 0005_add_building_units
Revises: 0004_auth_rbac_foundation
Create Date: 2026-05-05
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0005_add_building_units"
down_revision: Union[str, None] = "0004_auth_rbac_foundation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "building_units",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("building_id", sa.String(length=32), nullable=False),
        sa.Column("unit_id", sa.String(length=32), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("building_id", "unit_id", name="uq_building_unit"),
    )
    op.create_index("ix_building_units_id", "building_units", ["id"], unique=False)
    op.create_index("ix_building_units_building_id", "building_units", ["building_id"], unique=False)
    op.create_index("ix_building_units_unit_id", "building_units", ["unit_id"], unique=False)
    op.create_index("ix_building_units_is_active", "building_units", ["is_active"], unique=False)
    op.create_index("ix_building_units_created_at", "building_units", ["created_at"], unique=False)
    op.create_index("ix_building_units_updated_at", "building_units", ["updated_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_building_units_updated_at", table_name="building_units")
    op.drop_index("ix_building_units_created_at", table_name="building_units")
    op.drop_index("ix_building_units_is_active", table_name="building_units")
    op.drop_index("ix_building_units_unit_id", table_name="building_units")
    op.drop_index("ix_building_units_building_id", table_name="building_units")
    op.drop_index("ix_building_units_id", table_name="building_units")
    op.drop_table("building_units")
