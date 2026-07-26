import sqlite3

import pytest

from app.extraction import Chunk
from app.store import Store


def test_database_initialization_creates_schema_and_enforces_foreign_keys(tmp_path):
    store = Store(tmp_path)
    store.initialize()

    with store.connect() as connection:
        tables = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        assert {"documents", "chunks", "people"} <= tables
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """INSERT INTO chunks
                (document_id, ordinal, page, content, people_json)
                VALUES ('missing', 0, NULL, 'content', '[]')"""
            )


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
