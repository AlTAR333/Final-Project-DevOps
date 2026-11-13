"""Apply db/migrations/*.sql in order, once each. Run with: python -m db.migrate

Owner: Tristan.
"""

from pathlib import Path

from common.config import load_settings
from common.db import connect

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
LOCK_ID = 954_001


def pending_migrations(applied: set[str]) -> list[Path]:
    return [p for p in sorted(MIGRATIONS_DIR.glob("*.sql")) if p.stem not in applied]


def migrate(conn) -> list[str]:
    done = []
    conn.execute("SELECT pg_advisory_lock(%s)", (LOCK_ID,))
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "version TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())"
        )
        applied = {row[0] for row in conn.execute("SELECT version FROM schema_migrations")}
        for path in pending_migrations(applied):
            with conn.transaction():
                conn.execute(path.read_text())
                conn.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (path.stem,))
            done.append(path.stem)
    finally:
        conn.execute("SELECT pg_advisory_unlock(%s)", (LOCK_ID,))
    return done


def main() -> None:
    settings = load_settings()
    with connect(settings.database_url) as conn:
        done = migrate(conn)
    print("applied: " + ", ".join(done) if done else "up to date")


if __name__ == "__main__":
    main()
