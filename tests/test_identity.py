from __future__ import annotations

import pytest

from bucketio import db
from bucketio.identity import (
    MatchResult,
    create_contact,
    find_contact_by_email,
    get_or_create_company,
    resolve_contact,
    touch_seen,
)
from bucketio.normalize import normalize_name


def test_bob_and_robert_resolve_to_one_contact(conn):
    company_id = get_or_create_company(conn, "Acme Inc")
    bob = normalize_name("Bob Smith")

    first = resolve_contact(conn, bob, company_id)
    assert first == MatchResult(None, "new", first.score)
    assert first.contact_id is None and first.gray_zone is False

    contact_id = create_contact(conn, bob, company_id)

    second = resolve_contact(conn, normalize_name("Robert Smith"), company_id)
    assert second.contact_id == contact_id
    assert second.method == "exact"

    third = resolve_contact(conn, normalize_name("Bob Smith"), company_id)
    assert third.contact_id == contact_id

    count = conn.execute(
        "SELECT COUNT(*) AS n FROM contacts WHERE company_id = ?", (company_id,)
    ).fetchone()["n"]
    assert count == 1


def test_same_person_two_companies_is_two_contacts(conn):
    acme = get_or_create_company(conn, "Acme Inc")
    globex = get_or_create_company(conn, "Globex Inc")
    assert acme != globex

    jane = normalize_name("Jane Doe")
    acme_contact = create_contact(conn, jane, acme)
    globex_contact = create_contact(conn, jane, globex)
    assert acme_contact != globex_contact

    assert resolve_contact(conn, jane, acme).contact_id == acme_contact
    assert resolve_contact(conn, jane, globex).contact_id == globex_contact


def test_touch_seen_increments_count(conn):
    company_id = get_or_create_company(conn, "Acme Inc")
    contact_id = create_contact(conn, normalize_name("Jane Doe"), company_id)

    row = conn.execute(
        "SELECT seen_count FROM contacts WHERE id = ?", (contact_id,)
    ).fetchone()
    assert row["seen_count"] == 1

    touch_seen(conn, contact_id)
    row = conn.execute(
        "SELECT seen_count, last_seen_at FROM contacts WHERE id = ?", (contact_id,)
    ).fetchone()
    assert row["seen_count"] == 2
    assert row["last_seen_at"] is not None


def test_fuzzy_rule_matches_at_95(conn):
    company_id = get_or_create_company(conn, "Acme Inc")
    existing = create_contact(conn, normalize_name("Doe Jane"), company_id)

    result = resolve_contact(conn, normalize_name("Jane Doe"), company_id)
    assert result.method == "fuzzy_rule"
    assert result.contact_id == existing
    assert result.score == pytest.approx(100.0)
    assert result.gray_zone is False


def test_gray_zone_creates_nothing(conn):
    company_id = get_or_create_company(conn, "Acme Inc")
    create_contact(conn, normalize_name("Jane Doe"), company_id)

    result = resolve_contact(conn, normalize_name("Jane Do"), company_id)
    assert result.contact_id is None
    assert result.method == "new"
    assert result.gray_zone is True
    assert 80.0 <= result.score < 95.0

    count = conn.execute(
        "SELECT COUNT(*) AS n FROM contacts WHERE company_id = ?", (company_id,)
    ).fetchone()["n"]
    assert count == 1


def test_low_fuzzy_score_is_new_without_gray_zone(conn):
    company_id = get_or_create_company(conn, "Acme Inc")
    create_contact(conn, normalize_name("Jane Doe"), company_id)

    result = resolve_contact(conn, normalize_name("Zzz Qqq"), company_id)
    assert result.contact_id is None
    assert result.method == "new"
    assert result.gray_zone is False
    assert result.score < 80.0


def test_company_alias_merges_variants(conn):
    first = get_or_create_company(conn, "ACME Corp")
    second = get_or_create_company(conn, "Acme Inc")
    assert first == second

    rows = conn.execute(
        "SELECT alias_key FROM company_aliases WHERE company_id = ?", (first,)
    ).fetchall()
    assert {row["alias_key"] for row in rows} == {"acme"}
    name = conn.execute("SELECT name FROM companies WHERE id = ?", (first,)).fetchone()
    assert name["name"] == "ACME Corp"


def test_company_reused_by_domain_and_alias_added(conn):
    acme = get_or_create_company(conn, "Acme Inc", "acme.com")
    other = get_or_create_company(conn, "Globex", "ACME.com")
    assert other == acme

    row = conn.execute("SELECT domain FROM companies WHERE id = ?", (acme,)).fetchone()
    assert row["domain"] == "acme.com"

    alias = conn.execute(
        "SELECT company_id FROM company_aliases WHERE alias_key = 'globex'"
    ).fetchone()
    assert alias["company_id"] == acme


def test_company_domain_backfilled_when_null(conn):
    company_id = get_or_create_company(conn, "Acme Inc")
    row = conn.execute(
        "SELECT domain FROM companies WHERE id = ?", (company_id,)
    ).fetchone()
    assert row["domain"] is None

    again = get_or_create_company(conn, "Acme Inc", "acme.com")
    assert again == company_id
    row = conn.execute(
        "SELECT domain, updated_at FROM companies WHERE id = ?", (company_id,)
    ).fetchone()
    assert row["domain"] == "acme.com"
    assert row["updated_at"] is not None


def test_find_contact_by_email_case_insensitive(conn):
    company_id = get_or_create_company(conn, "Acme Inc")
    contact_id = create_contact(conn, normalize_name("Jane Doe"), company_id)
    conn.execute(
        "UPDATE contacts SET email = ? WHERE id = ?",
        ("jane.doe@acme.com", contact_id),
    )

    assert find_contact_by_email(conn, "JANE.DOE@ACME.COM") == contact_id
    assert find_contact_by_email(conn, "nobody@acme.com") is None


def test_find_contact_by_email_skips_merged(conn):
    company_id = get_or_create_company(conn, "Acme Inc")
    target = create_contact(conn, normalize_name("John Jones"), company_id)
    merged = create_contact(conn, normalize_name("Bob Smith"), company_id)
    conn.execute(
        "UPDATE contacts SET email = ?, merged_into = ? WHERE id = ?",
        ("bob@acme.com", target, merged),
    )

    assert find_contact_by_email(conn, "bob@acme.com") is None


def test_writes_participate_in_caller_transaction(conn):
    with db.tx(conn) as c:
        company_id = get_or_create_company(c, "Acme Inc")
        create_contact(c, normalize_name("Jane Doe"), company_id)

    assert conn.execute("SELECT COUNT(*) AS n FROM contacts").fetchone()["n"] == 1

    with pytest.raises(RuntimeError):
        with db.tx(conn) as c:
            get_or_create_company(c, "Rollback Inc")
            create_contact(c, normalize_name("Roll Back"), 1)
            raise RuntimeError("boom")

    assert conn.execute("SELECT COUNT(*) AS n FROM companies").fetchone()["n"] == 1
    assert conn.execute("SELECT COUNT(*) AS n FROM contacts").fetchone()["n"] == 1
