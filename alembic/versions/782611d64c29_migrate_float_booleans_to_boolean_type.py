"""migrate float booleans to boolean type

Revision ID: 782611d64c29
Revises: bacf5c53e137
Create Date: 2026-07-22 02:33:02.623791

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = "782611d64c29"
down_revision: Union[str, Sequence[str], None] = "bacf5c53e137"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Tables and columns that were previously Float but now Boolean.
# Maps table_name -> list of column names.
_BOOLEAN_COLUMNS: dict[str, list[str]] = {
    "geofences": ["alert_on_enter", "alert_on_exit"],
    "webhooks": ["active"],
    "alerts": ["acknowledged"],
    "api_keys": ["active"],
    "alert_rules": ["enabled"],
}


def _columns_to_migrate(table: str, columns: list[str]) -> list[str]:
    """Return subset of columns that are still Float and need migration."""
    bind = op.get_bind()
    inspector = inspect(bind)
    current_types = {c["name"]: c["type"] for c in inspector.get_columns(table)}
    return [c for c in columns if c in current_types and isinstance(current_types[c], sa.Float)]


def upgrade() -> None:
    """Normalize existing float booleans, then alter columns to Boolean."""
    for table, columns in _BOOLEAN_COLUMNS.items():
        to_migrate = _columns_to_migrate(table, columns)
        if not to_migrate:
            continue

        # Normalize: anything non-zero → 1, zero → 0
        for column in to_migrate:
            op.execute(
                f"UPDATE {table} SET {column} = CASE WHEN {column} = 0.0 THEN 0 ELSE 1 END"
            )

        # SQLite batch mode recreates the table when type changes are required.
        with op.batch_alter_table(table, schema=None) as batch_op:
            for column in to_migrate:
                batch_op.alter_column(
                    column,
                    existing_type=sa.Float(),
                    type_=sa.Boolean(),
                    existing_nullable=True,
                )


def downgrade() -> None:
    """Convert Boolean columns back to Float."""
    for table, columns in _BOOLEAN_COLUMNS.items():
        with op.batch_alter_table(table, schema=None) as batch_op:
            for column in columns:
                batch_op.alter_column(
                    column,
                    existing_type=sa.Boolean(),
                    type_=sa.Float(),
                    existing_nullable=True,
                )
