# SQLite connection + migration runner for the sorter's own SQLite database. WAL so the
# API can read while a pipeline run is still writing. Migrations are idempotent (IF NOT EXISTS).
from __future__ import annotations

import glob
import os
import sqlite3

MIGRATIONS_DIR = os.path.join(os.path.dirname(__file__), "migrations")


def connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")  # coexist with a concurrent pipeline writer
    return conn


def migrate(conn: sqlite3.Connection, migrations_dir: str = MIGRATIONS_DIR) -> None:
    """Apply each *.sql once, tracked in schema_migrations. Tracking lets a migration use a
    non-idempotent statement (e.g. ALTER TABLE ADD COLUMN, which SQLite has no IF NOT EXISTS for)
    safely: it runs exactly once and is skipped on every later open."""
    conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (filename TEXT PRIMARY KEY, applied_at INTEGER)")
    applied = {r[0] for r in conn.execute("SELECT filename FROM schema_migrations").fetchall()}
    for path in sorted(glob.glob(os.path.join(migrations_dir, "*.sql"))):
        name = os.path.basename(path)
        if name in applied:
            continue
        with open(path, encoding="utf-8") as fh:
            conn.executescript(fh.read())
        conn.execute("INSERT OR IGNORE INTO schema_migrations (filename) VALUES (?)", (name,))
    conn.commit()


def open_db(db_path: str) -> sqlite3.Connection:
    """Connect + run migrations. Use ':memory:' in tests."""
    conn = connect(db_path)
    migrate(conn)
    return conn
