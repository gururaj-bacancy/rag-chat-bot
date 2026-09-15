"""Applies every SQL migration in backend/migrations/, in sorted filename order,
inside a single transaction.

Usage:
    python scripts/run_migrations.py [database_url]

Defaults to `settings.database_url` from `app.config` when no URL is given.
"""

import sys
from pathlib import Path

from sqlalchemy import create_engine, text

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"


def run_migrations(database_url: str) -> None:
    engine = create_engine(database_url)
    try:
        with engine.begin() as conn:
            for sql_file in sorted(MIGRATIONS_DIR.glob("*.sql")):
                conn.execute(text(sql_file.read_text()))
    finally:
        engine.dispose()


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from app.config import settings

    url = sys.argv[1] if len(sys.argv) > 1 else settings.database_url
    run_migrations(url)
    print(f"Applied migrations in {MIGRATIONS_DIR} to {url}")
