"""full backend completion tables and users.unit_id

Revision ID: 0008_full_backend
Revises: 0007_comm_sim_cfg
Create Date: 2026-05-05
"""

from alembic import op
import sqlalchemy as sa


revision = "0008_full_backend"
down_revision = "0007_comm_sim_cfg"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("unit_id", sa.String(length=32), nullable=True))
    op.create_index(op.f("ix_users_unit_id"), "users", ["unit_id"], unique=False)

    op.create_table(
        "notifications",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("notification_id", sa.String(length=64), nullable=False),
        sa.Column("scope", sa.String(length=16), nullable=False),
        sa.Column("community_id", sa.String(length=32), nullable=True),
        sa.Column("building_id", sa.String(length=32), nullable=True),
        sa.Column("message", sa.String(), nullable=False),
        sa.Column("created_by_user_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_notifications_id"), "notifications", ["id"], unique=False)
    op.create_index(op.f("ix_notifications_notification_id"), "notifications", ["notification_id"], unique=True)
    op.create_index(op.f("ix_notifications_scope"), "notifications", ["scope"], unique=False)
    op.create_index(op.f("ix_notifications_community_id"), "notifications", ["community_id"], unique=False)
    op.create_index(op.f("ix_notifications_building_id"), "notifications", ["building_id"], unique=False)
    op.create_index(op.f("ix_notifications_created_by_user_id"), "notifications", ["created_by_user_id"], unique=False)
    op.create_index(op.f("ix_notifications_created_at"), "notifications", ["created_at"], unique=False)

    op.create_table(
        "notification_deliveries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("notification_id", sa.String(length=64), nullable=False),
        sa.Column("target_type", sa.String(length=16), nullable=False),
        sa.Column("target_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("delivered_at", sa.DateTime(), nullable=True),
        sa.Column("error", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_notification_deliveries_id"), "notification_deliveries", ["id"], unique=False)
    op.create_index(op.f("ix_notification_deliveries_notification_id"), "notification_deliveries", ["notification_id"], unique=False)
    op.create_index(op.f("ix_notification_deliveries_target_type"), "notification_deliveries", ["target_type"], unique=False)
    op.create_index(op.f("ix_notification_deliveries_target_id"), "notification_deliveries", ["target_id"], unique=False)
    op.create_index(op.f("ix_notification_deliveries_status"), "notification_deliveries", ["status"], unique=False)
    op.create_index(op.f("ix_notification_deliveries_delivered_at"), "notification_deliveries", ["delivered_at"], unique=False)
    op.create_index(op.f("ix_notification_deliveries_created_at"), "notification_deliveries", ["created_at"], unique=False)

    op.create_table(
        "device_commands",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("command_id", sa.String(length=64), nullable=False),
        sa.Column("community_id", sa.String(length=32), nullable=False),
        sa.Column("unit_id", sa.String(length=32), nullable=False),
        sa.Column("device_id", sa.String(length=64), nullable=False),
        sa.Column("action", sa.String(length=8), nullable=False),
        sa.Column("topic", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("error", sa.String(), nullable=True),
        sa.Column("created_by_user_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_device_commands_id"), "device_commands", ["id"], unique=False)
    op.create_index(op.f("ix_device_commands_command_id"), "device_commands", ["command_id"], unique=True)
    op.create_index(op.f("ix_device_commands_community_id"), "device_commands", ["community_id"], unique=False)
    op.create_index(op.f("ix_device_commands_unit_id"), "device_commands", ["unit_id"], unique=False)
    op.create_index(op.f("ix_device_commands_device_id"), "device_commands", ["device_id"], unique=False)
    op.create_index(op.f("ix_device_commands_status"), "device_commands", ["status"], unique=False)
    op.create_index(op.f("ix_device_commands_created_by_user_id"), "device_commands", ["created_by_user_id"], unique=False)
    op.create_index(op.f("ix_device_commands_created_at"), "device_commands", ["created_at"], unique=False)

    op.create_table(
        "device_catalog",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("device_key", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=128), nullable=False),
        sa.Column("default_power_watt", sa.Float(), nullable=True),
        sa.Column("controllable", sa.Boolean(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_device_catalog_id"), "device_catalog", ["id"], unique=False)
    op.create_index(op.f("ix_device_catalog_device_key"), "device_catalog", ["device_key"], unique=True)
    op.create_index(op.f("ix_device_catalog_controllable"), "device_catalog", ["controllable"], unique=False)
    op.create_index(op.f("ix_device_catalog_is_active"), "device_catalog", ["is_active"], unique=False)
    op.create_index(op.f("ix_device_catalog_created_at"), "device_catalog", ["created_at"], unique=False)
    op.create_index(op.f("ix_device_catalog_updated_at"), "device_catalog", ["updated_at"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_device_catalog_updated_at"), table_name="device_catalog")
    op.drop_index(op.f("ix_device_catalog_created_at"), table_name="device_catalog")
    op.drop_index(op.f("ix_device_catalog_is_active"), table_name="device_catalog")
    op.drop_index(op.f("ix_device_catalog_controllable"), table_name="device_catalog")
    op.drop_index(op.f("ix_device_catalog_device_key"), table_name="device_catalog")
    op.drop_index(op.f("ix_device_catalog_id"), table_name="device_catalog")
    op.drop_table("device_catalog")

    op.drop_index(op.f("ix_device_commands_created_at"), table_name="device_commands")
    op.drop_index(op.f("ix_device_commands_created_by_user_id"), table_name="device_commands")
    op.drop_index(op.f("ix_device_commands_status"), table_name="device_commands")
    op.drop_index(op.f("ix_device_commands_device_id"), table_name="device_commands")
    op.drop_index(op.f("ix_device_commands_unit_id"), table_name="device_commands")
    op.drop_index(op.f("ix_device_commands_community_id"), table_name="device_commands")
    op.drop_index(op.f("ix_device_commands_command_id"), table_name="device_commands")
    op.drop_index(op.f("ix_device_commands_id"), table_name="device_commands")
    op.drop_table("device_commands")

    op.drop_index(op.f("ix_notification_deliveries_created_at"), table_name="notification_deliveries")
    op.drop_index(op.f("ix_notification_deliveries_delivered_at"), table_name="notification_deliveries")
    op.drop_index(op.f("ix_notification_deliveries_status"), table_name="notification_deliveries")
    op.drop_index(op.f("ix_notification_deliveries_target_id"), table_name="notification_deliveries")
    op.drop_index(op.f("ix_notification_deliveries_target_type"), table_name="notification_deliveries")
    op.drop_index(op.f("ix_notification_deliveries_notification_id"), table_name="notification_deliveries")
    op.drop_index(op.f("ix_notification_deliveries_id"), table_name="notification_deliveries")
    op.drop_table("notification_deliveries")

    op.drop_index(op.f("ix_notifications_created_at"), table_name="notifications")
    op.drop_index(op.f("ix_notifications_created_by_user_id"), table_name="notifications")
    op.drop_index(op.f("ix_notifications_building_id"), table_name="notifications")
    op.drop_index(op.f("ix_notifications_community_id"), table_name="notifications")
    op.drop_index(op.f("ix_notifications_scope"), table_name="notifications")
    op.drop_index(op.f("ix_notifications_notification_id"), table_name="notifications")
    op.drop_index(op.f("ix_notifications_id"), table_name="notifications")
    op.drop_table("notifications")

    op.drop_index(op.f("ix_users_unit_id"), table_name="users")
    op.drop_column("users", "unit_id")
