"""Resolver pipeline: normalize -> identify -> route R1-R5 -> learn -> record.

Laya runs in **shadow** mode here: its answers are asked and stored in
``laya_decisions`` but never change a route, an email or an outcome. Pass 6
implements ``active`` (calibrated, gated per question type); until then
``active`` behaves exactly like ``shadow``. All writes join the caller's
connection through ``db.tx``; Laya is asked *outside* the write transaction so
a slow model never holds the SQLite write lock.
"""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass, field

from rapidfuzz import fuzz

from . import db, identity, patterns
from .config import Settings, get_settings
from .laya_client import (
    LayaAnswer,
    LayaClient,
    LayaQuestion,
    q_identity,
    q_plausible,
    q_rank,
    q_route,
)
from .normalize import NameParts, normalize_company, normalize_name
from .treg import NotConfigured, TregClient, TregResult, make_client

FIND_HIT_STATUSES: tuple[str, ...] = ("valid", "catch_all", "risky", "unknown")
CATCH_ALL_MIN_POSTERIOR = 0.5
NEXT_PATTERN_MIN_POSTERIOR = 0.35
GENERATE_K = 6


@dataclass
class FetchResult:
    contact_id: int
    name: str
    company: str
    domain: str | None
    email: str | None
    verification_status: str
    high_pattern_email: str | None
    alternates: list[str]
    confidence: float | None
    route: str
    treg_calls: dict[str, int]
    seen_count: int
    est_cost_saved: float
    cost_usd: float
    lookup_id: int
    identity_method: str


def to_json(result: FetchResult) -> dict:
    """The exact §2.5 payload (audit-only fields such as cost_usd are omitted)."""
    return {
        "contact_id": result.contact_id,
        "name": result.name,
        "company": result.company,
        "domain": result.domain,
        "email": result.email,
        "verification_status": result.verification_status,
        "high_pattern_email": result.high_pattern_email,
        "alternates": list(result.alternates),
        "confidence": result.confidence,
        "route": result.route,
        "treg_calls": dict(result.treg_calls),
        "seen_count": result.seen_count,
        "est_cost_saved": result.est_cost_saved,
    }


@dataclass
class _Tracked:
    calls: list[tuple[str, str, TregResult]] = field(default_factory=list)
    find_calls: int = 0
    verify_calls: int = 0
    cost: float = 0.0

    def add(self, kind: str, request: str, result: TregResult) -> None:
        self.calls.append((kind, request, result))
        if kind == "find":
            self.find_calls += 1
        else:
            self.verify_calls += 1
        self.cost += float(result.cost_units or 0.0)

    @property
    def counts(self) -> dict[str, int]:
        return {"find": self.find_calls, "verify": self.verify_calls}


def _pattern_index(pattern_name: str) -> int:
    try:
        return patterns.PATTERNS.index(pattern_name)
    except ValueError:
        return len(patterns.PATTERNS)


def _top_prior_pattern(conn: sqlite3.Connection) -> str:
    best = patterns.PATTERNS[0]
    best_key: tuple[float, int] | None = None
    for pattern_name in patterns.PATTERNS:
        row = conn.execute(
            "SELECT prior FROM pattern_priors WHERE pattern = ?", (pattern_name,)
        ).fetchone()
        prior = (
            float(row["prior"]) if row is not None else patterns.DEFAULT_PRIOR
        )
        key = (-prior, _pattern_index(pattern_name))
        if best_key is None or key < best_key:
            best_key, best = key, pattern_name
    return best


def _cache_fresh(
    conn: sqlite3.Connection, contact_id: int, settings: Settings
) -> bool:
    row = conn.execute(
        """
        SELECT CASE
                   WHEN last_verified_at IS NOT NULL
                        AND last_verified_at >= datetime('now', ?)
                   THEN 1 ELSE 0
               END AS fresh
        FROM contacts WHERE id = ?
        """,
        (f"-{int(settings.cache_ttl_days)} days", contact_id),
    ).fetchone()
    return bool(row is not None and row["fresh"])


def _set_catch_all(conn: sqlite3.Connection, company_id: int) -> None:
    conn.execute(
        "UPDATE companies SET is_catch_all = 1, updated_at = datetime('now') WHERE id = ?",
        (company_id,),
    )


def _next_pattern(
    conn: sqlite3.Connection,
    parts: NameParts,
    domain: str,
    attempted: set[str],
) -> str | None:
    """Next untried, renderable pattern ranked by posterior (>= 0.35)."""
    stats = patterns.pattern_stats(conn, domain)
    ordered = sorted(
        stats,
        key=lambda name: (-stats[name]["posterior"], _pattern_index(name), name),
    )
    for pattern_name in ordered:
        if pattern_name in attempted or pattern_name == "custom":
            continue
        if stats[pattern_name]["posterior"] < NEXT_PATTERN_MIN_POSTERIOR:
            break
        if patterns.render(pattern_name, parts):
            return pattern_name
    return None


def _best_fuzzy_row(
    conn: sqlite3.Connection, name_key: str, company_id: int
) -> tuple[sqlite3.Row | None, float]:
    """Closest existing contact at a company (used for the Q1 identity state)."""
    rows = conn.execute(
        "SELECT * FROM contacts WHERE company_id = ? AND merged_into IS NULL",
        (company_id,),
    ).fetchall()
    best: sqlite3.Row | None = None
    best_score = 0.0
    for row in rows:
        score = float(fuzz.token_set_ratio(name_key, row["name_key"]))
        if score > best_score:
            best, best_score = row, score
    return best, best_score


def _known_formats(conn: sqlite3.Connection, domain: str) -> list[str]:
    stats = patterns.pattern_stats(conn, domain)
    ordered = sorted(
        stats.items(), key=lambda kv: (-kv[1]["hits"], _pattern_index(kv[0]))
    )
    return [f"{name} ({s['hits']} valid)" for name, s in ordered if s["hits"]][:5]


def _similar_formats(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT pattern FROM pattern_priors ORDER BY prior DESC LIMIT 3"
    ).fetchall()
    return [row["pattern"] for row in rows]


def _truth_for(item: dict, status: str, verified_email: str | None = None) -> str | None:
    """Ground truth for a shadow row once the outcome is known.

    identity/route/plausible -> "valid" | "invalid" (report maps A/B);
    rank -> the criteria key ("c1"...) of the candidate that verified valid,
    else NULL (no verified candidate = no ground truth).
    """
    question = item["question_name"]
    if question == "identity":
        # ground truth = did the incoming fetch land on the existing contact's
        # exact email (same real person), or not
        existing_email = (item.get("existing_email") or "").strip().lower()
        if existing_email:
            return "valid" if (verified_email or "").strip().lower() == existing_email else "invalid"
        return "valid" if status == "valid" else "invalid"
    if question == "route":
        return "valid" if status == "valid" else "invalid"
    if question == "plausible":
        return "valid" if status == "valid" else None
    if question == "rank":
        if status != "valid":
            return None
        keys = item.get("candidate_keys") or {}
        for target in (verified_email, item.get("verified_email")):
            if target and target in keys:
                return keys[target]
        return None
    return None


def _laya_for(laya: object | None, settings: Settings) -> object | None:
    """A live Laya client, or None when the mode is off / the client is disabled."""
    if settings.laya_mode == "off":
        return None
    client = laya if laya is not None else LayaClient()
    return client if getattr(client, "enabled", False) else None


def _safe_find(
    client: TregClient, tracked: _Tracked, name: str, company: str
) -> TregResult:
    try:
        result = client.find(name, company)
    except NotConfigured:
        raise
    except Exception as exc:  # a broken transport must not kill the fetch
        result = TregResult(
            email=None,
            domain=None,
            status="error",
            raw={"status": "error", "error": str(exc)},
            cost_units=0.0,
            kind="find",
        )
    tracked.add("find", f"{name}|{company}", result)
    return result


def _safe_verify(client: TregClient, tracked: _Tracked, email: str) -> TregResult:
    try:
        result = client.verify(email)
    except NotConfigured:
        raise
    except Exception as exc:  # a broken transport must not kill the fetch
        result = TregResult(
            email=email,
            domain=None,
            status="error",
            raw={"status": "error", "error": str(exc)},
            cost_units=0.0,
            kind="verify",
        )
    tracked.add("verify", email, result)
    return result


def fetch(
    conn: sqlite3.Connection,
    name: str,
    company: str,
    *,
    force: bool = False,
    laya: object | None = None,
    client: TregClient | None = None,
) -> FetchResult:
    """Resolve one (name, company) through R1-R5 and record the audit trail."""
    started = time.perf_counter()
    settings = get_settings()
    if client is None:
        client = make_client(settings)
    laya_client = _laya_for(laya, settings)
    pending: list[dict] = []
    tracked = _Tracked()
    parts = normalize_name(name)

    with db.tx(conn):
        company_id = identity.get_or_create_company(conn, company)
        match = identity.resolve_contact(conn, parts, company_id)
        if match.contact_id is None:
            contact_id = identity.create_contact(conn, parts, company_id)
        else:
            contact_id = match.contact_id
            identity.touch_seen(conn, contact_id)
        identity_method = match.method
        if laya_client is not None and match.gray_zone:
            existing, score = _best_fuzzy_row(conn, parts.name_key, company_id)
            if existing is not None:
                pending.append(
                    {
                        "question_name": "identity",
                        "question": q_identity(
                            existing={
                                "name": existing["full_name"],
                                "company": company,
                                "email": existing["email"] or "",
                            },
                            incoming={"name": name, "company": company},
                        ),
                        "rules_answer": "new",
                        "existing_email": existing["email"] or "",
                    }
                )

    company_row = conn.execute(
        "SELECT * FROM companies WHERE id = ?", (company_id,)
    ).fetchone()
    contact_row = conn.execute(
        "SELECT * FROM contacts WHERE id = ?", (contact_id,)
    ).fetchone()
    seen_count = int(contact_row["seen_count"])

    domain: str | None = company_row["domain"]
    route: str | None = None
    email: str | None = None
    status: str = "unverified"
    email_source: str | None = None
    email_pattern: str | None = None
    confidence: float | None = None
    high_pattern_email: str | None = None
    alternates: list[str] = []
    stamp_verified = False
    generated: list[patterns.Candidate] = []
    verified_candidate: str | None = None
    verified_outcome: str | None = None

    cached_email = contact_row["email"]
    cached_status = contact_row["verification_status"]

    # --- R1 cache_hit -------------------------------------------------------
    if (
        not force
        and cached_email
        and cached_status == "valid"
        and _cache_fresh(conn, contact_id, settings)
    ):
        route = "cache_hit"
        email = cached_email
        status = "valid"
        email_source = contact_row["email_source"]
        email_pattern = contact_row["email_pattern"]
        confidence = contact_row["confidence"]
        high_pattern_email = contact_row["high_pattern_email"] or email

    # --- R2 catch_all -------------------------------------------------------
    if route is None and domain and company_row["is_catch_all"]:
        best = patterns.best_pattern(conn, domain)
        pattern_name: str | None = None
        posterior_value: float | None = None
        if best is not None:
            if best[1] >= CATCH_ALL_MIN_POSTERIOR:
                pattern_name, posterior_value = best[0], best[1]
        else:
            pattern_name = _top_prior_pattern(conn)
            posterior_value = patterns.posterior(conn, domain, pattern_name)
        if pattern_name is not None:
            local = patterns.render(pattern_name, parts)
            if local:
                route = "catch_all"
                email = f"{local}@{domain}"
                status = "catch_all"
                high_pattern_email = email
                confidence = posterior_value
                email_source = "pattern"
                email_pattern = pattern_name

    # --- R3 pattern_verify --------------------------------------------------
    if route is None and domain:
        best = patterns.best_pattern(conn, domain)
        if (
            best is not None
            and best[1] >= settings.verify_min_posterior
            and best[2] >= settings.verify_min_hits
        ):
            attempted: set[str] = set()
            tries = 0
            while tries < int(settings.verify_max_tries):
                if tries == 0:
                    pattern_name = best[0]
                else:
                    pattern_name = _next_pattern(conn, parts, domain, attempted)
                if pattern_name is None or pattern_name in attempted:
                    break
                attempted.add(pattern_name)
                local = patterns.render(pattern_name, parts)
                if local is None:
                    continue
                candidate_email = f"{local}@{domain}"
                posterior_value = patterns.posterior(conn, domain, pattern_name)
                if laya_client is not None and tries == 0:
                    alternatives: list[str] = []
                    for other in patterns.PATTERNS:
                        rendered = patterns.render(other, parts)
                        if not rendered:
                            continue
                        other_email = f"{rendered}@{domain}"
                        if other_email != candidate_email:
                            alternatives.append(other_email)
                    rank_candidates = [candidate_email] + alternatives[:11]
                    pending.append(
                        {
                            "question_name": "rank",
                            "question": q_rank(
                                person=name,
                                company=company,
                                domain=domain,
                                known_formats=_known_formats(conn, domain),
                                similar_formats=_similar_formats(conn),
                                candidate_emails=rank_candidates,
                            ),
                            "rules_answer": candidate_email,
                            "candidate_keys": {
                                candidate: f"c{index + 1}"
                                for index, candidate in enumerate(rank_candidates)
                            },
                            "verified_email": candidate_email,
                        }
                    )
                result = _safe_verify(client, tracked, candidate_email)
                tries += 1
                if result.status == "valid":
                    with db.tx(conn):
                        patterns.record_outcome(
                            conn, domain, pattern_name, "valid", verified=True
                        )
                    route = "pattern_verify"
                    email = result.email or candidate_email
                    status = "valid"
                    high_pattern_email = candidate_email
                    confidence = posterior_value
                    email_source = "treg_verify"
                    email_pattern = pattern_name
                    stamp_verified = True
                    break
                if result.status == "catch_all":
                    with db.tx(conn):
                        _set_catch_all(conn, company_id)
                    route = "pattern_verify"
                    email = candidate_email
                    status = "catch_all"
                    high_pattern_email = candidate_email
                    confidence = posterior_value
                    email_source = "pattern"
                    email_pattern = pattern_name
                    break
                if result.status == "error":
                    break
                with db.tx(conn):
                    patterns.record_outcome(conn, domain, pattern_name, "invalid")

    # --- R4 treg_find -------------------------------------------------------
    if route is None:
        result = _safe_find(client, tracked, name, company)
        if result.domain:
            domain = result.domain
            with db.tx(conn):
                conn.execute(
                    """
                    UPDATE companies
                    SET domain = ?, updated_at = datetime('now')
                    WHERE id = ?
                    """,
                    (result.domain, company_id),
                )

        if result.email and result.status in FIND_HIT_STATUSES:
            route = "treg_find"
            email = result.email
            status = result.status
            email_source = "treg_find"
            if not domain:
                domain = email.rpartition("@")[2] or None
            local, _, _ = email.partition("@")
            matched = patterns.reverse_match(local, parts)
            email_pattern = matched[0] if matched else "custom"
            high_pattern_email = email if matched else None
            if laya_client is not None:
                pending.append(
                    {
                        "question_name": "plausible",
                        "question": q_plausible(
                            person=name,
                            company=company,
                            treg_email=email,
                            learned_format=email_pattern,
                        ),
                        "rules_answer": email,
                    }
                )
            if result.status == "catch_all":
                with db.tx(conn):
                    _set_catch_all(conn, company_id)
            elif matched and domain:
                with db.tx(conn):
                    patterns.record_outcome(
                        conn, domain, email_pattern, "valid", verified=True
                    )
                if result.status == "valid":
                    stamp_verified = True
            elif result.status == "valid":
                stamp_verified = True

    # --- R5 generate --------------------------------------------------------
    if route is None:
        route = "generate"
        if not domain:
            status = "no_domain"
            email = None
            high_pattern_email = None
        else:
            ranked = patterns.candidates(conn, parts, domain, k=GENERATE_K)
            generated = [
                patterns.Candidate(
                    email=f"{candidate.email}@{domain}",
                    pattern=candidate.pattern,
                    rules_score=candidate.rules_score,
                )
                for candidate in ranked
            ]
            if not generated:
                status = "no_domain"
                email = None
                high_pattern_email = None
            else:
                top = generated[0]
                email = top.email
                status = "pattern_guess"
                high_pattern_email = top.email
                confidence = top.rules_score
                alternates = [candidate.email for candidate in generated[1:GENERATE_K]]
                email_source = "pattern"
                email_pattern = top.pattern
                if laya_client is not None:
                    rank_candidates = [candidate.email for candidate in generated]
                    pending.append(
                        {
                            "question_name": "rank",
                            "question": q_rank(
                                person=name,
                                company=company,
                                domain=domain,
                                known_formats=_known_formats(conn, domain),
                                similar_formats=_similar_formats(conn),
                                candidate_emails=rank_candidates,
                            ),
                            "rules_answer": top.email,
                            "candidate_keys": {
                                candidate: f"c{index + 1}"
                                for index, candidate in enumerate(rank_candidates)
                            },
                            "verified_email": top.email
                            if settings.generate_verify_top
                            else None,
                        }
                    )
                if settings.generate_verify_top:
                    result = _safe_verify(client, tracked, top.email)
                    verified_candidate = top.email
                    if result.status == "valid":
                        with db.tx(conn):
                            patterns.record_outcome(
                                conn, domain, top.pattern, "valid", verified=True
                            )
                        status = "valid"
                        email = result.email or top.email
                        stamp_verified = True
                        verified_outcome = "valid"
                    elif result.status == "catch_all":
                        with db.tx(conn):
                            _set_catch_all(conn, company_id)
                        status = "catch_all"
                        verified_outcome = "catch_all"
                    elif result.status == "invalid":
                        with db.tx(conn):
                            patterns.record_outcome(
                                conn, domain, top.pattern, "invalid"
                            )
                        verified_outcome = "invalid"

    # --- Laya Q2: verify-vs-find, only in the routing gray window -----------
    if laya_client is not None and route in ("pattern_verify", "treg_find") and domain:
        best_now = patterns.best_pattern(conn, domain)
        if best_now is not None:
            stats_now = patterns.pattern_stats(conn, domain)
            posterior_now, hits_now = best_now[1], best_now[2]
            misses_now = int(stats_now.get(best_now[0], {}).get("misses", 0))
            if (0.45 <= posterior_now < 0.60) or hits_now == 1:
                company_now = conn.execute(
                    "SELECT is_catch_all FROM companies WHERE id = ?", (company_id,)
                ).fetchone()
                pending.append(
                    {
                        "question_name": "route",
                        "question": q_route(
                            domain=domain,
                            best_pattern=best_now[0],
                            posterior=posterior_now,
                            verified_hits=hits_now,
                            misses=misses_now,
                            patterns_seen=len(stats_now),
                            catch_all=bool(
                                company_now and company_now["is_catch_all"]
                            ),
                        ),
                        "rules_answer": route,
                    }
                )

    # --- Laya (shadow): ask OUTSIDE the write transaction -------------------
    laya_rows: list[tuple[dict, LayaAnswer]] = []
    for item in pending:
        laya_rows.append((item, laya_client.ask(item["question"])))

    est_saved = max(0.0, float(settings.treg_find_cost) - tracked.cost)
    if route == "treg_find":
        est_saved = 0.0
    latency_ms = int((time.perf_counter() - started) * 1000)

    with db.tx(conn):
        if email is not None:
            conn.execute(
                """
                UPDATE contacts SET
                    email = ?,
                    email_source = ?,
                    email_pattern = ?,
                    verification_status = ?,
                    high_pattern_email = ?,
                    confidence = ?,
                    last_verified_at = CASE
                        WHEN ? THEN datetime('now') ELSE last_verified_at END
                WHERE id = ?
                """,
                (
                    email,
                    email_source,
                    email_pattern,
                    status,
                    high_pattern_email,
                    confidence,
                    1 if stamp_verified else 0,
                    contact_id,
                ),
            )

        cursor = conn.execute(
            """
            INSERT INTO lookups
                (contact_id, input_name, input_company, route, identity_method,
                 result_email, result_status, confidence, cost_usd, est_saved_usd,
                 laya_mode, latency_ms, forced)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                contact_id,
                name,
                company,
                route,
                identity_method,
                email,
                status,
                confidence,
                tracked.cost,
                est_saved,
                settings.laya_mode,
                latency_ms,
                1 if force else 0,
            ),
        )
        lookup_id = int(cursor.lastrowid)

        for kind, request, result in tracked.calls:
            conn.execute(
                """
                INSERT INTO treg_calls
                    (lookup_id, kind, request, status, email, cost_usd, raw_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    lookup_id,
                    kind,
                    request,
                    result.status,
                    result.email,
                    float(result.cost_units or 0.0),
                    json.dumps(result.raw, ensure_ascii=False, default=str),
                ),
            )

        for rank, candidate in enumerate(generated, start=1):
            outcome = (
                verified_outcome if candidate.email == verified_candidate else None
            )
            conn.execute(
                """
                INSERT INTO candidates
                    (lookup_id, email, pattern, rules_score, laya_prob,
                     final_score, rank, outcome)
                VALUES (?, ?, ?, ?, NULL, ?, ?, ?)
                """,
                (
                    lookup_id,
                    candidate.email,
                    candidate.pattern,
                    float(candidate.rules_score),
                    float(candidate.rules_score),
                    rank,
                    outcome,
                ),
            )

        for item, answer in laya_rows:
            conn.execute(
                """
                INSERT INTO laya_decisions
                    (lookup_id, question, routed_model, answer, confidence,
                     probs_json, rules_answer, applied, truth, latency_ms, error)
                VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?)
                """,
                (
                    lookup_id,
                    item["question_name"],
                    answer.routed_model,
                    answer.answer,
                    answer.confidence,
                    json.dumps(answer.probs, ensure_ascii=False),
                    item["rules_answer"],
                    _truth_for(item, status, email),
                    answer.latency_ms,
                    answer.error,
                ),
            )

    return FetchResult(
        contact_id=contact_id,
        name=name,
        company=company,
        domain=domain,
        email=email,
        verification_status=status,
        high_pattern_email=high_pattern_email,
        alternates=alternates,
        confidence=confidence,
        route=route,
        treg_calls=tracked.counts,
        seen_count=seen_count,
        est_cost_saved=est_saved,
        cost_usd=tracked.cost,
        lookup_id=lookup_id,
        identity_method=identity_method,
    )
