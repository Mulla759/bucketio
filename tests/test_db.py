from __future__ import annotations

from bucketio import db

EXPECTED_TABLES = {
    "schema_version",
    "companies",
    "company_aliases",
    "contacts",
    "domain_patterns",
    "pattern_priors",
    "lookups",
    "treg_calls",
    "candidates",
    "laya_decisions",
    "laya_calibration",
}


def test_migrate_creates_all_tables(conn):
    assert EXPECTED_TABLES <= db.table_names(conn)


def test_migrate_seeds_priors(conn):
    rows = conn.execute("SELECT pattern, prior FROM pattern_priors").fetchall()
    priors = {r["pattern"]: r["prior"] for r in rows}
    assert len(priors) == 12
    assert priors["first.last"] == 0.40
    assert priors["flast"] == 0.18


def test_migrate_records_schema_version(conn):
    row = conn.execute("SELECT version FROM schema_version").fetchone()
    assert row["version"] == db.SCHEMA_VERSION


def test_migrate_is_idempotent(db_path):
    first = db.migrate(db_path)
    first.close()
    second = db.migrate(db_path)
    try:
        assert len(db.table_names(second)) == len(EXPECTED_TABLES)
        count = second.execute("SELECT COUNT(*) AS n FROM pattern_priors").fetchone()["n"]
        assert count == 12
        versions = second.execute("SELECT COUNT(*) AS n FROM schema_version").fetchone()["n"]
        assert versions == 1
    finally:
        second.close()


def test_wal_mode_enabled(conn):
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode.lower() == "wal"


def test_tx_rolls_back_on_error(conn):
    try:
        with db.tx(conn) as c:
            c.execute("INSERT INTO pattern_priors (pattern, prior) VALUES ('boom', 1.0)")
            raise RuntimeError("nope")
    except RuntimeError:
        pass
    row = conn.execute("SELECT 1 FROM pattern_priors WHERE pattern='boom'").fetchone()
    assert row is None
