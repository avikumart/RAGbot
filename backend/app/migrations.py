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


MIGRATION_004_CHUNKS_FTS = (
    """CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
        content,
        document_id UNINDEXED,
        chunk_id UNINDEXED,
        tokenize='porter unicode61'
    )""",
)


MIGRATION_005_MULTI_TENANT_ISOLATION = (
    """ALTER TABLE documents ADD COLUMN owner_id TEXT NOT NULL DEFAULT ''""",
    "CREATE INDEX IF NOT EXISTS documents_owner_uploaded_idx ON documents(owner_id, uploaded_at DESC)",
)


MIGRATION_006_ENTITY_ALIASES = (
    """ALTER TABLE people ADD COLUMN canonical_id TEXT NOT NULL DEFAULT ''""",
    "CREATE INDEX IF NOT EXISTS people_canonical_idx ON people(canonical_id)",
)


MIGRATION_007_ENTITY_RELATIONSHIPS = (
    """CREATE TABLE IF NOT EXISTS entity_relationships (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
        chunk_id INTEGER REFERENCES chunks(id) ON DELETE SET NULL,
        source_entity TEXT NOT NULL,
        target_entity TEXT NOT NULL,
        relation TEXT NOT NULL,
        source_type TEXT NOT NULL DEFAULT 'person',
        target_type TEXT NOT NULL DEFAULT 'entity'
    )""",
    "CREATE INDEX IF NOT EXISTS entity_relationships_document_id_idx ON entity_relationships(document_id)",
    "CREATE INDEX IF NOT EXISTS entity_relationships_source_idx ON entity_relationships(source_entity)",
    "CREATE INDEX IF NOT EXISTS entity_relationships_target_idx ON entity_relationships(target_entity)",
)


MIGRATIONS = (
    (1, MIGRATION_001_INITIAL_SCHEMA),
    (2, MIGRATION_002_PENDING_FILE_CLEANUP),
    (3, MIGRATION_003_CHAT_SESSIONS),
    (4, MIGRATION_004_CHUNKS_FTS),
    (5, MIGRATION_005_MULTI_TENANT_ISOLATION),
    (6, MIGRATION_006_ENTITY_ALIASES),
    (7, MIGRATION_007_ENTITY_RELATIONSHIPS),
)
LATEST_SCHEMA_VERSION = MIGRATIONS[-1][0]


