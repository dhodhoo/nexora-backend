"""add communities table

Revision ID: 0002_add_communities
Revises: 0001_baseline
Create Date: 2026-05-04
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0002_add_communities"
down_revision: Union[str, None] = "0001_baseline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "communities",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("community_id", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=True),
        sa.UniqueConstraint("community_id"),
    )
    op.create_index("ix_communities_id", "communities", ["id"])
    op.create_index("ix_communities_community_id", "communities", ["community_id"])


def downgrade() -> None:
    op.drop_index("ix_communities_community_id", table_name="communities")
    op.drop_index("ix_communities_id", table_name="communities")
    op.drop_table("communities")
