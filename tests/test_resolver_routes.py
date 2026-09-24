from __future__ import annotations

import json
from pathlib import Path

import pytest

from bucketio import db, patterns, resolver
from bucketio.config import Settings
from bucketio.identity import get_or_create_company
from bucketio.patterns import record_outcome
from bucketio.resolver import fetch, to_json
from bucketio.treg import TregMockClient

FIXTURE = Path(__file__).parent / "fixtures" / "treg_mock.json"
ACME = "acme.com"
UMBRELLA = "umbrella.com"


@pytest.fixture()
def settings(tmp_path, monkeypatch):
    built = Settings(
        _env_file=None,
        db_path=tmp_path / "test.db",
        treg_mode="mock",
        laya_mode="off",
        treg_find_cost=0.004834,
        treg_verify_cost=0.0015,
        cache_ttl_days=90,
        verify_min_posterior=0.60,
        verify_min_hits=2,
        verify_max_tries=2,
        generate_verify_top=True,
    )
    monkeypatch.setattr(resolver, "get_settings", lambda: built)
    return built


@pytest.fixture()
def client(settings):
    return TregMockClient(path=FIXTURE, settings=settings)


def test_1_first_fetch_jane_is_treg_find(conn, client):
    result = fetch(conn, "Jane Doe", "Acme Inc", client=client)

    assert result.route == "treg_find"
    assert result.treg_calls == {"find": 1, "verify": 0}
    assert result.email == "jane.doe@acme.com"
    assert result.verification_status == "valid"
    assert result.domain == "acme.com"
    assert result.identity_method == "new"
    assert result.seen_count == 1
    assert result.cost_usd == pytest.approx(0.004834)
    assert result.est_cost_saved == 0.0
    assert result.contact_id > 0
    assert result.lookup_id > 0


def test_2_second_person_still_finds_until_two_verified_hits(conn, client):
    fetch(conn, "Jane Doe", "Acme Inc", client=client)
    best = patterns.best_pattern(conn, ACME)
    assert best is not None and best[0] == "first.last" and best[2] == 1

    result = fetch(conn, "John Smith", "Acme", client=client)
    assert result.route == "treg_find"
    assert result.treg_calls == {"find": 1, "verify": 0}
    assert result.email == "john.smith@acme.com"
    assert result.verification_status == "valid"


def test_3_third_person_uses_pattern_verify(conn, client):
    fetch(conn, "Jane Doe", "Acme Inc", client=client)
    fetch(conn, "John Smith", "Acme", client=client)

    result = fetch(conn, "Mary Jones", "Acme Inc", client=client)
    assert result.route == "pattern_verify"
    assert result.treg_calls == {"find": 0, "verify": 1}
    assert result.email == "mary.jones@acme.com"
    assert result.verification_status == "valid"
    assert result.est_cost_saved == pytest.approx(0.004834 - 0.0015)

    call = conn.execute(
        "SELECT kind, request, status FROM treg_calls ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert (call["kind"], call["request"], call["status"]) == (
        "verify",
        "mary.jones@acme.com",
        "valid",
    )


def test_4_refetch_jane_is_cache_hit_with_seen_count_2(conn, client):
    fetch(conn, "Jane Doe", "Acme Inc", client=client)
    result = fetch(conn, "Jane Doe", "Acme Inc", client=client)

    assert result.route == "cache_hit"
    assert result.treg_calls == {"find": 0, "verify": 0}
    assert result.email == "jane.doe@acme.com"
    assert result.verification_status == "valid"
    assert result.identity_method == "exact"
    assert result.seen_count == 2
    assert result.cost_usd == 0.0
    assert result.est_cost_saved == pytest.approx(0.004834)


def test_5_catch_all_domain_skips_verifies(conn, client):
    first = fetch(conn, "Peter Gibbons", "Initech", client=client)
    assert first.route == "treg_find"
    assert first.verification_status == "catch_all"
    assert first.email == "peter.gibbons@initech.com"

    row = conn.execute(
        "SELECT is_catch_all FROM companies WHERE domain = 'initech.com'"
    ).fetchone()
    assert row["is_catch_all"] == 1

    second = fetch(conn, "Milton Waddams", "Initech", client=client)
    assert second.route == "catch_all"
    assert second.treg_calls == {"find": 0, "verify": 0}
    assert second.verification_status == "catch_all"
    assert second.email == "milton.waddams@initech.com"
    assert second.est_cost_saved == pytest.approx(0.004834)

    total = conn.execute("SELECT COUNT(*) AS n FROM treg_calls").fetchone()["n"]
    assert total == 1


def test_6_ghost_domain_generates_candidates(conn, client):
    result = fetch(conn, "Casper Ghost", "Ghost Co", client=client)

    assert result.route == "generate"
    assert result.domain == "ghost.co"
    assert result.email is not None and result.email.endswith("@ghost.co")
    assert result.high_pattern_email == result.email
    assert result.confidence is not None and result.confidence < 0.5
    assert len(result.alternates) == 5
    assert len(set(result.alternates)) == 5
    assert result.verification_status == "pattern_guess"
    assert result.treg_calls == {"find": 1, "verify": 1}


def test_7_invalid_verify_falls_to_next_pattern(conn, client):
    with db.tx(conn):
        get_or_create_company(conn, "Umbrella", "umbrella.com")
        for _ in range(3):
            record_outcome(conn, UMBRELLA, "first.last", "valid", verified=True)
        record_outcome(conn, UMBRELLA, "flast", "valid", verified=True)

    result = fetch(conn, "Zed Zulu", "Umbrella", client=client)

    assert result.route == "pattern_verify"
    assert result.treg_calls == {"find": 0, "verify": 2}
    assert result.email == "zzulu@umbrella.com"
    assert result.verification_status == "valid"
    assert result.domain == "umbrella.com"

    row = conn.execute(
        "SELECT misses FROM domain_patterns WHERE domain = ? AND pattern = 'first.last'",
        (UMBRELLA,),
    ).fetchone()
    assert row["misses"] == 1

    requests = [
        r["request"]
        for r in conn.execute("SELECT request FROM treg_calls ORDER BY id").fetchall()
    ]
    assert requests == ["zed.zulu@umbrella.com", "zzulu@umbrella.com"]


def test_8_force_bypasses_cache(conn, client):
    fetch(conn, "Jane Doe", "Acme Inc", client=client)
    result = fetch(conn, "Jane Doe", "Acme Inc", force=True, client=client)

    assert result.route != "cache_hit"
    assert result.treg_calls["find"] + result.treg_calls["verify"] >= 1
    assert result.seen_count == 2

    row = conn.execute("SELECT forced FROM lookups ORDER BY id DESC LIMIT 1").fetchone()
    assert row["forced"] == 1


def test_9_non_latin_name_resolves(conn, client):
    result = fetch(conn, "Анна Иванова", "Acme Inc", client=client)

    assert result.name == "Анна Иванова"
    assert result.email == "anna.ivanova@acme.com"
    assert result.verification_status == "valid"
    assert result.route in {"treg_find", "pattern_verify"}


def test_10_lookup_treg_call_and_candidate_rows_are_recorded(conn, client):
    result = fetch(conn, "Casper Ghost", "Ghost Co", client=client)

    lookup = conn.execute(
        "SELECT * FROM lookups WHERE id = ?", (result.lookup_id,)
    ).fetchone()
    assert lookup["route"] == "generate"
    assert lookup["identity_method"] == "new"
    assert lookup["laya_mode"] == "off"
    assert lookup["forced"] == 0
    assert lookup["result_email"] == result.email
    assert lookup["cost_usd"] == pytest.approx(result.cost_usd)
    assert lookup["est_saved_usd"] == pytest.approx(result.est_cost_saved)
    assert conn.execute("SELECT COUNT(*) AS n FROM lookups").fetchone()["n"] == 1

    calls = conn.execute(
        "SELECT * FROM treg_calls WHERE lookup_id = ? ORDER BY id", (result.lookup_id,)
    ).fetchall()
    assert len(calls) == 2
    assert [c["kind"] for c in calls] == ["find", "verify"]
    for call in calls:
        assert isinstance(json.loads(call["raw_json"]), dict)

    candidates = conn.execute(
        "SELECT * FROM candidates WHERE lookup_id = ? ORDER BY rank",
        (result.lookup_id,),
    ).fetchall()
    assert [c["rank"] for c in candidates] == [1, 2, 3, 4, 5, 6]
    assert candidates[0]["email"] == result.high_pattern_email
    assert candidates[0]["final_score"] == pytest.approx(candidates[0]["rules_score"])
    assert candidates[0]["outcome"] == "invalid"
    assert all(c["outcome"] is None for c in candidates[1:])


def test_generate_without_domain_returns_no_domain(conn, client):
    result = fetch(conn, "Zed Zulu", "Hoax LLC", client=client)

    assert result.route == "generate"
    assert result.verification_status == "no_domain"
    assert result.domain is None
    assert result.email is None
    assert result.high_pattern_email is None
    assert result.alternates == []
    assert result.treg_calls == {"find": 1, "verify": 0}
    # Free not_found miss: the §3.3 formula still credits find_cost - cost_usd.
    assert result.est_cost_saved == pytest.approx(0.004834)


def test_expired_cache_ttl_falls_through(conn, client):
    fetch(conn, "Jane Doe", "Acme Inc", client=client)
    conn.execute("UPDATE contacts SET last_verified_at = datetime('now', '-100 days')")
    conn.commit()

    result = fetch(conn, "Jane Doe", "Acme Inc", client=client)
    assert result.route != "cache_hit"
    assert result.treg_calls["find"] + result.treg_calls["verify"] >= 1


def test_to_json_has_exact_prd_keys(conn, client):
    result = fetch(conn, "Jane Doe", "Acme Inc", client=client)
    payload = to_json(result)

    assert set(payload) == {
        "contact_id",
        "name",
        "company",
        "domain",
        "email",
        "verification_status",
        "high_pattern_email",
        "alternates",
        "confidence",
        "route",
        "treg_calls",
        "seen_count",
        "est_cost_saved",
    }
    assert payload["name"] == "Jane Doe"
    assert payload["company"] == "Acme Inc"
    assert payload["treg_calls"] == {"find": 1, "verify": 0}
    assert json.loads(json.dumps(payload)) == payload
