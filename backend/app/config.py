from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    max_upload_bytes: int
    ollama_base_url: str
    ollama_model: str
    cors_origins: tuple[str, ...]

    @classmethod
    def from_env(cls, data_dir: Path | None = None) -> "Settings":
        resolved_data_dir = data_dir or Path(os.getenv("PERSONA_DATA_DIR", "/data"))
        origins = os.getenv(
            "CORS_ORIGINS",
            "http://localhost:3000,http://127.0.0.1:3000",
        )
        return cls(
            data_dir=resolved_data_dir,
            max_upload_bytes=int(os.getenv("MAX_UPLOAD_BYTES", str(10 * 1024 * 1024))),
            ollama_base_url=os.getenv("OLLAMA_BASE_URL", "").rstrip("/"),
            ollama_model=os.getenv("OLLAMA_MODEL", "llama3.2:3b"),
            cors_origins=tuple(origin.strip() for origin in origins.split(",") if origin.strip()),
        )

