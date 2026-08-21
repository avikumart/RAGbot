from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    database_url: str
    max_upload_bytes: int
    cerebras_api_key: str
    cerebras_base_url: str
    cerebras_model: str
    cors_origins: tuple[str, ...]
    vector_search_enabled: bool
    qdrant_url: str
    qdrant_collection: str
    embedding_provider: str
    embedding_model: str
    embedding_dimensions: int
    embedding_batch_size: int
    vector_candidate_limit: int
    lexical_candidate_limit: int
    vector_timeout_seconds: float
    embedding_timeout_seconds: float
    auth_proxy_secret: str
    local_development_owner: str
    chunk_size: int
    chunk_overlap: int

    @classmethod
    def from_env(cls, data_dir: Path | None = None) -> "Settings":
        resolved_data_dir = data_dir or Path(os.getenv("PERSONA_DATA_DIR", "/data"))
        database_url = os.getenv("DATABASE_URL", "").strip()
        if not database_url:
            database_url = (
                f"sqlite:///{resolved_data_dir / 'personagraph.db'}"
                if data_dir is not None
                else "postgresql://personagraph:personagraph@postgres:5432/personagraph"
            )
        origins = os.getenv(
            "CORS_ORIGINS",
            "http://localhost:3000,http://127.0.0.1:3000",
        )
        return cls(
            data_dir=resolved_data_dir,
            database_url=database_url,
            max_upload_bytes=int(os.getenv("MAX_UPLOAD_BYTES", str(10 * 1024 * 1024))),
            cerebras_api_key=os.getenv("CEREBRAS_API_KEY", "").strip(),
            cerebras_base_url=os.getenv(
                "CEREBRAS_API_BASE_URL",
                "https://api.cerebras.ai/v1",
            ).rstrip("/"),
            cerebras_model=os.getenv("CEREBRAS_MODEL", "gpt-oss-120b"),
            cors_origins=tuple(origin.strip() for origin in origins.split(",") if origin.strip()),
            vector_search_enabled=os.getenv("VECTOR_SEARCH_ENABLED", "true").casefold()
            in {"1", "true", "yes", "on"},
            qdrant_url=os.getenv("QDRANT_URL", "http://qdrant:6333").rstrip("/"),
            qdrant_collection=os.getenv("QDRANT_COLLECTION", "personagraph_chunks"),
            embedding_provider=os.getenv("EMBEDDING_PROVIDER", "local").casefold(),
            embedding_model=os.getenv(
                "EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5"
            ),
            embedding_dimensions=int(os.getenv("EMBEDDING_DIMENSIONS", "384")),
            embedding_batch_size=int(os.getenv("EMBEDDING_BATCH_SIZE", "32")),
            vector_candidate_limit=int(os.getenv("VECTOR_CANDIDATE_LIMIT", "20")),
            lexical_candidate_limit=int(os.getenv("LEXICAL_CANDIDATE_LIMIT", "20")),
            vector_timeout_seconds=float(os.getenv("VECTOR_TIMEOUT_SECONDS", "5")),
            embedding_timeout_seconds=float(os.getenv("EMBEDDING_TIMEOUT_SECONDS", "30")),
            auth_proxy_secret=os.getenv("AUTH_PROXY_SECRET", "").strip(),
            local_development_owner=os.getenv(
                "LOCAL_DEVELOPMENT_OWNER", "local-development-user"
            ).strip() or "local-development-user",
            chunk_size=int(os.getenv("CHUNK_SIZE", "800")),
            chunk_overlap=int(os.getenv("CHUNK_OVERLAP", "150")),
        )
