"""Identity resolution: companies by alias/domain, contacts by exact + fuzzy rules.

Rules only (no Laya). Every function participates in whatever transaction the
caller has open via ``db.tx``; nothing here calls ``conn.commit()``.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Literal

from rapidfuzz import fuzz

from .normalize import NameParts, normalize_company

FUZZY_MATCH_MIN = 95.0
GRAY_ZONE_MIN = 80.0


@dataclass(frozen=True)
class MatchResult:
    contact_id: int | None
    method: Literal["exact", "fuzzy_rule", "new"]
    score: float
    gray_zone: bool = False


def _clean_domain(domain: str | None) -> str | None:
    if not domain:
        return None
    value = domain.strip().lower().strip(".")
    return value or None


def get_or_create_company(
    conn: sqlite3.Connection,
    raw_company: str,
    domain: str | None = None,
) -> int:
    """Resolve a company id by alias key, company key, domain, then insert."""
    alias_key = normalize_company(raw_company) or "unknown"
    dom = _clean_domain(domain)

    company_id: int | None = None
    row = conn.execute(
        "SELECT company_id FROM company_aliases WHERE alias_key = ?", (alias_key,)
    ).fetchone()
    if row is not None:
        company_id = int(row["company_id"])

    if company_id is None:
        row = conn.execute(
            "SELECT id FROM companies WHERE company_key = ?", (alias_key,)
        ).fetchone()
        if row is not None:
            company_id = int(row["id"])

    if company_id is None and dom is not None:
        row = conn.execute(
            "SELECT id FROM companies WHERE domain = ? ORDER BY id LIMIT 1", (dom,)
        ).fetchone()
        if row is not None:
            company_id = int(row["id"])

    if company_id is None:
        cursor = conn.execute(
            """
            INSERT INTO companies (name, company_key, domain, created_at, updated_at)
            VALUES (?, ?, ?, datetime('now'), datetime('now'))
            """,
            ((raw_company or "").strip() or alias_key, alias_key, dom),
        )
        company_id = int(cursor.lastrowid)

    conn.execute(
        "INSERT OR IGNORE INTO company_aliases (alias_key, company_id) VALUES (?, ?)",
        (alias_key, company_id),
    )

    if dom is not None:
        row = conn.execute(
            "SELECT domain FROM companies WHERE id = ?", (company_id,)
        ).fetchone()
        if row is not None and row["domain"] is None:
            conn.execute(
                "UPDATE companies SET domain = ?, updated_at = datetime('now') WHERE id = ?",
                (dom, company_id),
            )

    return company_id


def resolve_contact(
    conn: sqlite3.Connection, name: NameParts, company_id: int
) -> MatchResult:
    """Exact match, else fuzzy against non-merged contacts at the company."""
    row = conn.execute(
        "SELECT id FROM contacts WHERE name_key = ? AND company_id = ?",
        (name.name_key, company_id),
    ).fetchone()
    if row is not None:
        return MatchResult(int(row["id"]), "exact", 100.0)

    rows = conn.execute(
        "SELECT id, name_key FROM contacts WHERE company_id = ? AND merged_into IS NULL",
        (company_id,),
    ).fetchall()
    best_id: int | None = None
    best_score = 0.0
    for candidate in rows:
        score = float(fuzz.token_set_ratio(name.name_key, candidate["name_key"]))
        if score > best_score:
            best_score = score
            best_id = int(candidate["id"])

    if best_id is not None and best_score >= FUZZY_MATCH_MIN:
        return MatchResult(best_id, "fuzzy_rule", best_score)
    if best_score >= GRAY_ZONE_MIN:
        return MatchResult(None, "new", best_score, gray_zone=True)
    return MatchResult(None, "new", best_score)


def create_contact(
    conn: sqlite3.Connection, name: NameParts, company_id: int
) -> int:
    """Insert a new contact with seen_count = 1 and fresh timestamps."""
    cursor = conn.execute(
        """
        INSERT INTO contacts
            (full_name, first_name, middle_name, last_name, name_key, company_id,
             seen_count, first_seen_at, last_seen_at)
        VALUES (?, ?, ?, ?, ?, ?, 1, datetime('now'), datetime('now'))
        """,
        (
            name.full_name,
            name.first,
            name.middle,
            name.last,
            name.name_key,
            company_id,
        ),
    )
    return int(cursor.lastrowid)


def touch_seen(conn: sqlite3.Connection, contact_id: int) -> None:
    """Increment seen_count and refresh last_seen_at."""
    conn.execute(
        "UPDATE contacts SET seen_count = seen_count + 1, last_seen_at = datetime('now') WHERE id = ?",
        (contact_id,),
    )


def find_contact_by_email(conn: sqlite3.Connection, email: str) -> int | None:
    """Case-insensitive email lookup, ignoring soft-merged rows."""
    row = conn.execute(
        """
        SELECT id FROM contacts
        WHERE lower(email) = lower(?) AND merged_into IS NULL
        ORDER BY id LIMIT 1
        """,
        (email or "",),
    ).fetchone()
    return int(row["id"]) if row is not None else None
