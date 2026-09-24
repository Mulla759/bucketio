from __future__ import annotations

import csv
import io
from pathlib import Path

import pytest

from bucketio import db, identity
from bucketio.csv_io import EXPORT_HEADER, export_contacts, import_contacts
from bucketio.normalize import normalize_name


def _write_csv(tmp_path: Path, text: str, name: str = "contacts.csv") -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def _contact_row(conn, name: str, company: str):
    row = conn.execute(
        """
        SELECT c.* FROM contacts c
        JOIN companies co ON co.id = c.company_id
        WHERE c.name_key = ? AND co.name = ?
        """,
        (normalize_name(name).name_key, company),
    ).fetchone()
    assert row is not None, f"contact {name!r} at {company!r} not found"
    return row


def test_import_creates_companies_and_contacts(conn, tmp_path):
    path = _write_csv(
        tmp_path,
        "Name,Company,Email,Notes\n"
        "Jane Doe,Acme Inc,jane.doe@acme.com,vip\n"
        "John Smith,Acme Inc,,\n",
    )

    result = import_contacts(conn, path)

    assert result == {"rows": 2, "created": 2, "updated": 0, "errors": []}

    jane = _contact_row(conn, "Jane Doe", "Acme Inc")
    assert jane["email"] == "jane.doe@acme.com"
    assert jane["email_source"] == "import"
    assert jane["verification_status"] == "unverified"

    john = _contact_row(conn, "John Smith", "Acme Inc")
    assert john["email"] is None
    assert john["verification_status"] == "unverified"

    company = conn.execute(
        "SELECT * FROM companies WHERE company_key = 'acme'"
    ).fetchone()
    assert company["domain"] == "acme.com"
    assert (
        conn.execute("SELECT COUNT(*) AS n FROM companies").fetchone()["n"] == 1
    )


def test_import_tolerates_bom_case_and_extra_columns(conn, tmp_path):
    path = tmp_path / "bom.csv"
    path.write_text(
        "\ufeffname,COMPANY,e-mail,Phone\nJane Doe,Acme Inc,JANE@ACME.COM,555\n",
        encoding="utf-8",
    )

    result = import_contacts(conn, path)

    assert result["created"] == 1
    assert result["errors"] == []
    jane = _contact_row(conn, "Jane Doe", "Acme Inc")
    assert jane["email"] == "JANE@ACME.COM"


def test_import_collects_bad_rows_and_continues(conn, tmp_path):
    path = _write_csv(
        tmp_path,
        "Name,Company,Email\n"
        ",Acme Inc,x@acme.com\n"
        "No Company,,\n"
        "Jane Doe,Acme Inc,jane.doe@acme.com\n",
    )

    result = import_contacts(conn, path)

    assert result["rows"] == 3
    assert result["created"] == 1
    assert result["updated"] == 0
    assert [error["row"] for error in result["errors"]] == [2, 3]
    assert all("missing name or company" in e["error"] for e in result["errors"])
    assert _contact_row(conn, "Jane Doe", "Acme Inc")["email"] == "jane.doe@acme.com"


def test_import_updates_existing_contact(conn, tmp_path):
    path = _write_csv(tmp_path, "Name,Company,Email\nJane Doe,Acme Inc,jane.doe@acme.com\n")
    first = import_contacts(conn, path)
    second = import_contacts(conn, path)

    assert (first["created"], first["updated"]) == (1, 0)
    assert (second["created"], second["updated"]) == (0, 1)
    assert conn.execute("SELECT COUNT(*) AS n FROM contacts").fetchone()["n"] == 1
    assert second["errors"] == []


def test_import_missing_required_header_raises(conn, tmp_path):
    path = _write_csv(tmp_path, "Name,Email\nJane Doe,jane@acme.com\n")

    with pytest.raises(ValueError):
        import_contacts(conn, path)


def test_import_accepts_open_stream(conn):
    stream = io.StringIO("Name,Company\nJane Doe,Acme Inc\n")

    result = import_contacts(conn, stream)

    assert result["created"] == 1


def test_import_skips_blank_lines(conn, tmp_path):
    path = _write_csv(tmp_path, "Name,Company\n\nJane Doe,Acme Inc\n\n")

    result = import_contacts(conn, path)

    assert result["rows"] == 1
    assert result["created"] == 1


def test_export_round_trip(conn, tmp_path):
    source = _write_csv(
        tmp_path,
        "Name,Company,Email\n"
        "Jane Doe,Acme Inc,jane.doe@acme.com\n"
        "John Smith,Acme Inc,\n",
        name="in.csv",
    )
    import_contacts(conn, source)

    out = tmp_path / "out.csv"
    count = export_contacts(conn, out)

    assert count == 2
    rows = list(csv.reader(out.read_text(encoding="utf-8").splitlines()))
    assert rows[0] == list(EXPORT_HEADER)
    assert len(rows) == 3
    assert [row[0] for row in rows[1:]] == ["Jane Doe", "John Smith"]
    assert [row[1] for row in rows[1:]] == ["Acme Inc", "Acme Inc"]
    assert [row[2] for row in rows[1:]] == ["jane.doe@acme.com", ""]

    # The exported file imports cleanly into a second, empty database.
    other_path = tmp_path / "other.db"
    other = db.migrate(other_path)
    try:
        reimported = import_contacts(other, out)
    finally:
        other.close()
    assert reimported["created"] == 2
    assert reimported["errors"] == []


def test_export_skips_merged_contacts(conn, tmp_path):
    keep = _contact_row_id(conn, "Jane Doe", "Acme Inc")
    drop = _contact_row_id(conn, "John Smith", "Acme Inc")
    conn.execute("UPDATE contacts SET merged_into = ? WHERE id = ?", (keep, drop))
    conn.commit()

    out = tmp_path / "out.csv"
    count = export_contacts(conn, out)

    assert count == 1
    text = out.read_text(encoding="utf-8")
    assert "Jane Doe" in text
    assert "John Smith" not in text


def test_export_route_is_latest_lookup(conn, tmp_path):
    with db.tx(conn):
        company_id = identity.get_or_create_company(conn, "Acme Inc")
        contact_id = identity.create_contact(
            conn, normalize_name("Jane Doe"), company_id
        )
    conn.execute(
        """
        INSERT INTO lookups (contact_id, input_name, input_company, route, laya_mode, created_at)
        VALUES (?, 'Jane Doe', 'Acme Inc', 'treg_find', 'off', '2020-01-01 00:00:00')
        """,
        (contact_id,),
    )
    conn.execute(
        """
        INSERT INTO lookups (contact_id, input_name, input_company, route, laya_mode, created_at)
        VALUES (?, 'Jane Doe', 'Acme Inc', 'cache_hit', 'off', '2030-01-01 00:00:00')
        """,
        (contact_id,),
    )
    conn.commit()

    out = tmp_path / "out.csv"
    export_contacts(conn, out)

    row = list(csv.reader(out.read_text(encoding="utf-8").splitlines()))[1]
    assert row[8] == "cache_hit"


def test_export_writes_to_open_stream(conn):
    buffer = io.StringIO()

    count = export_contacts(conn, buffer)

    assert count == 0
    assert buffer.getvalue().splitlines() == [",".join(EXPORT_HEADER)]


def _contact_row_id(conn, name, company) -> int:
    with db.tx(conn):
        company_id = identity.get_or_create_company(conn, company)
        match = identity.resolve_contact(conn, normalize_name(name), company_id)
        if match.contact_id is not None:
            return match.contact_id
        return identity.create_contact(conn, normalize_name(name), company_id)
