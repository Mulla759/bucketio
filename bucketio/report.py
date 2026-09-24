"""Report: cost, route and Laya-agreement metrics over the audit tables.

``build_report`` reads ``lookups``, ``treg_calls``, ``contacts`` and
``laya_decisions``. ``since`` accepts a relative window ("7d", "24h", "90m",
"30s", "2w") or an ISO date/datetime; anything else raises ``ValueError``.
Only ``lookups.created_at`` is windowed -- ``contacts`` is the current total of
non-merged rows, not a window count.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

_RELATIVE = re.compile(r"^(\d+)\s*([smhdw])$", re.IGNORECASE)
_ISO = re.compile(
    r"^\d{4}-\d{2}-\d{2}([T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?)?$"
)
_RELATIVE_UNITS = {
    "s": "seconds",
    "m": "minutes",
    "h": "hours",
    "d": "days",
    "w": "days",
}

_VALID_TRUTHS = frozenset({"valid", "yes", "true", "a"})
_INVALID_TRUTHS = frozenset({"invalid", "no", "false", "b", "not_valid"})
_AGREE_TRUTHS = frozenset({"agree", "agrees", "agreed", "match", "matches"})
_DISAGREE_TRUTHS = frozenset({"disagree", "disagrees", "disagreed", "mismatch", "no_match"})


@dataclass
class Report:
    fetches: int
    routes: dict[str, int]
    find_calls: int
    verify_calls: int
    est_saved_usd: float
    cost_usd: float
    contacts: int
    laya_agreement: float | None
    laya_samples: int

    def to_json(self) -> dict:
        return {
            "fetches": self.fetches,
            "routes": dict(self.routes),
            "treg": {
                "find_calls": self.find_calls,
                "verify_calls": self.verify_calls,
                "cost_usd": self.cost_usd,
            },
            "est_saved_usd": self.est_saved_usd,
            "contacts": self.contacts,
            "laya": {"agreement": self.laya_agreement, "samples": self.laya_samples},
        }


def _since_clause(since: str | None) -> tuple[str, list[str]]:
    """SQL predicate over the ``lookups l`` alias plus its parameters."""
    if since is None:
        return "", []
    text = str(since).strip()
    if not text:
        raise ValueError("since must not be empty")

    relative = _RELATIVE.match(text)
    if relative is not None:
        amount = int(relative.group(1))
        unit = relative.group(2).lower()
        if amount <= 0:
            raise ValueError(f"invalid since: {since!r}")
        days = amount * 7 if unit == "w" else amount
        return "l.created_at >= datetime('now', ?)", [f"-{days} {_RELATIVE_UNITS[unit]}"]

    if _ISO.match(text):
        normalized = text.replace("Z", "+00:00").replace(" ", "T")
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError as exc:
            raise ValueError(f"invalid since: {since!r}") from exc
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
        return "l.created_at >= ?", [parsed.strftime("%Y-%m-%d %H:%M:%S")]

    raise ValueError(
        f"invalid since: {since!r} (use a relative window like '7d'/'24h' or an ISO date)"
    )


def _laya_match(
    question: str | None, answer: str | None, truth: str | None
) -> bool | None:
    """True/False when the Laya answer can be judged against ``truth``, else None.

    For ``identity``/``route``/``plausible`` the truth is the eventual outcome
    ("valid" -> answer "A" was right, "invalid" -> "B"). For ``rank`` the truth
    is the criteria key of the verified candidate (e.g. "c1"). Truths of
    "agree"/"disagree" already encode whether the answer matched and are used
    as-is. Uninterpretable rows return None and are excluded from the sample.
    """
    answer_key = (answer or "").strip().lower()
    truth_key = (truth or "").strip().lower()
    if not answer_key or not truth_key:
        return None
    if truth_key in _AGREE_TRUTHS:
        return True
    if truth_key in _DISAGREE_TRUTHS:
        return False

    if (question or "").strip().lower() == "rank":
        if truth_key.startswith("c") and truth_key[1:].isdigit():
            return answer_key == truth_key
        if truth_key in _VALID_TRUTHS or truth_key in _INVALID_TRUTHS:
            # A rank truth of valid/invalid does not name the verified candidate.
            return None
        return answer_key == truth_key

    if truth_key in _VALID_TRUTHS:
        return answer_key == "a"
    if truth_key in _INVALID_TRUTHS:
        return answer_key == "b"
    return answer_key == truth_key


def build_report(conn: sqlite3.Connection, *, since: str | None = None) -> Report:
    clause, params = _since_clause(since)
    where = f"WHERE {clause}" if clause else ""

    totals = conn.execute(
        f"""
        SELECT COUNT(*) AS fetches,
               COALESCE(SUM(est_saved_usd), 0.0) AS saved,
               COALESCE(SUM(cost_usd), 0.0) AS cost
        FROM lookups l {where}
        """,
        params,
    ).fetchone()

    routes = {
        str(row["route"]): int(row["n"])
        for row in conn.execute(
            f"SELECT route, COUNT(*) AS n FROM lookups l {where} GROUP BY route",
            params,
        )
    }

    calls = {"find": 0, "verify": 0}
    for row in conn.execute(
        f"""
        SELECT tc.kind AS kind, COUNT(*) AS n
        FROM treg_calls tc JOIN lookups l ON l.id = tc.lookup_id
        {where}
        GROUP BY tc.kind
        """,
        params,
    ):
        calls[str(row["kind"])] = int(row["n"])

    contacts = int(
        conn.execute(
            "SELECT COUNT(*) AS n FROM contacts WHERE merged_into IS NULL"
        ).fetchone()["n"]
    )

    laya_where = "WHERE ld.truth IS NOT NULL"
    if clause:
        laya_where += f" AND {clause}"
    samples = 0
    agreed = 0
    for row in conn.execute(
        f"""
        SELECT ld.question AS question, ld.answer AS answer, ld.truth AS truth
        FROM laya_decisions ld JOIN lookups l ON l.id = ld.lookup_id
        {laya_where}
        """,
        params,
    ):
        verdict = _laya_match(row["question"], row["answer"], row["truth"])
        if verdict is None:
            continue
        samples += 1
        if verdict:
            agreed += 1

    return Report(
        fetches=int(totals["fetches"]),
        routes=routes,
        find_calls=calls.get("find", 0),
        verify_calls=calls.get("verify", 0),
        est_saved_usd=float(totals["saved"]),
        cost_usd=float(totals["cost"]),
        contacts=contacts,
        laya_agreement=(agreed / samples) if samples else None,
        laya_samples=samples,
    )
