from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import psycopg
from alembic import command
from alembic.config import Config
from psycopg.rows import dict_row


POSTGRESQL_PREFIXES = ("postgresql://", "postgres://")


def is_postgresql_url(database_url: str) -> bool:
    return database_url.startswith(POSTGRESQL_PREFIXES)


class DatabaseConnection:
    """Small DB-API compatibility layer for SQLite tests and PostgreSQL runtime."""

    def __init__(self, connection: Any, dialect: str):
        self._connection = connection
        self.dialect = dialect

    def _statement(self, statement: str) -> str:
        if self.dialect != "postgresql":
            return statement
        if statement.strip().upper() == "BEGIN IMMEDIATE":
            return "BEGIN"
        return statement.replace("?", "%s")

    def execute(self, statement: str, parameters: Any = None):
        sql = self._statement(statement)
        if parameters is None:
            return self._connection.execute(sql)
        return self._connection.execute(sql, parameters)

    def executemany(self, statement: str, parameters: Any):
        if self.dialect == "postgresql":
            with self._connection.cursor() as cursor:
                cursor.executemany(self._statement(statement), parameters)
            return None
        return self._connection.executemany(statement, parameters)

    def commit(self) -> None:
        self._connection.commit()

    def rollback(self) -> None:
        self._connection.rollback()

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> "DatabaseConnection":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        try:
            if exc_type is None:
                self.commit()
            else:
                self.rollback()
        finally:
            self.close()


def connect(database_url: str) -> DatabaseConnection:
    if is_postgresql_url(database_url):
        connection = psycopg.connect(database_url, row_factory=dict_row)
        return DatabaseConnection(connection, "postgresql")

    prefix = "sqlite:///"
    if not database_url.startswith(prefix):
        raise ValueError("DATABASE_URL must use postgresql:// or sqlite:///.")
    database_path = Path(database_url.removeprefix(prefix))
    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return DatabaseConnection(connection, "sqlite")


def run_alembic_upgrade(database_url: str) -> None:
    if not is_postgresql_url(database_url):
        return
    backend_root = Path(__file__).resolve().parents[1]
    config = Config(str(backend_root / "alembic.ini"))
    config.attributes["database_url"] = database_url
    command.upgrade(config, "head")
