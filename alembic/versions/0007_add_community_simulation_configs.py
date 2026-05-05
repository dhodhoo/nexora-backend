"""add community simulation configs

Revision ID: 0007_comm_sim_cfg
Revises: 0006_add_building_configs
Create Date: 2026-05-05
"""

from alembic import op
import sqlalchemy as sa


revision = "0007_comm_sim_cfg"
down_revision = "0006_add_building_configs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "community_simulation_configs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("community_id", sa.String(length=32), nullable=False),
        sa.Column("simulation_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_community_simulation_configs_id"), "community_simulation_configs", ["id"], unique=False)
    op.create_index(op.f("ix_community_simulation_configs_community_id"), "community_simulation_configs", ["community_id"], unique=True)
    op.create_index(op.f("ix_community_simulation_configs_simulation_enabled"), "community_simulation_configs", ["simulation_enabled"], unique=False)
    op.create_index(op.f("ix_community_simulation_configs_updated_at"), "community_simulation_configs", ["updated_at"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_community_simulation_configs_updated_at"), table_name="community_simulation_configs")
    op.drop_index(op.f("ix_community_simulation_configs_simulation_enabled"), table_name="community_simulation_configs")
    op.drop_index(op.f("ix_community_simulation_configs_community_id"), table_name="community_simulation_configs")
    op.drop_index(op.f("ix_community_simulation_configs_id"), table_name="community_simulation_configs")
    op.drop_table("community_simulation_configs")
