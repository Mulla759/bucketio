from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from bucketio import db
from bucketio.identity import create_contact, get_or_create_company
from bucketio.normalize import normalize_name
from bucketio.report import build_report


def _add_lookup(
    conn,
    *,
    route="treg_find",
    status="valid",
    cost=0.0,
    saved=0.0,
    age_days=None,
    created_at=None,
    contact_id=None,
):
    columns = (
        "contact_id, input_name, input_company, route, result_status, "
        "cost_usd, est_saved_usd, laya_mode, created_at"
    )
    if created_at is not None:
        cursor = conn.execute(
            f"INSERT INTO lookups ({columns}) VALUES (?, 'Jane Doe', 'Acme Inc', ?, ?, ?, ?, 'off', ?)",
            (contact_id, route, status, cost, saved, created_at),
        )
    elif age_days is not None:
        cursor = conn.execute(
            f"INSERT INTO lookups ({columns}) VALUES (?, 'Jane Doe', 'Acme Inc', ?, ?, ?, ?, 'off', datetime('now', ?))",
            (contact_id, route, status, cost, saved, f"-{int(age_days)} days"),
        )
    else:
        cursor = conn.execute(
            f"INSERT INTO lookups ({columns}) VALUES (?, 'Jane Doe', 'Acme Inc', ?, ?, ?, ?, 'off', datetime('now'))",
            (contact_id, route, status, cost, saved),
        )
    conn.commit()
    return int(cursor.lastrowid)


def _add_call(conn, lookup_id, kind, cost=0.0):
    conn.execute(
        """
        INSERT INTO treg_calls (lookup_id, kind, request, status, raw_json, cost_usd)
        VALUES (?, ?, 'req', 'valid', '{}', ?)
        """,
        (lookup_id, kind, cost),
    )
    conn.commit()


def _add_decision(conn, lookup_id, question, answer, truth, error=None):
    conn.execute(
        """
        INSERT INTO laya_decisions (lookup_id, question, answer, truth, error)
        VALUES (?, ?, ?, ?, ?)
        """,
        (lookup_id, question, answer, truth, error),
    )
    conn.commit()


def _add_contact(conn, name, company):
    with db.tx(conn):
        company_id = get_or_create_company(conn, company)
        return create_contact(conn, normalize_name(name), company_id)


def test_empty_database_report(conn):
    built = build_report(conn)

    assert built.fetches == 0
    assert built.routes == {}
    assert built.find_calls == 0
    assert built.verify_calls == 0
    assert built.est_saved_usd == 0.0
    assert built.cost_usd == 0.0
    assert built.contacts == 0
    assert built.laya_agreement is None
    assert built.laya_samples == 0
    assert built.to_json() == {
        "fetches": 0,
        "routes": {},
        "treg": {"find_calls": 0, "verify_calls": 0, "cost_usd": 0.0},
        "est_saved_usd": 0.0,
        "contacts": 0,
        "laya": {"agreement": None, "samples": 0},
    }


def test_totals_routes_and_calls(conn):
    first = _add_lookup(conn, route="treg_find", cost=0.004834, saved=0.0)
    _add_call(conn, first, "find", 0.004834)
    second = _add_lookup(conn, route="pattern_verify", cost=0.0015, saved=0.003334)
    _add_call(conn, second, "verify", 0.0015)
    _add_lookup(conn, route="cache_hit", cost=0.0, saved=0.004834)

    built = build_report(conn)

    assert built.fetches == 3
    assert built.routes == {"treg_find": 1, "pattern_verify": 1, "cache_hit": 1}
    assert built.find_calls == 1
    assert built.verify_calls == 1
    assert built.cost_usd == pytest.approx(0.006334)
    assert built.est_saved_usd == pytest.approx(0.008168)
    payload = built.to_json()
    assert payload["treg"] == {
        "find_calls": 1,
        "verify_calls": 1,
        "cost_usd": pytest.approx(0.006334),
    }


def test_since_relative_window_filters_lookups_and_calls(conn):
    old = _add_lookup(conn, route="treg_find", cost=0.5, saved=0.0, age_days=30)
    _add_call(conn, old, "find", 0.5)
    recent = _add_lookup(conn, route="cache_hit", cost=0.001, saved=0.5)
    _add_call(conn, recent, "verify", 0.001)

    built = build_report(conn, since="7d")

    assert built.fetches == 1
    assert built.routes == {"cache_hit": 1}
    assert built.find_calls == 0
    assert built.verify_calls == 1
    assert built.cost_usd == pytest.approx(0.001)
    assert built.est_saved_usd == pytest.approx(0.5)


def test_since_relative_hours(conn):
    _add_lookup(conn, route="treg_find", age_days=2)
    _add_lookup(conn, route="cache_hit")

    assert build_report(conn, since="24h").fetches == 1
    assert build_report(conn, since="72h").fetches == 2


def test_since_iso_date_filters(conn):
    _add_lookup(conn, route="treg_find", age_days=10)
    _add_lookup(conn, route="cache_hit")
    cutoff = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")

    built = build_report(conn, since=cutoff)

    assert built.fetches == 1
    assert built.routes == {"cache_hit": 1}


def test_since_iso_datetime_filters(conn):
    _add_lookup(conn, route="treg_find", created_at="2020-01-01 00:00:00")
    _add_lookup(conn, route="cache_hit", created_at="2030-01-01 00:00:00")

    built = build_report(conn, since="2025-06-01T12:30:00")

    assert built.fetches == 1
    assert built.routes == {"cache_hit": 1}


@pytest.mark.parametrize("bad", ["", "yesterday", "7x", "-3d", "0d", "2026-13-45", "abc"])
def test_bad_since_raises_value_error(conn, bad):
    with pytest.raises(ValueError):
        build_report(conn, since=bad)


def test_contacts_excludes_merged(conn):
    keep = _add_contact(conn, "Jane Doe", "Acme Inc")
    _add_contact(conn, "John Smith", "Acme Inc")
    conn.execute("UPDATE contacts SET merged_into = ? WHERE id != ?", (keep, keep))
    conn.commit()

    assert build_report(conn).contacts == 1


def test_laya_agreement_mixed_truths(conn):
    lookup = _add_lookup(conn, route="pattern_verify")
    _add_decision(conn, lookup, "identity", "A", "valid")  # match
    _add_decision(conn, lookup, "identity", "B", "valid")  # miss
    _add_decision(conn, lookup, "rank", "c1", "c1")  # match
    _add_decision(conn, lookup, "rank", "c2", "c1")  # miss
    _add_decision(conn, lookup, "route", "A", "agree")  # match
    _add_decision(conn, lookup, "route", "B", "disagree")  # miss
    _add_decision(conn, lookup, "plausible", "A", None)  # no truth: excluded
    _add_decision(conn, lookup, "plausible", "A", "valid", error="timeout")  # still judged

    built = build_report(conn)

    assert built.laya_samples == 7
    assert built.laya_agreement == pytest.approx(4 / 7)


def test_laya_agreement_none_without_truth(conn):
    lookup = _add_lookup(conn)
    _add_decision(conn, lookup, "identity", "A", None)
    _add_decision(conn, lookup, "rank", "c1", None)

    built = build_report(conn)

    assert built.laya_samples == 0
    assert built.laya_agreement is None


def test_laya_agreement_respects_since(conn):
    old = _add_lookup(conn, age_days=30)
    _add_decision(conn, old, "identity", "A", "valid")
    recent = _add_lookup(conn)
    _add_decision(conn, recent, "identity", "B", "valid")

    built = build_report(conn, since="7d")

    assert built.laya_samples == 1
    assert built.laya_agreement == 0.0


def test_uninterpretable_rank_truth_is_excluded(conn):
    lookup = _add_lookup(conn)
    _add_decision(conn, lookup, "rank", "c1", "valid")

    built = build_report(conn)

    assert built.laya_samples == 0
    assert built.laya_agreement is None
