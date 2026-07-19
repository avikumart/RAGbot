from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    max_upload_bytes: int
    cerebras_api_key: str
    cerebras_base_url: str
    cerebras_model: str
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
            cerebras_api_key=os.getenv("CEREBRAS_API_KEY", "").strip(),
            cerebras_base_url=os.getenv(
                "CEREBRAS_API_BASE_URL",
                "https://api.cerebras.ai/v1",
            ).rstrip("/"),
            cerebras_model=os.getenv("CEREBRAS_MODEL", "gpt-oss-120b"),
            cors_origins=tuple(origin.strip() for origin in origins.split(",") if origin.strip()),
        )
