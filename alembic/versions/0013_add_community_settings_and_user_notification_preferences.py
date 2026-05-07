"""add community settings and user notification preferences

Revision ID: 0013_comm_settings_notif_prefs
Revises: 0012_add_device_schedule_source
Create Date: 2026-05-07 11:30:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0013_comm_settings_notif_prefs"
down_revision: Union[str, None] = "0012_add_device_schedule_source"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "community_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("community_id", sa.String(length=32), nullable=False),
        sa.Column("tariff", sa.Float(), nullable=False, server_default="1444.7"),
        sa.Column("emission_factor", sa.Float(), nullable=False, server_default="0.85"),
        sa.Column("thresholds", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("notification_config", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_community_settings_id"), "community_settings", ["id"], unique=False)
    op.create_index(op.f("ix_community_settings_community_id"), "community_settings", ["community_id"], unique=True)
    op.create_index(op.f("ix_community_settings_created_at"), "community_settings", ["created_at"], unique=False)
    op.create_index(op.f("ix_community_settings_updated_at"), "community_settings", ["updated_at"], unique=False)

    op.create_table(
        "user_notification_preferences",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("preferences", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_user_notification_preferences_id"), "user_notification_preferences", ["id"], unique=False)
    op.create_index(op.f("ix_user_notification_preferences_user_id"), "user_notification_preferences", ["user_id"], unique=True)
    op.create_index(op.f("ix_user_notification_preferences_created_at"), "user_notification_preferences", ["created_at"], unique=False)
    op.create_index(op.f("ix_user_notification_preferences_updated_at"), "user_notification_preferences", ["updated_at"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_user_notification_preferences_updated_at"), table_name="user_notification_preferences")
    op.drop_index(op.f("ix_user_notification_preferences_created_at"), table_name="user_notification_preferences")
    op.drop_index(op.f("ix_user_notification_preferences_user_id"), table_name="user_notification_preferences")
    op.drop_index(op.f("ix_user_notification_preferences_id"), table_name="user_notification_preferences")
    op.drop_table("user_notification_preferences")

    op.drop_index(op.f("ix_community_settings_updated_at"), table_name="community_settings")
    op.drop_index(op.f("ix_community_settings_created_at"), table_name="community_settings")
    op.drop_index(op.f("ix_community_settings_community_id"), table_name="community_settings")
    op.drop_index(op.f("ix_community_settings_id"), table_name="community_settings")
    op.drop_table("community_settings")
