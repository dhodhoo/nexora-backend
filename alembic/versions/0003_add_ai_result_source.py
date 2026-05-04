"""add source field to ai_analysis_results

Revision ID: 0003_add_ai_result_source
Revises: 0002_add_communities
Create Date: 2026-05-04
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0003_add_ai_result_source"
down_revision: Union[str, None] = "0002_add_communities"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("ai_analysis_results", sa.Column("source", sa.String(length=16), nullable=True))
    op.execute("UPDATE ai_analysis_results SET source = 'unknown' WHERE source IS NULL")
    op.alter_column("ai_analysis_results", "source", nullable=False)
    op.create_index("ix_ai_analysis_results_source", "ai_analysis_results", ["source"])


def downgrade() -> None:
    op.drop_index("ix_ai_analysis_results_source", table_name="ai_analysis_results")
    op.drop_column("ai_analysis_results", "source")
