from __future__ import annotations

import argparse
import json
import os
import sqlite3
from pathlib import Path

import psycopg

from .database import is_postgresql_url, run_alembic_upgrade


TABLE_COLUMNS = {
    "documents": (
        "id",
        "filename",
        "content_type",
        "stored_path",
        "sha256",
        "size_bytes",
        "uploaded_at",
        "chunk_count",
    ),
    "chunks": ("id", "document_id", "ordinal", "page", "content", "people_json"),
    "people": ("document_id", "name", "normalized", "mentions"),
    "vector_index_state": (
        "document_id",
        "status",
        "embedding_model",
        "error",
        "updated_at",
    ),
    "pending_file_cleanup": (
        "stored_path",
        "document_id",
        "queued_at",
        "attempt_count",
        "last_attempt_at",
        "last_error",
    ),
    "chat_sessions": (
        "id",
        "owner_id",
        "topic",
        "document_ids_json",
        "person",
        "created_at",
        "updated_at",
    ),
    "chat_messages": (
        "id",
        "session_id",
        "ordinal",
        "role",
        "content",
        "sources_json",
        "mode",
        "retrieval_mode",
        "client_message_id",
        "created_at",
    ),
}


def migrate_sqlite_database(sqlite_path: Path, database_url: str) -> dict[str, int]:
    if not sqlite_path.is_file():
        raise FileNotFoundError(f"SQLite database does not exist: {sqlite_path}")
    if not is_postgresql_url(database_url):
        raise ValueError("The target DATABASE_URL must use postgresql://.")

    run_alembic_upgrade(database_url)
    counts: dict[str, int] = {}
    with sqlite3.connect(sqlite_path) as source:
        source.row_factory = sqlite3.Row
        source_tables = {
            row[0]
            for row in source.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        missing = set(TABLE_COLUMNS) - source_tables
        if missing:
            raise RuntimeError(
                "SQLite source is not at the current schema; missing tables: "
                + ", ".join(sorted(missing))
                + ". Start the previous application version once to apply its migrations."
            )

        with psycopg.connect(database_url) as target:
            nonempty = [
                table
                for table in TABLE_COLUMNS
                if target.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone()
            ]
            if nonempty:
                raise RuntimeError(
                    "PostgreSQL target must be empty; found data in: "
                    + ", ".join(nonempty)
                )

            for table, columns in TABLE_COLUMNS.items():
                rows = source.execute(
                    f"SELECT {', '.join(columns)} FROM {table}"
                ).fetchall()
                if rows:
                    placeholders = ", ".join("%s" for _ in columns)
                    with target.cursor() as cursor:
                        cursor.executemany(
                            f"INSERT INTO {table} ({', '.join(columns)}) "
                            f"VALUES ({placeholders})",
                            [tuple(row[column] for column in columns) for row in rows],
                        )
                counts[table] = len(rows)

            target.execute(
                """SELECT setval(
                    pg_get_serial_sequence('chunks', 'id'),
                    COALESCE((SELECT MAX(id) FROM chunks), 1),
                    EXISTS (SELECT 1 FROM chunks)
                )"""
            )
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Copy a current Personagraph SQLite database into empty PostgreSQL."
    )
    parser.add_argument(
        "sqlite_path",
        nargs="?",
        type=Path,
        default=Path(os.getenv("PERSONA_DATA_DIR", "/data")) / "personagraph.db",
    )
    parser.add_argument(
        "--database-url",
        default=os.getenv("DATABASE_URL", ""),
        help="PostgreSQL target URL (defaults to DATABASE_URL).",
    )
    args = parser.parse_args()
    if not args.database_url:
        parser.error("--database-url or DATABASE_URL is required")
    counts = migrate_sqlite_database(args.sqlite_path, args.database_url)
    print(json.dumps(counts, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
