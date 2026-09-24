"""SQLite access: connection, migration runner, transactions.

One schema (bucketio/schema.sql) applied by a tiny versioned runner.
Safe to call migrate() on every startup: it is idempotent.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from importlib import resources
from pathlib import Path
from typing import Iterator

SCHEMA_VERSION = 1

PATTERN_PRIORS: dict[str, float] = {
    "first.last": 0.40,
    "flast": 0.18,
    "first": 0.10,
    "firstlast": 0.06,
    "f.last": 0.05,
    "first_last": 0.04,
    "firstl": 0.04,
    "last.first": 0.03,
    "lastf": 0.03,
    "last": 0.02,
    "first-last": 0.02,
    "fl": 0.03,
}


def schema_sql() -> str:
    return resources.files("bucketio").joinpath("schema.sql").read_text(encoding="utf-8")


def connect(db_path: Path | str | None = None, *, read_only: bool = False) -> sqlite3.Connection:
    """Open a connection with the PRAGMAs BucketIO relies on."""
    from .config import get_settings

    path = Path(db_path) if db_path is not None else get_settings().db_path
    if read_only:
        uri = f"file:{path.as_posix()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=5.0)
    else:
        conn = sqlite3.connect(path, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    if not read_only:
        conn.execute("PRAGMA journal_mode = WAL")
    return conn


def migrate(db_path: Path | str | None = None, conn: sqlite3.Connection | None = None) -> sqlite3.Connection:
    """Apply schema.sql and seed pattern priors. Idempotent.

    Returns an open connection; the caller owns it (and should close it).
    """
    conn = conn or connect(db_path)
    conn.executescript(schema_sql())
    row = conn.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
    if row is None:
        conn.execute("INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,))
    conn.executemany(
        "INSERT OR IGNORE INTO pattern_priors (pattern, prior) VALUES (?, ?)",
        sorted(PATTERN_PRIORS.items()),
    )
    conn.commit()
    return conn


@contextmanager
def tx(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Transaction context: commit on success, rollback on error."""
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise


def table_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    return {r["name"] for r in rows}
