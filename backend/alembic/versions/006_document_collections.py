"""Create collections and collection_documents tables for document organization.

Revision ID: 006_document_collections
Revises: 005_entity_events
Create Date: 2026-10-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "006_document_collections"
down_revision: str | None = "005_entity_events"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "collections",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("owner_id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
    )
    op.create_index(
        "collections_owner_created_idx",
        "collections",
        ["owner_id", sa.text("created_at DESC")],
    )
    op.create_table(
        "collection_documents",
        sa.Column(
            "collection_id",
            sa.Text(),
            sa.ForeignKey("collections.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "document_id",
            sa.Text(),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )
    op.create_index(
        "collection_documents_document_idx",
        "collection_documents",
        ["document_id"],
    )


def downgrade() -> None:
    op.drop_index("collection_documents_document_idx", table_name="collection_documents")
    op.drop_table("collection_documents")
    op.drop_index("collections_owner_created_idx", table_name="collections")
    op.drop_table("collections")
