"""Email pattern engine: rendering, reverse matching, Beta stats, candidates.

Patterns are templates over the normalized ``NameParts`` produced by
``normalize.py``. All rendered local parts are ASCII-folded lowercase.
Every write participates in the caller's transaction; nothing commits here.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass

from unidecode import unidecode

from .db import PATTERN_PRIORS
from .normalize import NameParts, fold_ascii

ALPHA = 2.0
DEFAULT_PRIOR = 0.02

PATTERNS: tuple[str, ...] = (
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

OUTCOMES: tuple[str, ...] = ("valid", "invalid", "catch_all")

_LOCAL_STRIP = re.compile(r"[^a-z0-9._-]")


def seed_priors() -> dict[str, float]:
    """The seeded global pattern priors from the schema module."""
    return dict(PATTERN_PRIORS)


def _pattern_index(pattern: str) -> int:
    try:
        return PATTERNS.index(pattern)
    except ValueError:
        return len(PATTERNS)


def _fold_local(value: str | None) -> str:
    if not value:
        return ""
    try:
        text = unidecode(value)
    except Exception:  # pragma: no cover - unidecode is very tolerant
        text = value
    return _LOCAL_STRIP.sub("", text.lower())


def _joined_lasts(name: NameParts) -> list[str]:
    variants: list[str] = []
    for variant in name.last_variants or ():
        folded = fold_ascii(variant).replace(" ", "")
        if folded and folded not in variants:
            variants.append(folded)
    if not variants:
        folded_last = fold_ascii(name.last).replace(" ", "")
        if folded_last:
            variants.append(folded_last)
    return variants


def render_variants(pattern: str, name: NameParts) -> list[str]:
    """All distinct local parts a pattern can produce for this name."""
    first = fold_ascii(name.first)
    lasts = _joined_lasts(name)
    initial_f = first[:1]
    initial_l = lasts[0][:1] if lasts else ""

    needs_first = pattern != "last"
    needs_last = pattern != "first"
    if needs_first and not first:
        return []
    if needs_last and not lasts:
        return []

    out: list[str] = []

    def add(value: str) -> None:
        if value and value not in out:
            out.append(value)

    if pattern == "first":
        add(first)
    elif pattern == "first.last":
        for last in lasts:
            add(f"{first}.{last}")
    elif pattern == "flast":
        for last in lasts:
            add(f"{initial_f}{last}")
    elif pattern == "firstlast":
        for last in lasts:
            add(f"{first}{last}")
    elif pattern == "first_last":
        for last in lasts:
            add(f"{first}_{last}")
    elif pattern == "f.last":
        for last in lasts:
            add(f"{initial_f}.{last}")
    elif pattern == "firstl":
        add(f"{first}{initial_l}")
    elif pattern == "last.first":
        for last in lasts:
            add(f"{last}.{first}")
    elif pattern == "lastf":
        for last in lasts:
            add(f"{last}{initial_f}")
    elif pattern == "last":
        for last in lasts:
            add(last)
    elif pattern == "first-last":
        for last in lasts:
            add(f"{first}-{last}")
    elif pattern == "fl":
        add(f"{initial_f}{initial_l}")

    return out


def render(pattern: str, name: NameParts) -> str | None:
    """Local part for the joined-last variant, or None if unrenderable."""
    variants = render_variants(pattern, name)
    return variants[0] if variants else None


def reverse_match(local_part: str, name: NameParts) -> list[str]:
    """Every pattern that renders this local part for this name."""
    folded = _fold_local(local_part)
    if not folded:
        return []
    return [p for p in PATTERNS if folded in render_variants(p, name)]


def _prior(conn: sqlite3.Connection, pattern: str) -> float:
    row = conn.execute(
        "SELECT prior FROM pattern_priors WHERE pattern = ?", (pattern,)
    ).fetchone()
    return float(row["prior"]) if row is not None else DEFAULT_PRIOR


def posterior(conn: sqlite3.Connection, domain: str, pattern: str) -> float:
    """Beta mean for (domain, pattern): (hits + ALPHA*prior) / (hits+misses+ALPHA)."""
    row = conn.execute(
        "SELECT hits, misses FROM domain_patterns WHERE domain = ? AND pattern = ?",
        (domain, pattern),
    ).fetchone()
    hits = int(row["hits"]) if row is not None else 0
    misses = int(row["misses"]) if row is not None else 0
    return (hits + ALPHA * _prior(conn, pattern)) / (hits + misses + ALPHA)


def pattern_stats(conn: sqlite3.Connection, domain: str) -> dict[str, dict]:
    """pattern -> {hits, misses, verified_hits, posterior} for one domain."""
    rows = conn.execute(
        "SELECT pattern, hits, misses, verified_hits FROM domain_patterns WHERE domain = ?",
        (domain,),
    ).fetchall()
    stats: dict[str, dict] = {}
    for row in rows:
        pattern = row["pattern"]
        stats[pattern] = {
            "hits": int(row["hits"]),
            "misses": int(row["misses"]),
            "verified_hits": int(row["verified_hits"]),
            "posterior": posterior(conn, domain, pattern),
        }
    return stats


def best_pattern(
    conn: sqlite3.Connection, domain: str
) -> tuple[str, float, int] | None:
    """Highest-posterior pattern with its posterior and verified_hits."""
    stats = pattern_stats(conn, domain)
    if not stats:
        return None
    pattern, values = min(
        stats.items(),
        key=lambda item: (-item[1]["posterior"], _pattern_index(item[0]), item[0]),
    )
    return pattern, float(values["posterior"]), int(values["verified_hits"])


def record_outcome(
    conn: sqlite3.Connection,
    domain: str,
    pattern: str,
    outcome: str,
    *,
    verified: bool = False,
) -> None:
    """Upsert (domain, pattern) counts for a valid/invalid/catch_all outcome."""
    if outcome not in OUTCOMES:
        raise ValueError(f"unknown outcome: {outcome!r}")

    if outcome == "valid":
        conn.execute(
            """
            INSERT INTO domain_patterns (domain, pattern, hits, misses, verified_hits, last_hit_at)
            VALUES (?, ?, 1, 0, ?, datetime('now'))
            ON CONFLICT(domain, pattern) DO UPDATE SET
                hits = hits + 1,
                verified_hits = verified_hits + ?,
                last_hit_at = datetime('now')
            """,
            (domain, pattern, 1 if verified else 0, 1 if verified else 0),
        )
    elif outcome == "invalid":
        conn.execute(
            """
            INSERT INTO domain_patterns (domain, pattern, hits, misses, verified_hits, last_hit_at)
            VALUES (?, ?, 0, 1, 0, NULL)
            ON CONFLICT(domain, pattern) DO UPDATE SET misses = misses + 1
            """,
            (domain, pattern),
        )
    else:
        conn.execute(
            """
            INSERT INTO domain_patterns (domain, pattern, hits, misses, verified_hits, last_hit_at)
            VALUES (?, ?, 0, 0, 0, NULL)
            ON CONFLICT(domain, pattern) DO NOTHING
            """,
            (domain, pattern),
        )


@dataclass(frozen=True)
class Candidate:
    email: str
    pattern: str
    rules_score: float


def candidates(
    conn: sqlite3.Connection, name: NameParts, domain: str, k: int = 5
) -> list[Candidate]:
    """Ranked, deduped candidate emails: score = prior * posterior."""
    best: dict[str, Candidate] = {}
    for pattern in PATTERNS:
        score = _prior(conn, pattern) * posterior(conn, domain, pattern)
        for email in render_variants(pattern, name):
            existing = best.get(email)
            if existing is None or score > existing.rules_score:
                best[email] = Candidate(email=email, pattern=pattern, rules_score=score)
    ordered = sorted(
        best.values(),
        key=lambda c: (-c.rules_score, _pattern_index(c.pattern)),
    )
    return ordered[:k]


def reprior(conn: sqlite3.Connection) -> None:
    """Re-estimate global priors from all domains; no-op under 20 outcomes."""
    rows = conn.execute(
        """
        SELECT pattern, COALESCE(SUM(hits), 0) AS hits, COALESCE(SUM(misses), 0) AS misses
        FROM domain_patterns GROUP BY pattern
        """
    ).fetchall()
    totals = {
        row["pattern"]: (int(row["hits"]), int(row["misses"])) for row in rows
    }
    total_hits = sum(hits for hits, _ in totals.values())
    total_misses = sum(misses for _, misses in totals.values())
    if total_hits + total_misses < 20:
        return

    for row in conn.execute("SELECT pattern FROM pattern_priors").fetchall():
        pattern = row["pattern"]
        hits, _ = totals.get(pattern, (0, 0))
        prior = (hits + 1.0) / (total_hits + total_misses + 12.0)
        conn.execute(
            "UPDATE pattern_priors SET prior = ? WHERE pattern = ?", (prior, pattern)
        )
