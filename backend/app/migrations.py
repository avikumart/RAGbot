from __future__ import annotations


# Each migration is an ordered tuple of statements so Store can execute the
# whole upgrade in one transaction. Never edit an applied migration; append a
# new version instead.
MIGRATION_001_INITIAL_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS documents (
        id TEXT PRIMARY KEY,
        filename TEXT NOT NULL,
        content_type TEXT NOT NULL,
        stored_path TEXT NOT NULL,
        sha256 TEXT NOT NULL,
        size_bytes INTEGER NOT NULL,
        uploaded_at TEXT NOT NULL,
        chunk_count INTEGER NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS chunks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
        ordinal INTEGER NOT NULL,
        page INTEGER,
        content TEXT NOT NULL,
        people_json TEXT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS chunks_document_idx ON chunks(document_id)",
    """CREATE TABLE IF NOT EXISTS people (
        document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
        name TEXT NOT NULL,
        normalized TEXT NOT NULL,
        mentions INTEGER NOT NULL,
        PRIMARY KEY (document_id, normalized)
    )""",
    "CREATE INDEX IF NOT EXISTS people_normalized_idx ON people(normalized)",
    """CREATE TABLE IF NOT EXISTS vector_index_state (
        document_id TEXT PRIMARY KEY REFERENCES documents(id) ON DELETE CASCADE,
        status TEXT NOT NULL,
        embedding_model TEXT,
        error TEXT,
        updated_at TEXT NOT NULL
    )""",
)


MIGRATION_002_PENDING_FILE_CLEANUP = (
    """CREATE TABLE IF NOT EXISTS pending_file_cleanup (
        stored_path TEXT PRIMARY KEY,
        document_id TEXT NOT NULL,
        queued_at TEXT NOT NULL,
        attempt_count INTEGER NOT NULL DEFAULT 0,
        last_attempt_at TEXT,
        last_error TEXT
    )""",
)


MIGRATION_003_CHAT_SESSIONS = (
    """CREATE TABLE IF NOT EXISTS chat_sessions (
        id TEXT PRIMARY KEY,
        owner_id TEXT NOT NULL,
        topic TEXT NOT NULL,
        document_ids_json TEXT,
        person TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS chat_messages (
        id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
        ordinal INTEGER NOT NULL,
        role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
        content TEXT NOT NULL,
        sources_json TEXT,
        mode TEXT,
        retrieval_mode TEXT,
        client_message_id TEXT,
        created_at TEXT NOT NULL,
        UNIQUE(session_id, ordinal)
    )""",
    "CREATE INDEX IF NOT EXISTS chat_sessions_owner_updated_idx ON chat_sessions(owner_id, updated_at DESC, id DESC)",
    "CREATE INDEX IF NOT EXISTS chat_messages_session_ordinal_idx ON chat_messages(session_id, ordinal)",
    "CREATE UNIQUE INDEX IF NOT EXISTS chat_messages_client_message_idx ON chat_messages(session_id, client_message_id) WHERE client_message_id IS NOT NULL",
)


MIGRATIONS = (
    (1, MIGRATION_001_INITIAL_SCHEMA),
    (2, MIGRATION_002_PENDING_FILE_CLEANUP),
    (3, MIGRATION_003_CHAT_SESSIONS),
)
LATEST_SCHEMA_VERSION = MIGRATIONS[-1][0]
