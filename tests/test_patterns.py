from __future__ import annotations

import pytest

from bucketio import db
from bucketio.normalize import NameParts, normalize_name
from bucketio.patterns import (
    ALPHA,
    PATTERNS,
    best_pattern,
    candidates,
    pattern_stats,
    posterior,
    record_outcome,
    render,
    render_variants,
    reprior,
    reverse_match,
    seed_priors,
)

JANE = normalize_name("Jane Doe")
JANE_VDB = normalize_name("Jane van der Berg")
ACME = "acme.com"


def test_patterns_exact_order():
    assert PATTERNS == (
        "first.last",
        "flast",
        "first",
        "firstlast",
        "first_last",
        "f.last",
        "firstl",
        "last.first",
        "lastf",
        "last",
        "first-last",
        "fl",
    )


def test_render_first_last():
    assert render("first.last", JANE) == "jane.doe"
    assert render("first", JANE) == "jane"
    assert render("flast", JANE) == "jdoe"
    assert render("last.first", JANE) == "doe.jane"
    assert render("fl", JANE) == "jd"


def test_reverse_match_expected_patterns():
    assert reverse_match("jane.doe", JANE) == ["first.last"]
    assert reverse_match("jdoe", JANE) == ["flast"]
    assert reverse_match("Jane.Doe", JANE) == ["first.last"]
    assert reverse_match("jd", JANE) == ["fl"]
    assert reverse_match("nope@x", JANE) == []


def test_render_variants_joined_and_token_last():
    assert render_variants("first.last", JANE_VDB) == ["jane.vanderberg", "jane.berg"]
    assert render_variants("flast", JANE_VDB) == ["jvanderberg", "jberg"]
    assert render("first.last", JANE_VDB) == "jane.vanderberg"
    assert reverse_match("jane.berg", JANE_VDB) == ["first.last"]
    assert reverse_match("jvanderberg", JANE_VDB) == ["flast"]


def test_render_none_when_last_missing():
    parts = NameParts(
        full_name="Madonna",
        first="madonna",
        middle=None,
        last="",
        name_key="madonna madonna",
        initials="m",
        last_variants=(),
    )
    assert render("first.last", parts) is None
    assert render("last", parts) is None
    assert render("fl", parts) is None
    assert render("first", parts) == "madonna"
    assert render_variants("first.last", parts) == []
    assert reverse_match("madonna", parts) == ["first"]


def test_posterior_uses_prior_and_counts(conn):
    expected = (0 + ALPHA * 0.40) / (0 + ALPHA)
    assert posterior(conn, ACME, "first.last") == pytest.approx(expected)

    with db.tx(conn):
        record_outcome(conn, ACME, "first.last", "valid", verified=True)
    expected = (1 + ALPHA * 0.40) / (1 + ALPHA)
    assert posterior(conn, ACME, "first.last") == pytest.approx(expected)

    assert posterior(conn, ACME, "custom") == pytest.approx(0.02)


def test_three_valid_first_last_ranks_first(conn):
    with db.tx(conn):
        for _ in range(3):
            record_outcome(conn, ACME, "first.last", "valid", verified=True)

    assert posterior(conn, ACME, "first.last") > 0.6

    ranked = candidates(conn, JANE, ACME)
    assert ranked[0].pattern == "first.last"
    assert ranked[0].email == "jane.doe"
    assert len(ranked) == 5
    emails = [candidate.email for candidate in ranked]
    assert len(set(emails)) == len(emails)
    scores = [candidate.rules_score for candidate in ranked]
    assert scores == sorted(scores, reverse=True)


def test_catch_all_changes_no_counts(conn):
    with db.tx(conn):
        record_outcome(conn, "initech.com", "first.last", "valid", verified=True)
        record_outcome(conn, "initech.com", "first.last", "catch_all")

    stats = pattern_stats(conn, "initech.com")["first.last"]
    assert (stats["hits"], stats["misses"], stats["verified_hits"]) == (1, 0, 1)


def test_invalid_counts_as_miss(conn):
    with db.tx(conn):
        record_outcome(conn, ACME, "flast", "invalid")

    stats = pattern_stats(conn, ACME)["flast"]
    assert (stats["hits"], stats["misses"], stats["verified_hits"]) == (0, 1, 0)
    assert posterior(conn, ACME, "flast") < 0.18


def test_record_outcome_rejects_unknown_outcome(conn):
    with pytest.raises(ValueError):
        record_outcome(conn, ACME, "first.last", "maybe")


def test_best_pattern_none_and_after_rows(conn):
    assert best_pattern(conn, "empty.com") is None

    with db.tx(conn):
        record_outcome(conn, ACME, "first.last", "valid", verified=True)
        record_outcome(conn, ACME, "flast", "invalid")

    best = best_pattern(conn, ACME)
    assert best is not None
    pattern, value, verified_hits = best
    assert pattern == "first.last"
    assert value == posterior(conn, ACME, "first.last")
    assert verified_hits == 1


def test_reprior_noop_below_20_outcomes(conn):
    seeds = seed_priors()
    with db.tx(conn):
        for _ in range(5):
            record_outcome(conn, ACME, "flast", "valid", verified=True)
        reprior(conn)

    priors = {
        row["pattern"]: row["prior"]
        for row in conn.execute("SELECT pattern, prior FROM pattern_priors")
    }
    assert priors == pytest.approx(seeds)


def test_reprior_renormalizes_above_20_outcomes(conn):
    seeds = seed_priors()
    with db.tx(conn):
        for _ in range(25):
            record_outcome(conn, ACME, "first.last", "valid", verified=True)
        reprior(conn)

    priors = {
        row["pattern"]: row["prior"]
        for row in conn.execute("SELECT pattern, prior FROM pattern_priors")
    }
    assert priors["first.last"] > seeds["first.last"]
    assert priors["first.last"] > priors["flast"]
    assert priors["first.last"] == pytest.approx(26.0 / 37.0)


def test_candidates_tie_break_follows_pattern_order(conn):
    ranked = candidates(conn, JANE, "fresh.com", k=50)
    patterns = [candidate.pattern for candidate in ranked]
    assert patterns[0] == "first.last"
    assert patterns[1] == "flast"
    assert patterns[2] == "first"


def test_seed_priors_reexports_db_priors():
    assert seed_priors() == db.PATTERN_PRIORS
