from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse

import psycopg
import pytest

from app.extraction import Chunk
from app.sqlite_import import TABLE_COLUMNS, migrate_sqlite_database
from app.store import Store


TEST_POSTGRES_URL = os.getenv("TEST_POSTGRES_URL", "")
pytestmark = pytest.mark.skipif(
    not TEST_POSTGRES_URL,
    reason="TEST_POSTGRES_URL is required for PostgreSQL integration tests",
)


@pytest.fixture(autouse=True)
def clean_postgres():
    if not TEST_POSTGRES_URL:
        yield
        return
    database_name = urlparse(TEST_POSTGRES_URL).path.removeprefix("/")
    if not database_name.endswith("_test"):
        raise RuntimeError("PostgreSQL integration tests require a *_test database.")
    with psycopg.connect(TEST_POSTGRES_URL, autocommit=True) as connection:
        connection.execute("DROP SCHEMA public CASCADE")
        connection.execute("CREATE SCHEMA public")
    yield


def add_sample_document(store: Store, document_id: str = "document-1") -> Path:
    stored_path = store.upload_dir / f"{document_id}.txt"
    stored_path.write_text("Jordan Lee owns the rollout plan.")
    store.add_document(
        document_id=document_id,
        filename=stored_path.name,
        content_type="text/plain",
        stored_path=stored_path,
        digest="test-digest",
        size_bytes=34,
        chunks=[
            Chunk(
                ordinal=0,
                page=None,
                content="Jordan Lee owns the rollout plan.",
                people=("Jordan Lee",),
            )
        ],
        people={"Jordan Lee": 1},
    )
    return stored_path


def test_alembic_baseline_and_store_round_trip(tmp_path):
    store = Store(tmp_path, TEST_POSTGRES_URL)
    store.initialize()
    store.initialize()

    with store.connect() as connection:
        tables = {
            row["table_name"]
            for row in connection.execute(
                """SELECT table_name FROM information_schema.tables
                WHERE table_schema = 'public'"""
            ).fetchall()
        }
        assert set(TABLE_COLUMNS) | {"alembic_version"} <= tables
        assert connection.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchone()["version_num"] == "001_initial_schema"

    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        with store.connect() as connection:
            connection.execute(
                """INSERT INTO chunks
                (document_id, ordinal, page, content, people_json)
                VALUES (?, 0, NULL, 'content', '[]')""",
                ("missing",),
            )

    stored_path = add_sample_document(store)
    document = store.list_documents()[0]
    assert document["id"] == "document-1"
    assert store.list_people()[0]["name"] == "Jordan Lee"
    assert store.get_chunks()[0]["id"] > 0

    session = store.create_chat_session("owner-1")
    persisted = store.persist_chat_turn(
        "owner-1",
        session_id=session["id"],
        client_message_id="message-0001",
        content="What does Jordan own?",
        document_ids=["document-1"],
        person="Jordan Lee",
        answer="Jordan owns the rollout plan [1].",
        sources=[{"document_id": "document-1", "excerpt": "rollout plan"}],
        mode="local-grounded",
        retrieval_mode="lexical",
        topic="Jordan rollout",
    )
    assert persisted["assistant_message"]["role"] == "assistant"

    assert store.delete_document("document-1") is True
    assert not stored_path.exists()
    with store.connect() as connection:
        assert connection.execute(
            "SELECT COUNT(*) AS count FROM chunks"
        ).fetchone()["count"] == 0
        assert connection.execute(
            "SELECT COUNT(*) AS count FROM people"
        ).fetchone()["count"] == 0
    assert store.delete_chat_session("owner-1", session["id"]) is True


def test_current_sqlite_database_imports_atomically_and_preserves_chunk_ids(tmp_path):
    sqlite_dir = tmp_path / "legacy"
    source = Store(sqlite_dir)
    source.initialize()
    add_sample_document(source, "legacy-document")
    source.set_vector_status("legacy-document", "ready", "test/model")
    session = source.create_chat_session("legacy-owner", topic="Legacy chat")
    source.persist_chat_turn(
        "legacy-owner",
        session_id=session["id"],
        client_message_id="message-0001",
        content="What does Jordan own?",
        document_ids=["legacy-document"],
        person="Jordan Lee",
        answer="Jordan owns the rollout plan [1].",
        sources=[{"document_id": "legacy-document"}],
        mode="local-grounded",
        retrieval_mode="lexical",
        topic="Legacy chat",
    )

    counts = migrate_sqlite_database(source.db_path, TEST_POSTGRES_URL)
    assert counts == {
        "documents": 1,
        "chunks": 1,
        "people": 1,
        "vector_index_state": 1,
        "pending_file_cleanup": 0,
        "chat_sessions": 1,
        "chat_messages": 2,
    }

    target = Store(tmp_path / "target", TEST_POSTGRES_URL)
    assert target.get_chunks()[0]["id"] == 1
    assert target.get_document("legacy-document")["index_status"] == "ready"
    assert target.get_chat_session("legacy-owner", session["id"])["messages"][1][
        "role"
    ] == "assistant"

    with pytest.raises(RuntimeError, match="target must be empty"):
        migrate_sqlite_database(source.db_path, TEST_POSTGRES_URL)
