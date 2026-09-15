"""Add canonical_id to people table for entity disambiguation.

Revision ID: 003_entity_aliases
Revises: 002_multi_tenant_isolation
Create Date: 2026-09-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "003_entity_aliases"
down_revision: str | None = "002_multi_tenant_isolation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "people",
        sa.Column("canonical_id", sa.String(length=128), nullable=False, server_default=""),
    )
    op.create_index(
        "people_canonical_idx",
        "people",
        ["canonical_id"],
    )


def downgrade() -> None:
    op.drop_index("people_canonical_idx", table_name="people")
    op.drop_column("people", "canonical_id")
