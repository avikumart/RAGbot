import sqlite3

import pytest

from app.extraction import Chunk
from app.migrations import LATEST_SCHEMA_VERSION
from app.store import Store


LEGACY_SCHEMA = """
CREATE TABLE documents (
    id TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    content_type TEXT NOT NULL,
    stored_path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    uploaded_at TEXT NOT NULL,
    chunk_count INTEGER NOT NULL
);
CREATE TABLE chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL,
    page INTEGER,
    content TEXT NOT NULL,
    people_json TEXT NOT NULL
);
CREATE INDEX chunks_document_idx ON chunks(document_id);
CREATE TABLE people (
    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    normalized TEXT NOT NULL,
    mentions INTEGER NOT NULL,
    PRIMARY KEY (document_id, normalized)
);
CREATE INDEX people_normalized_idx ON people(normalized);
"""


def schema_objects(connection):
    return connection.execute(
        """SELECT type, name, tbl_name, sql
        FROM sqlite_master
        WHERE name NOT LIKE 'sqlite_%'
        ORDER BY type, name"""
    ).fetchall()


def test_opening_empty_database_runs_migration_001_and_enforces_foreign_keys(tmp_path):
    store = Store(tmp_path)
    store.initialize()

    with store.connect() as connection:
        tables = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        assert {"documents", "chunks", "people", "vector_index_state"} <= tables
        assert connection.execute("PRAGMA user_version").fetchone()[0] == (
            LATEST_SCHEMA_VERSION
        )
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """INSERT INTO chunks
                (document_id, ordinal, page, content, people_json)
                VALUES ('missing', 0, NULL, 'content', '[]')"""
            )


def test_migration_is_idempotent(tmp_path):
    store = Store(tmp_path)
    store.initialize()
    with store.connect() as connection:
        before = schema_objects(connection)
        connection.execute(
            """INSERT INTO documents
            (id, filename, content_type, stored_path, sha256, size_bytes, uploaded_at, chunk_count)
            VALUES ('existing', 'existing.txt', 'text/plain', '/tmp/existing.txt',
                    'digest', 8, '2026-08-01T00:00:00Z', 0)"""
        )

    store.initialize()

    with store.connect() as connection:
        assert schema_objects(connection) == before
        assert connection.execute("PRAGMA user_version").fetchone()[0] == (
            LATEST_SCHEMA_VERSION
        )
        assert connection.execute(
            "SELECT filename FROM documents WHERE id = 'existing'"
        ).fetchone()[0] == "existing.txt"


def test_opening_pre_existing_unversioned_database_preserves_data(tmp_path):
    database_path = tmp_path / "personagraph.db"
    with sqlite3.connect(database_path) as connection:
        connection.executescript(LEGACY_SCHEMA)
        connection.execute(
            """INSERT INTO documents
            (id, filename, content_type, stored_path, sha256, size_bytes, uploaded_at, chunk_count)
            VALUES ('legacy', 'legacy.txt', 'text/plain', '/tmp/legacy.txt',
                    'digest', 12, '2026-08-01T00:00:00Z', 1)"""
        )
        connection.execute(
            """INSERT INTO chunks
            (document_id, ordinal, page, content, people_json)
            VALUES ('legacy', 0, NULL, 'Jordan Lee led it.', '[\"Jordan Lee\"]')"""
        )
        connection.execute(
            """INSERT INTO people (document_id, name, normalized, mentions)
            VALUES ('legacy', 'Jordan Lee', 'jordan lee', 1)"""
        )
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 0

    store = Store(tmp_path)
    store.initialize()

    assert store.upload_dir.is_dir()
    assert store.get_document("legacy")["filename"] == "legacy.txt"
    assert store.get_chunks(["legacy"])[0]["content"] == "Jordan Lee led it."
    with store.connect() as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == (
            LATEST_SCHEMA_VERSION
        )
        assert connection.execute(
            "SELECT COUNT(*) FROM vector_index_state"
        ).fetchone()[0] == 0


def test_opening_database_from_newer_app_fails_without_changes(tmp_path):
    database_path = tmp_path / "personagraph.db"
    with sqlite3.connect(database_path) as connection:
        connection.execute(f"PRAGMA user_version = {LATEST_SCHEMA_VERSION + 1}")

    with pytest.raises(RuntimeError, match="newer than supported"):
        Store(tmp_path).initialize()

    with sqlite3.connect(database_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == (
            LATEST_SCHEMA_VERSION + 1
        )
        assert schema_objects(connection) == []


def test_database_persists_documents_and_cascades_deletes(tmp_path):
    store = Store(tmp_path)
    store.initialize()
    stored_path = store.upload_dir / "document.txt"
    stored_path.write_text("Jordan Lee owns the rollout plan.")

    store.add_document(
        document_id="document-1",
        filename="document.txt",
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

    reopened = Store(tmp_path)
    document = reopened.list_documents()[0]
    assert document["id"] == "document-1"
    assert document["index_status"] == "pending"
    assert document["index_error"] is None
    assert document["index_updated_at"] is None
    assert reopened.list_people()[0]["name"] == "Jordan Lee"
    assert reopened.get_chunks()[0]["content"] == "Jordan Lee owns the rollout plan."

    assert reopened.delete_document("document-1") is True
    assert not stored_path.exists()
    with reopened.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM chunks").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM people").fetchone()[0] == 0


def test_document_index_status_is_returned_without_internal_error_details(tmp_path):
    store = Store(tmp_path)
    store.initialize()
    stored_path = store.upload_dir / "failed.txt"
    stored_path.write_text("A document that could not be embedded.")
    store.add_document(
        document_id="failed-document",
        filename="failed.txt",
        content_type="text/plain",
        stored_path=stored_path,
        digest="test-digest",
        size_bytes=38,
        chunks=[],
        people={},
    )
    store.set_vector_status(
        "failed-document",
        "needs_reindex",
        "test/model",
        "Connection refused at qdrant.internal:6333 with token=secret-value",
    )

    document = store.list_documents()[0]
    assert document["index_status"] == "needs_reindex"
    assert document["index_error"] == (
        "Document embeddings could not be generated. Retry indexing and check the status again."
    )
    assert document["index_updated_at"] is not None
    assert "qdrant.internal" not in document["index_error"]
    assert "secret-value" not in document["index_error"]
