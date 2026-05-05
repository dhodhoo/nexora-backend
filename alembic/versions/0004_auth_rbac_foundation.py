"""auth and rbac foundation

Revision ID: 0004_auth_rbac_foundation
Revises: 0003_add_ai_result_source
Create Date: 2026-05-05
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0004_auth_rbac_foundation"
down_revision: Union[str, None] = "0003_add_ai_result_source"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


user_role_enum = postgresql.ENUM("ROLE_ADMIN", "ROLE_COORDINATOR", "ROLE_BUILDING_MANAGER", "ROLE_RESIDENT", name="user_role", create_type=True)
user_status_enum = postgresql.ENUM("ACTIVE", "INACTIVE", "PENDING", "DELETED", name="user_status", create_type=True)
user_role_enum_inline = postgresql.ENUM("ROLE_ADMIN", "ROLE_COORDINATOR", "ROLE_BUILDING_MANAGER", "ROLE_RESIDENT", name="user_role", create_type=False)
user_status_enum_inline = postgresql.ENUM("ACTIVE", "INACTIVE", "PENDING", "DELETED", name="user_status", create_type=False)


def upgrade() -> None:
    bind = op.get_bind()
    user_role_enum.create(bind, checkfirst=True)
    user_status_enum.create(bind, checkfirst=True)

    op.create_table(
        "buildings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("building_id", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=True),
    )
    op.create_index("ix_buildings_building_id", "buildings", ["building_id"], unique=True)

    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("full_name", sa.String(length=128), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role", user_role_enum_inline, nullable=False),
        sa.Column("status", user_status_enum_inline, nullable=False),
        sa.Column("community_id", sa.String(length=32), nullable=True),
        sa.Column("building_id", sa.String(length=32), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_users_user_id", "users", ["user_id"], unique=True)
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_index("ix_users_role", "users", ["role"], unique=False)
    op.create_index("ix_users_status", "users", ["status"], unique=False)
    op.create_index("ix_users_community_id", "users", ["community_id"], unique=False)
    op.create_index("ix_users_building_id", "users", ["building_id"], unique=False)

    op.create_table(
        "revoked_tokens",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("jti", sa.String(length=128), nullable=False),
        sa.Column("token_type", sa.String(length=16), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_revoked_tokens_jti", "revoked_tokens", ["jti"], unique=True)
    op.create_index("ix_revoked_tokens_token_type", "revoked_tokens", ["token_type"], unique=False)
    op.create_index("ix_revoked_tokens_expires_at", "revoked_tokens", ["expires_at"], unique=False)

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("log_id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=True),
        sa.Column("role", sa.String(length=32), nullable=True),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("resource", sa.String(length=255), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_audit_logs_log_id", "audit_logs", ["log_id"], unique=True)
    op.create_index("ix_audit_logs_user_id", "audit_logs", ["user_id"], unique=False)
    op.create_index("ix_audit_logs_action", "audit_logs", ["action"], unique=False)
    op.create_index("ix_audit_logs_created_at", "audit_logs", ["created_at"], unique=False)

    op.add_column("energy_readings", sa.Column("is_simulation", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.create_index("ix_energy_readings_is_simulation", "energy_readings", ["is_simulation"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_energy_readings_is_simulation", table_name="energy_readings")
    op.drop_column("energy_readings", "is_simulation")

    op.drop_index("ix_audit_logs_created_at", table_name="audit_logs")
    op.drop_index("ix_audit_logs_action", table_name="audit_logs")
    op.drop_index("ix_audit_logs_user_id", table_name="audit_logs")
    op.drop_index("ix_audit_logs_log_id", table_name="audit_logs")
    op.drop_table("audit_logs")

    op.drop_index("ix_revoked_tokens_expires_at", table_name="revoked_tokens")
    op.drop_index("ix_revoked_tokens_token_type", table_name="revoked_tokens")
    op.drop_index("ix_revoked_tokens_jti", table_name="revoked_tokens")
    op.drop_table("revoked_tokens")

    op.drop_index("ix_users_building_id", table_name="users")
    op.drop_index("ix_users_community_id", table_name="users")
    op.drop_index("ix_users_status", table_name="users")
    op.drop_index("ix_users_role", table_name="users")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_index("ix_users_user_id", table_name="users")
    op.drop_table("users")

    op.drop_index("ix_buildings_building_id", table_name="buildings")
    op.drop_table("buildings")

    bind = op.get_bind()
    user_status_enum.drop(bind, checkfirst=True)
    user_role_enum.drop(bind, checkfirst=True)
