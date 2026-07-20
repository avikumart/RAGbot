from __future__ import annotations

import argparse
import json
import logging

from .config import Settings
from .store import Store
from .vector_service import VectorService


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Backfill missing vectors and remove Qdrant records orphaned from SQLite."
    )
    parser.add_argument("command", choices=["backfill"])
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)

    settings = Settings.from_env()
    if not settings.vector_search_enabled:
        parser.error("VECTOR_SEARCH_ENABLED must be true to run vector backfill")
    store = Store(settings.data_dir)
    store.initialize()
    stats = VectorService(settings, store).reconcile()
    print(json.dumps(stats.__dict__, sort_keys=True))
    return 1 if stats.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
