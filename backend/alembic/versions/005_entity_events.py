"""Create entity_events table for temporal milestones.

Revision ID: 005_entity_events
Revises: 004_entity_relationships
Create Date: 2026-10-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "005_entity_events"
down_revision: str | None = "004_entity_relationships"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "entity_events",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("document_id", sa.String(), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("entity_name", sa.String(length=256), nullable=False),
        sa.Column("event_text", sa.Text(), nullable=False),
        sa.Column("event_date", sa.String(length=128), nullable=False),
        sa.Column("chunk_id", sa.Integer(), sa.ForeignKey("chunks.id", ondelete="SET NULL"), nullable=True),
    )
    op.create_index(
        "entity_events_document_id_idx",
        "entity_events",
        ["document_id"],
    )
    op.create_index(
        "entity_events_entity_name_idx",
        "entity_events",
        ["entity_name"],
    )


def downgrade() -> None:
    op.drop_index("entity_events_entity_name_idx", table_name="entity_events")
    op.drop_index("entity_events_document_id_idx", table_name="entity_events")
    op.drop_table("entity_events")
