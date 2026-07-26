from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

from .extraction import Chunk


DEFAULT_INDEX_STATUS = "pending"
PUBLIC_INDEX_ERROR = (
    "Document embeddings could not be generated. Retry indexing and check the status again."
)


class Store:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.upload_dir = data_dir / "uploads"
        self.db_path = data_dir / "personagraph.db"

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def initialize(self) -> None:
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS documents (
                    id TEXT PRIMARY KEY,
                    filename TEXT NOT NULL,
                    content_type TEXT NOT NULL,
                    stored_path TEXT NOT NULL,
                    sha256 TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    uploaded_at TEXT NOT NULL,
                    chunk_count INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS chunks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                    ordinal INTEGER NOT NULL,
                    page INTEGER,
                    content TEXT NOT NULL,
                    people_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS chunks_document_idx ON chunks(document_id);
                CREATE TABLE IF NOT EXISTS people (
                    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                    name TEXT NOT NULL,
                    normalized TEXT NOT NULL,
                    mentions INTEGER NOT NULL,
                    PRIMARY KEY (document_id, normalized)
                );
                CREATE INDEX IF NOT EXISTS people_normalized_idx ON people(normalized);
                CREATE TABLE IF NOT EXISTS vector_index_state (
                    document_id TEXT PRIMARY KEY REFERENCES documents(id) ON DELETE CASCADE,
                    status TEXT NOT NULL,
                    embedding_model TEXT,
                    error TEXT,
                    updated_at TEXT NOT NULL
                );
                """
            )

    def add_document(
        self,
        *,
        document_id: str,
        filename: str,
        content_type: str,
        stored_path: Path,
        digest: str,
        size_bytes: int,
        chunks: list[Chunk],
        people: dict[str, int],
    ) -> dict:
        uploaded_at = datetime.now(UTC).isoformat()
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO documents
                (id, filename, content_type, stored_path, sha256, size_bytes, uploaded_at, chunk_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    document_id, filename, content_type, str(stored_path), digest,
                    size_bytes, uploaded_at, len(chunks),
                ),
            )
            connection.executemany(
                """INSERT INTO chunks (document_id, ordinal, page, content, people_json)
                VALUES (?, ?, ?, ?, ?)""",
                [
                    (document_id, chunk.ordinal, chunk.page, chunk.content, json.dumps(chunk.people))
                    for chunk in chunks
                ],
            )
            connection.executemany(
                """INSERT INTO people (document_id, name, normalized, mentions)
                VALUES (?, ?, ?, ?)""",
                [
                    (document_id, name, name.casefold(), mentions)
                    for name, mentions in people.items()
                ],
            )
        return {
            "id": document_id,
            "filename": filename,
            "content_type": content_type,
            "size_bytes": size_bytes,
            "uploaded_at": uploaded_at,
            "chunk_count": len(chunks),
            "people": sorted(people),
        }

    def set_vector_status(
        self, document_id: str, status: str, embedding_model: str, error: str | None = None
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO vector_index_state
                (document_id, status, embedding_model, error, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(document_id) DO UPDATE SET
                status=excluded.status, embedding_model=excluded.embedding_model,
                error=excluded.error, updated_at=excluded.updated_at""",
                (document_id, status, embedding_model, error, datetime.now(UTC).isoformat()),
            )

    def list_documents(self) -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT documents.*,
                vector_index_state.status AS stored_index_status,
                vector_index_state.error AS stored_index_error,
                vector_index_state.updated_at AS stored_index_updated_at
                FROM documents
                LEFT JOIN vector_index_state
                ON vector_index_state.document_id = documents.id
                ORDER BY documents.uploaded_at DESC"""
            ).fetchall()
            result = []
            for row in rows:
                people = connection.execute(
                    "SELECT name FROM people WHERE document_id = ? ORDER BY name",
                    (row["id"],),
                ).fetchall()
                result.append(
                    {
                        "id": row["id"],
                        "filename": row["filename"],
                        "content_type": row["content_type"],
                        "size_bytes": row["size_bytes"],
                        "uploaded_at": row["uploaded_at"],
                        "chunk_count": row["chunk_count"],
                        "people": [person["name"] for person in people],
                        "index_status": row["stored_index_status"] or DEFAULT_INDEX_STATUS,
                        "index_error": (
                            PUBLIC_INDEX_ERROR if row["stored_index_error"] else None
                        ),
                        "index_updated_at": row["stored_index_updated_at"],
                    }
                )
            return result

    def get_document(self, document_id: str) -> dict | None:
        return next(
            (
                document
                for document in self.list_documents()
                if document["id"] == document_id
            ),
            None,
        )

    def list_people(self, document_ids: Iterable[str] | None = None) -> list[dict]:
        ids = list(document_ids or [])
        clause = ""
        params: list[str] = []
        if ids:
            clause = f"WHERE document_id IN ({','.join('?' for _ in ids)})"
            params = ids
        with self.connect() as connection:
            rows = connection.execute(
                f"""SELECT normalized, MIN(name) AS name, SUM(mentions) AS mentions,
                COUNT(DISTINCT document_id) AS document_count
                FROM people {clause}
                GROUP BY normalized ORDER BY mentions DESC, name ASC""",
                params,
            ).fetchall()
            return [dict(row) for row in rows]

    def get_chunks(self, document_ids: Iterable[str] | None = None) -> list[dict]:
        ids = list(document_ids or [])
        clause = ""
        params: list[str] = []
        if ids:
            clause = f"WHERE chunks.document_id IN ({','.join('?' for _ in ids)})"
            params = ids
        with self.connect() as connection:
            rows = connection.execute(
                f"""SELECT chunks.*, documents.filename
                FROM chunks JOIN documents ON documents.id = chunks.document_id
                {clause} ORDER BY documents.uploaded_at DESC, chunks.ordinal ASC""",
                params,
            ).fetchall()
            return [
                {
                    **dict(row),
                    "people": json.loads(row["people_json"]),
                }
                for row in rows
            ]

    def get_chunks_by_ids(
        self, chunk_ids: Iterable[int], document_ids: Iterable[str] | None = None
    ) -> list[dict]:
        ids = list(dict.fromkeys(chunk_ids))
        if not ids:
            return []
        document_scope = list(document_ids or [])
        clauses = [f"chunks.id IN ({','.join('?' for _ in ids)})"]
        params: list[str | int] = list(ids)
        if document_scope:
            clauses.append(
                f"chunks.document_id IN ({','.join('?' for _ in document_scope)})"
            )
            params.extend(document_scope)
        with self.connect() as connection:
            rows = connection.execute(
                f"""SELECT chunks.*, documents.filename
                FROM chunks JOIN documents ON documents.id = chunks.document_id
                WHERE {' AND '.join(clauses)}""",
                params,
            ).fetchall()
            return [{**dict(row), "people": json.loads(row["people_json"])} for row in rows]

    def document_exists(self, document_id: str) -> bool:
        with self.connect() as connection:
            return connection.execute(
                "SELECT 1 FROM documents WHERE id = ?", (document_id,)
            ).fetchone() is not None

    def delete_document(self, document_id: str) -> bool:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT stored_path FROM documents WHERE id = ?", (document_id,)
            ).fetchone()
            if not row:
                return False
            connection.execute("DELETE FROM documents WHERE id = ?", (document_id,))
        path = Path(row["stored_path"])
        if path.exists() and self.upload_dir in path.parents:
            path.unlink()
        return True
