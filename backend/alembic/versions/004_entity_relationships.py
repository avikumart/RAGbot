"""Create entity_relationships table for knowledge graph.

Revision ID: 004_entity_relationships
Revises: 003_entity_aliases
Create Date: 2026-09-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "004_entity_relationships"
down_revision: str | None = "003_entity_aliases"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "entity_relationships",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("document_id", sa.String(), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("chunk_id", sa.Integer(), sa.ForeignKey("chunks.id", ondelete="SET NULL"), nullable=True),
        sa.Column("source_entity", sa.String(length=256), nullable=False),
        sa.Column("target_entity", sa.String(length=256), nullable=False),
        sa.Column("relation", sa.String(length=256), nullable=False),
        sa.Column("source_type", sa.String(length=64), nullable=False, server_default="person"),
        sa.Column("target_type", sa.String(length=64), nullable=False, server_default="entity"),
    )
    op.create_index(
        "entity_relationships_document_id_idx",
        "entity_relationships",
        ["document_id"],
    )
    op.create_index(
        "entity_relationships_source_idx",
        "entity_relationships",
        ["source_entity"],
    )
    op.create_index(
        "entity_relationships_target_idx",
        "entity_relationships",
        ["target_entity"],
    )


def downgrade() -> None:
    op.drop_index("entity_relationships_target_idx", table_name="entity_relationships")
    op.drop_index("entity_relationships_source_idx", table_name="entity_relationships")
    op.drop_index("entity_relationships_document_id_idx", table_name="entity_relationships")
    op.drop_table("entity_relationships")
