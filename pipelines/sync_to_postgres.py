"""CLI Pipeline: Synchronize approved manifest.json evidence into PostgreSQL + pgvector.

Usage:
    python pipelines/sync_to_postgres.py [--url postgresql://user:pass@host:5432/dbname]
"""

import argparse
import os
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.retrieval.pg_vector_engine import DATABASE_URL_ENV, DEFAULT_DATABASE_URL, PgVectorHybridEngine

MANIFEST_PATH = ROOT_DIR / "clinical" / "evidence_manifest" / "manifest.json"


def sync_manifest_to_postgres(database_url: str) -> None:
    print("Connecting to PostgreSQL...")
    engine = PgVectorHybridEngine(database_url=database_url)

    if not engine.ping():
        print("❌ Error: Unable to connect to PostgreSQL. Check your DATABASE_URL or ensure the database server is running.")
        sys.exit(1)

    print("✅ Connection verified. Initializing pgvector extension and clinical schema...")
    num_sources, num_passages = engine.sync_from_manifest(MANIFEST_PATH)

    print(f"🎉 Successfully synchronized {num_sources} sources and {num_passages} passages into PostgreSQL + pgvector!")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sync manifest.json to PostgreSQL + pgvector.")
    parser.add_argument(
        "--url",
        default=os.getenv(DATABASE_URL_ENV, DEFAULT_DATABASE_URL),
        help="PostgreSQL connection URL.",
    )
    args = parser.parse_args()

    sync_manifest_to_postgres(args.url)

