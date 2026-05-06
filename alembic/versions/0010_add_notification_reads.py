"""add notification reads table

Revision ID: 0010_add_notification_reads
Revises: 0009_add_device_qty
Create Date: 2026-05-06
"""

from alembic import op
import sqlalchemy as sa


revision = "0010_add_notification_reads"
down_revision = "0009_add_device_qty"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "notification_reads",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("notification_id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("read_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("notification_id", "user_id", name="uq_notification_read_user"),
    )
    op.create_index(op.f("ix_notification_reads_id"), "notification_reads", ["id"], unique=False)
    op.create_index(op.f("ix_notification_reads_notification_id"), "notification_reads", ["notification_id"], unique=False)
    op.create_index(op.f("ix_notification_reads_user_id"), "notification_reads", ["user_id"], unique=False)
    op.create_index(op.f("ix_notification_reads_read_at"), "notification_reads", ["read_at"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_notification_reads_read_at"), table_name="notification_reads")
    op.drop_index(op.f("ix_notification_reads_user_id"), table_name="notification_reads")
    op.drop_index(op.f("ix_notification_reads_notification_id"), table_name="notification_reads")
    op.drop_index(op.f("ix_notification_reads_id"), table_name="notification_reads")
    op.drop_table("notification_reads")

