"""CSV import/export for the contacts sheet.

Import header: ``Name,Company[,Email]`` -- case-insensitive, BOM-tolerant and
extra columns are ignored. Export writes the full sheet in the same column
order as the web table. Both accept a filesystem path or an open text stream
so the API can work in memory. One bad import row is collected, never fatal.
"""

from __future__ import annotations

import csv
import sqlite3
from typing import IO, Any

from . import db, identity
from .normalize import normalize_name

EXPORT_HEADER: tuple[str, ...] = (
    "Name",
    "Company",
    "Email",
    "High-pattern email",
    "Status",
    "Confidence",
    "Seen",
    "Last verified",
    "Route",
)

_COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "name": ("name", "full name", "full_name", "contact", "contact name", "person"),
    "company": (
        "company",
        "company name",
        "company_name",
        "organization",
        "organisation",
        "org",
        "employer",
    ),
    "email": ("email", "e-mail", "email address", "e-mail address", "mail"),
}


def _resolve_columns(fieldnames: Any) -> dict[str, str | None]:
    """Map the canonical Name/Company/Email columns onto actual header names."""
    normalized: dict[str, str] = {}
    for raw in fieldnames or ():
        if raw is None:
            continue
        normalized.setdefault(str(raw).strip().lower(), raw)
    resolved: dict[str, str | None] = {}
    for canonical, aliases in _COLUMN_ALIASES.items():
        resolved[canonical] = next(
            (normalized[alias] for alias in aliases if alias in normalized), None
        )
    missing = [key for key in ("name", "company") if resolved[key] is None]
    if missing:
        raise ValueError(
            "CSV is missing required column(s): "
            + ", ".join(missing)
            + " (expected a header row like Name,Company[,Email])"
        )
    return resolved


def _clean(value: object) -> str:
    return str(value).strip() if value is not None else ""


def _email_domain(email: str) -> str | None:
    if "@" not in email:
        return None
    domain = email.rpartition("@")[2].strip().lower().strip(".")
    return domain or None


def _import_row(conn: sqlite3.Connection, name: str, company: str, email: str) -> bool:
    """Upsert one row inside its own transaction; True when it was created."""
    parts = normalize_name(name)
    with db.tx(conn):
        company_id = identity.get_or_create_company(
            conn, company, _email_domain(email)
        )
        match = identity.resolve_contact(conn, parts, company_id)
        if match.contact_id is None:
            contact_id = identity.create_contact(conn, parts, company_id)
            created = True
        else:
            contact_id = match.contact_id
            created = False
        if email:
            conn.execute(
                """
                UPDATE contacts
                SET email = ?, email_source = 'import', verification_status = 'unverified'
                WHERE id = ?
                """,
                (email, contact_id),
            )
    return created


def import_contacts(
    conn: sqlite3.Connection,
    path: str | Any,
    *,
    client: object | None = None,
) -> dict:
    """Import a CSV; returns ``{"rows", "created", "updated", "errors"}``.

    ``client`` is accepted for the future verify-on-import path and is unused
    in Pass 4. ``path`` may be a filesystem path or an open text stream.
    """
    _ = client  # reserved for verify-on-import (Pass 5+)
    close_after = not hasattr(path, "read")
    stream: IO[str] = (
        open(path, "r", encoding="utf-8-sig", newline="") if close_after else path
    )
    stats: dict = {"rows": 0, "created": 0, "updated": 0, "errors": []}
    try:
        reader = csv.DictReader(stream)
        columns = _resolve_columns(reader.fieldnames)
        for line, raw in enumerate(reader, start=2):
            if raw is None:
                continue
            name = _clean(raw.get(columns["name"]))
            company = _clean(raw.get(columns["company"]))
            email_column = columns.get("email")
            email = _clean(raw.get(email_column)) if email_column else ""
            if not name and not company and not email:
                continue
            stats["rows"] += 1
            if not name or not company:
                stats["errors"].append(
                    {"row": line, "error": "missing name or company"}
                )
                continue
            try:
                created = _import_row(conn, name, company, email)
            except Exception as exc:
                stats["errors"].append(
                    {"row": line, "error": f"{type(exc).__name__}: {exc}"}
                )
                continue
            stats["created" if created else "updated"] += 1
        return stats
    finally:
        if close_after:
            stream.close()


_EXPORT_SQL = """
SELECT c.full_name AS full_name,
       co.name AS company,
       c.email AS email,
       c.high_pattern_email AS high_pattern_email,
       c.verification_status AS verification_status,
       c.confidence AS confidence,
       c.seen_count AS seen_count,
       c.last_verified_at AS last_verified_at,
       (SELECT l.route FROM lookups l
         WHERE l.contact_id = c.id
         ORDER BY l.id DESC LIMIT 1) AS route
FROM contacts c JOIN companies co ON co.id = c.company_id
WHERE c.merged_into IS NULL AND c.do_not_contact = 0
ORDER BY c.id
"""


def export_contacts(conn: sqlite3.Connection, path: str | Any) -> int:
    """Write the contacts sheet to ``path`` (file or stream); return row count.

    ``do_not_contact`` rows are never exported (compliance, Pass 7).
    """
    close_after = not hasattr(path, "write")
    stream: IO[str] = (
        open(path, "w", encoding="utf-8", newline="") if close_after else path
    )
    try:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(EXPORT_HEADER)
        count = 0
        for row in conn.execute(_EXPORT_SQL):
            writer.writerow(
                [
                    row["full_name"],
                    row["company"],
                    row["email"] or "",
                    row["high_pattern_email"] or "",
                    row["verification_status"] or "",
                    "" if row["confidence"] is None else row["confidence"],
                    row["seen_count"],
                    row["last_verified_at"] or "",
                    row["route"] or "",
                ]
            )
            count += 1
        return count
    finally:
        if close_after:
            stream.close()
