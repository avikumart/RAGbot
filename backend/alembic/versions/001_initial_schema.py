"""Create the initial Personagraph PostgreSQL schema.

Revision ID: 001_initial_schema
Revises:
Create Date: 2026-08-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "001_initial_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("content_type", sa.Text(), nullable=False),
        sa.Column("stored_path", sa.Text(), nullable=False),
        sa.Column("sha256", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("uploaded_at", sa.Text(), nullable=False),
        sa.Column("chunk_count", sa.Integer(), nullable=False),
    )
    op.create_table(
        "chunks",
        sa.Column("id", sa.Integer(), sa.Identity(), primary_key=True),
        sa.Column(
            "document_id",
            sa.Text(),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("page", sa.Integer()),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("people_json", sa.Text(), nullable=False),
    )
    op.create_index("chunks_document_idx", "chunks", ["document_id"])
    op.create_table(
        "people",
        sa.Column(
            "document_id",
            sa.Text(),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("normalized", sa.Text(), primary_key=True),
        sa.Column("mentions", sa.Integer(), nullable=False),
    )
    op.create_index("people_normalized_idx", "people", ["normalized"])
    op.create_table(
        "vector_index_state",
        sa.Column(
            "document_id",
            sa.Text(),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("embedding_model", sa.Text()),
        sa.Column("error", sa.Text()),
        sa.Column("updated_at", sa.Text(), nullable=False),
    )
    op.create_table(
        "pending_file_cleanup",
        sa.Column("stored_path", sa.Text(), primary_key=True),
        sa.Column("document_id", sa.Text(), nullable=False),
        sa.Column("queued_at", sa.Text(), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_attempt_at", sa.Text()),
        sa.Column("last_error", sa.Text()),
    )
    op.create_table(
        "chat_sessions",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("owner_id", sa.Text(), nullable=False),
        sa.Column("topic", sa.Text(), nullable=False),
        sa.Column("document_ids_json", sa.Text()),
        sa.Column("person", sa.Text()),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
    )
    op.create_index(
        "chat_sessions_owner_updated_idx",
        "chat_sessions",
        ["owner_id", sa.text("updated_at DESC"), sa.text("id DESC")],
    )
    op.create_table(
        "chat_messages",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column(
            "session_id",
            sa.Text(),
            sa.ForeignKey("chat_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column(
            "role",
            sa.Text(),
            sa.CheckConstraint("role IN ('user', 'assistant')"),
            nullable=False,
        ),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("sources_json", sa.Text()),
        sa.Column("mode", sa.Text()),
        sa.Column("retrieval_mode", sa.Text()),
        sa.Column("client_message_id", sa.Text()),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.UniqueConstraint("session_id", "ordinal"),
    )
    op.create_index(
        "chat_messages_session_ordinal_idx",
        "chat_messages",
        ["session_id", "ordinal"],
    )
    op.create_index(
        "chat_messages_client_message_idx",
        "chat_messages",
        ["session_id", "client_message_id"],
        unique=True,
        postgresql_where=sa.text("client_message_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("chat_messages_client_message_idx", table_name="chat_messages")
    op.drop_index("chat_messages_session_ordinal_idx", table_name="chat_messages")
    op.drop_table("chat_messages")
    op.drop_index("chat_sessions_owner_updated_idx", table_name="chat_sessions")
    op.drop_table("chat_sessions")
    op.drop_table("pending_file_cleanup")
    op.drop_table("vector_index_state")
    op.drop_index("people_normalized_idx", table_name="people")
    op.drop_table("people")
    op.drop_index("chunks_document_idx", table_name="chunks")
    op.drop_table("chunks")
    op.drop_table("documents")
