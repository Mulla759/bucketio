from __future__ import annotations

import io
import threading
from pathlib import Path

import pytest
from typer.testing import CliRunner

from bucketio import config, csv_io, db, resolver
from bucketio.cli import app
from bucketio.config import Settings
from bucketio.resolver import fetch
from bucketio.treg import TregMockClient

FIXTURE = Path(__file__).parent / "fixtures" / "treg_mock.json"


@pytest.fixture()
def settings(tmp_path, monkeypatch):
    built = Settings(
        _env_file=None,
        db_path=tmp_path / "test.db",
        treg_mode="mock",
        laya_mode="off",
        treg_find_cost=0.004834,
        treg_verify_cost=0.0015,
    )
    monkeypatch.setattr(resolver, "get_settings", lambda: built)
    monkeypatch.setattr(config, "get_settings", lambda: built)
    return built


def _client(settings):
    return TregMockClient(path=FIXTURE, settings=settings)


PEOPLE = [
    ("Jane Doe", "Acme Inc"),
    ("John Smith", "Acme"),
    ("Mary Jones", "Acme Inc"),
    ("Sam Smith", "Globex"),
    ("Jane Doe", "Globex"),
    ("Peter Gibbons", "Initech"),
    ("Casper Ghost", "Ghost Co"),
] * 3


def test_twenty_parallel_fetches_no_lock_errors(db_path, settings):
    db.migrate(db_path).close()
    results: list = []
    errors: list = []
    guard = threading.Lock()

    def worker(name: str, company: str) -> None:
        conn = db.connect(db_path)
        try:
            result = fetch(conn, name, company, client=_client(settings))
            with guard:
                results.append(result)
        except Exception as exc:  # noqa: BLE001 - the point is to surface any error
            with guard:
                errors.append(exc)
        finally:
            conn.close()

    threads = [threading.Thread(target=worker, args=args) for args in PEOPLE]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert len(results) == len(PEOPLE)
    assert all(result.email for result in results)


def test_same_fetch_in_flight_pays_once(db_path, settings):
    db.migrate(db_path).close()
    errors: list = []

    def worker() -> None:
        conn = db.connect(db_path)
        try:
            fetch(conn, "Jane Doe", "Acme Inc", client=_client(settings))
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)
        finally:
            conn.close()

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    conn = db.connect(db_path)
    try:
        finds = conn.execute(
            "SELECT COUNT(*) AS n FROM treg_calls WHERE kind = 'find'"
        ).fetchone()["n"]
        lookups = conn.execute("SELECT COUNT(*) AS n FROM lookups").fetchone()["n"]
    finally:
        conn.close()
    assert finds == 1
    assert lookups == 8


def test_unmerge_command(db_path, settings):
    conn = db.migrate(db_path)
    with db.tx(conn):
        conn.execute(
            "INSERT INTO companies (name, company_key) VALUES ('Acme', 'acme')"
        )
        first = conn.execute(
            """
            INSERT INTO contacts (full_name, name_key, company_id)
            VALUES ('Jane Doe', 'jane doe', 1)
            """
        ).lastrowid
        second = conn.execute(
            """
            INSERT INTO contacts (full_name, name_key, company_id, merged_into)
            VALUES ('Jane Do', 'jane do', 1, ?)
            """,
            (first,),
        ).lastrowid
    conn.close()

    runner = CliRunner()
    result = runner.invoke(app, ["unmerge", str(second)])
    assert result.exit_code == 0, result.output
    assert "Unmerged" in result.output

    conn = db.connect(db_path)
    try:
        merged = conn.execute(
            "SELECT merged_into FROM contacts WHERE id = ?", (second,)
        ).fetchone()["merged_into"]
    finally:
        conn.close()
    assert merged is None

    again = runner.invoke(app, ["unmerge", str(second)])
    assert again.exit_code == 0
    assert "not merged" in again.output


def test_export_respects_do_not_contact(db_path, settings):
    conn = db.migrate(db_path)
    with db.tx(conn):
        conn.execute(
            "INSERT INTO companies (name, company_key) VALUES ('Acme', 'acme')"
        )
        conn.execute(
            """
            INSERT INTO contacts (full_name, name_key, company_id, email, do_not_contact)
            VALUES ('Keep Me', 'keep me', 1, 'keep@acme.com', 0)
            """
        )
        conn.execute(
            """
            INSERT INTO contacts (full_name, name_key, company_id, email, do_not_contact)
            VALUES ('Leave Me', 'leave me', 1, 'leave@acme.com', 1)
            """
        )
    buffer = io.StringIO()
    count = csv_io.export_contacts(conn, buffer)
    conn.close()

    assert count == 1
    text = buffer.getvalue()
    assert "keep@acme.com" in text
    assert "leave@acme.com" not in text


def test_calibrate_command_without_data(db_path, settings):
    db.migrate(db_path).close()
    result = CliRunner().invoke(app, ["calibrate"])
    assert result.exit_code == 0, result.output
    assert "No labelled Laya decisions" in result.output
