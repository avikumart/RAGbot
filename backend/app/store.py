from __future__ import annotations

import json
import logging
import sqlite3
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

from .extraction import Chunk
from .migrations import LATEST_SCHEMA_VERSION, MIGRATIONS


DEFAULT_INDEX_STATUS = "pending"
PUBLIC_INDEX_ERROR = (
    "Document embeddings could not be generated. Retry indexing and check the status again."
)
logger = logging.getLogger(__name__)


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
            self._migrate(connection)
        # File deletion is deliberately retried after schema initialization. A
        # previous process may have committed a document deletion but failed to
        # unlink its uploaded file because of a transient filesystem error.
        try:
            self.cleanup_pending_files()
        except Exception:
            # Pending rows are durable, so cleanup must never make the database
            # unavailable at startup. A later startup or deletion retries them.
            logger.exception("Pending uploaded-file cleanup retry failed")

    @staticmethod
    def _migrate(connection: sqlite3.Connection) -> None:
        # The write lock is acquired before reading user_version so concurrent
        # startup cannot apply the same non-idempotent future migration twice.
        connection.execute("BEGIN IMMEDIATE")
        try:
            current_version = connection.execute("PRAGMA user_version").fetchone()[0]
            if current_version > LATEST_SCHEMA_VERSION:
                raise RuntimeError(
                    "Database schema version "
                    f"{current_version} is newer than supported version "
                    f"{LATEST_SCHEMA_VERSION}."
                )

            for target_version, statements in MIGRATIONS:
                if target_version <= current_version:
                    continue
                if target_version != current_version + 1:
                    raise RuntimeError(
                        f"Missing database migration after version {current_version}."
                    )
                for statement in statements:
                    connection.execute(statement)
                connection.execute(f"PRAGMA user_version = {target_version}")
                current_version = target_version
            connection.commit()
        except Exception:
            connection.rollback()
            raise

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
        # Deletion ordering is intentional:
        # 1. In one SQLite transaction, durably queue the file path and delete
        #    the authoritative document row (which cascades to related rows).
        # 2. After that transaction commits, best-effort unlink queued files.
        # A filesystem failure therefore cannot roll back or misreport an
        # already-committed document deletion; its queue row remains for retry.
        with self.connect() as connection:
            row = connection.execute(
                "SELECT stored_path FROM documents WHERE id = ?", (document_id,)
            ).fetchone()
            if not row:
                return False
            stored_path = row["stored_path"]
            connection.execute(
                """INSERT INTO pending_file_cleanup
                (stored_path, document_id, queued_at)
                VALUES (?, ?, ?)
                ON CONFLICT(stored_path) DO UPDATE SET
                document_id=excluded.document_id,
                queued_at=excluded.queued_at,
                attempt_count=0,
                last_attempt_at=NULL,
                last_error=NULL""",
                (stored_path, document_id, datetime.now(UTC).isoformat()),
            )
            connection.execute("DELETE FROM documents WHERE id = ?", (document_id,))
        try:
            # Retry every queued path while a deletion request has already paid
            # the cost of entering the cleanup path.
            self.cleanup_pending_files()
        except Exception:
            # SQLite deletion has committed and the pending cleanup row is the
            # recovery mechanism. Do not return an error for a deleted document.
            logger.exception(
                "Uploaded-file cleanup deferred; pending cleanup retained "
                "document_id=%s stored_path=%s",
                document_id,
                stored_path,
            )
        return True

    def cleanup_pending_files(
        self, stored_paths: Iterable[str] | None = None
    ) -> tuple[int, int]:
        """Best-effort unlink queued uploads, returning (completed, pending).

        Successful cleanup, including an already-missing file, removes its queue
        row. Failures are recorded and logged for a later startup or deletion to
        retry. Paths outside the managed upload directory are never unlinked;
        their unsafe queue rows are logged and retired instead of retried.
        """
        paths = list(dict.fromkeys(stored_paths)) if stored_paths is not None else None
        if paths == []:
            return 0, 0

        clause = ""
        params: list[str] = []
        if paths is not None:
            clause = f"WHERE stored_path IN ({','.join('?' for _ in paths)})"
            params = paths
        with self.connect() as connection:
            rows = connection.execute(
                f"""SELECT stored_path, document_id
                FROM pending_file_cleanup {clause}
                ORDER BY queued_at, stored_path""",
                params,
            ).fetchall()

        completed = 0
        pending = 0
        for row in rows:
            stored_path = row["stored_path"]
            path = Path(stored_path)
            if not self._is_managed_upload_path(path):
                reason = "Stored path is outside the managed upload directory."
                with self.connect() as connection:
                    connection.execute(
                        "DELETE FROM pending_file_cleanup WHERE stored_path = ?",
                        (stored_path,),
                    )
                completed += 1
                logger.warning(
                    "Uploaded-file cleanup retired without unlinking "
                    "document_id=%s stored_path=%s reason=%s",
                    row["document_id"],
                    stored_path,
                    reason,
                )
                continue

            error: str | None = None
            try:
                path.unlink(missing_ok=True)
            except OSError as exc:
                error = str(exc)

            if error is not None:
                pending += 1
                attempted_at = datetime.now(UTC).isoformat()
                with self.connect() as connection:
                    connection.execute(
                        """UPDATE pending_file_cleanup
                        SET attempt_count = attempt_count + 1,
                            last_attempt_at = ?, last_error = ?
                        WHERE stored_path = ?""",
                        (attempted_at, error[:500], stored_path),
                    )
                logger.warning(
                    "Uploaded-file cleanup deferred; pending cleanup retained "
                    "document_id=%s stored_path=%s reason=%s",
                    row["document_id"],
                    stored_path,
                    error,
                )
                continue

            with self.connect() as connection:
                connection.execute(
                    "DELETE FROM pending_file_cleanup WHERE stored_path = ?",
                    (stored_path,),
                )
            completed += 1

        return completed, pending

    def _is_managed_upload_path(self, path: Path) -> bool:
        try:
            upload_dir = self.upload_dir.resolve()
            resolved_path = path.resolve()
        except (OSError, RuntimeError):
            return False
        return resolved_path != upload_dir and upload_dir in resolved_path.parents
