"""add building_id to energy_readings

Revision ID: 0014_building_id_energy_readings
Revises: 0013_comm_settings_notif_prefs
Create Date: 2026-05-07 14:30:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0014_building_id_energy_readings"
down_revision: Union[str, None] = "0013_comm_settings_notif_prefs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("energy_readings", sa.Column("building_id", sa.String(length=32), nullable=True))
    op.create_index("ix_energy_readings_building_id", "energy_readings", ["building_id"], unique=False)

    op.execute(
        """
        UPDATE energy_readings er
        SET building_id = bu.building_id
        FROM (
            SELECT unit_id, MIN(building_id) AS building_id
            FROM building_units
            GROUP BY unit_id
        ) bu
        WHERE er.unit_id = bu.unit_id
          AND er.building_id IS NULL
        """
    )


def downgrade() -> None:
    op.drop_index("ix_energy_readings_building_id", table_name="energy_readings")
    op.drop_column("energy_readings", "building_id")
