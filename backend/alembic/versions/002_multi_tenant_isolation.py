"""Add owner_id to documents for multi-tenant isolation.

Revision ID: 002_multi_tenant_isolation
Revises: 001_initial_schema
Create Date: 2026-09-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "002_multi_tenant_isolation"
down_revision: str | None = "001_initial_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column("owner_id", sa.Text(), nullable=False, server_default=""),
    )
    op.create_index(
        "documents_owner_uploaded_idx",
        "documents",
        ["owner_id", sa.text("uploaded_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("documents_owner_uploaded_idx", table_name="documents")
    op.drop_column("documents", "owner_id")
