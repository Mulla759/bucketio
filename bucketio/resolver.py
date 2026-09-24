"""Resolver pipeline: normalize -> identify -> route R1-R5 -> learn -> record.

Laya is always *asked* through ``laya_client`` and stored in ``laya_decisions``.
In ``shadow`` (and for every question type the calibration gate has not
enabled) answers never change a route, an email or an outcome. In ``active``
the question types listed by ``calibrate.enabled_questions`` may be applied:

* Q1 identity - calibrated "A" >= 0.80 merges into the existing fuzzy contact.
* Q2 route - calibrated "A"/"B" >= 0.75 forces/skips the pattern verify.
* Q3 rank - only on the ``generate`` route: blend
  ``final = (1-W)*rules_score + W*calibrated_prob`` and re-rank.
* Q4 plausible never changes behaviour.

``rules_answer`` on every row is the criteria key the rules chose ("A"/"B" for
identity/route/plausible, "c1"... for rank). ``applied`` is 1 only on rows
whose answer actually changed the outcome. All writes join the caller's
connection through ``db.tx``; Laya is asked *outside* the write transactions so
a slow model never holds the SQLite write lock.
"""

from __future__ import annotations

import json
import math
import sqlite3
import threading
import time
from dataclasses import dataclass, field

from rapidfuzz import fuzz

from . import calibrate, db, identity, patterns
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
IDENTITY_MERGE_MIN_CONF = 0.80
ROUTE_FOLLOW_MIN_CONF = 0.75
ROUTE_GRAY_MIN_POSTERIOR = 0.45
ROUTE_GRAY_MAX_POSTERIOR = 0.60


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


def _temperature(conn: sqlite3.Connection, question: str, n_options: int) -> float:
    """Fitted temperature for ``(question, n_options)``; 1.0 when uncalibrated."""
    row = conn.execute(
        "SELECT temperature FROM laya_calibration WHERE question = ? AND n_options = ?",
        (question, int(n_options)),
    ).fetchone()
    if row is None:
        return 1.0
    value = row["temperature"]
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return 1.0
    number = float(value)
    return number if math.isfinite(number) and number > 0 else 1.0


def _blend_rank(
    candidates: list[patterns.Candidate],
    probs: dict[str, float],
    candidate_keys: dict[str, str],
    weight: float,
    temperature: float,
) -> tuple[list[patterns.Candidate], dict[str, tuple[float, float]]]:
    """Blend calibrated Laya probabilities into candidate scores and re-rank.

    Returns the re-ordered candidates plus ``email -> (laya_prob, final_score)``.
    A no-op (original order, empty map) when the distribution is missing or does
    not cover every candidate, so a partial answer can never distort the blend.
    """
    if not candidates or not probs:
        return candidates, {}
    calibrated = calibrate.calibrated_probs(probs, temperature)
    if not calibrated:
        return candidates, {}
    keys = {candidate.email: candidate_keys.get(candidate.email) for candidate in candidates}
    if any(key is None or key not in calibrated for key in keys.values()):
        return candidates, {}
    w = min(1.0, max(0.0, float(weight)))
    scores: dict[str, tuple[float, float]] = {}
    for candidate in candidates:
        laya_prob = float(calibrated[keys[candidate.email]])
        final = (1.0 - w) * float(candidate.rules_score) + w * laya_prob
        scores[candidate.email] = (laya_prob, final)
    ordered = sorted(
        candidates,
        key=lambda candidate: (
            -scores[candidate.email][1],
            _pattern_index(candidate.pattern),
            candidate.email,
        ),
    )
    return ordered, scores


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


_locks_guard = threading.Lock()
_identity_locks: dict[tuple[str, str], threading.Lock] = {}


def _identity_lock(name_key: str, company_key: str) -> threading.Lock:
    """One lock per (person, company): concurrent identical fetches serialise,
    so the second one hits the cache instead of paying for a second find."""
    key = (name_key, company_key)
    with _locks_guard:
        lock = _identity_locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _identity_locks[key] = lock
        return lock


def fetch(
    conn: sqlite3.Connection,
    name: str,
    company: str,
    *,
    force: bool = False,
    laya: object | None = None,
    client: TregClient | None = None,
) -> FetchResult:
    """Fetch with a per-identity lock (Pass 7 idempotency)."""
    parts = normalize_name(name)
    with _identity_lock(parts.name_key, normalize_company(company)):
        return _fetch(conn, name, company, force=force, laya=laya, client=client)


def _fetch(
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
    active = settings.laya_mode == "active"
    enabled = (
        calibrate.enabled_questions(conn)
        if active and laya_client is not None
        else set()
    )
    pending: list[dict] = []
    asked: list[tuple[dict, LayaAnswer]] = []
    tracked = _Tracked()
    parts = normalize_name(name)

    # --- identity: Q1 is asked before the contact is written so an active
    # "same person" answer can reuse the existing row ------------------------
    with db.tx(conn):
        company_id = identity.get_or_create_company(conn, company)
        match = identity.resolve_contact(conn, parts, company_id)

    existing_row: sqlite3.Row | None = None
    identity_item: dict | None = None
    merged_by_laya = False
    if laya_client is not None and match.gray_zone:
        existing_row, _score = _best_fuzzy_row(conn, parts.name_key, company_id)
        if existing_row is not None:
            identity_item = {
                "question_name": "identity",
                "question": q_identity(
                    existing={
                        "name": existing_row["full_name"],
                        "company": company,
                        "email": existing_row["email"] or "",
                    },
                    incoming={"name": name, "company": company},
                ),
                "rules_answer": "B",
                "existing_email": existing_row["email"] or "",
                "applied": 0,
            }
            if active and "identity" in enabled:
                answer = laya_client.ask(identity_item["question"])
                temperature = _temperature(
                    conn, "identity", len(identity_item["question"].criteria)
                )
                confidence_a = calibrate.calibrated_confidence(
                    answer.probs, "A", temperature
                )
                if (
                    answer.answer == "A"
                    and confidence_a is not None
                    and confidence_a >= IDENTITY_MERGE_MIN_CONF
                ):
                    merged_by_laya = True
                    identity_item["applied"] = 1
                asked.append((identity_item, answer))
            else:
                pending.append(identity_item)

    with db.tx(conn):
        if merged_by_laya and existing_row is not None:
            contact_id = int(existing_row["id"])
            identity.touch_seen(conn, contact_id)
            identity_method = "laya"
        elif match.contact_id is None:
            contact_id = identity.create_contact(conn, parts, company_id)
            identity_method = match.method
        else:
            contact_id = match.contact_id
            identity.touch_seen(conn, contact_id)
            identity_method = match.method

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
    candidate_scores: dict[str, tuple[float | None, float]] = {}
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

    # --- Q2 route (active): ask at decision time so the answer can apply -----
    route_item: dict | None = None
    force_verify = False
    skip_r3 = False
    if (
        laya_client is not None
        and active
        and "route" in enabled
        and route is None
        and domain
    ):
        best_now = patterns.best_pattern(conn, domain)
        if best_now is not None:
            stats_now = patterns.pattern_stats(conn, domain)
            posterior_now, hits_now = best_now[1], best_now[2]
            misses_now = int(stats_now.get(best_now[0], {}).get("misses", 0))
            if (
                ROUTE_GRAY_MIN_POSTERIOR <= posterior_now < ROUTE_GRAY_MAX_POSTERIOR
                or hits_now == 1
            ):
                rules_verify = (
                    posterior_now >= settings.verify_min_posterior
                    and hits_now >= settings.verify_min_hits
                )
                company_now = conn.execute(
                    "SELECT is_catch_all FROM companies WHERE id = ?", (company_id,)
                ).fetchone()
                route_item = {
                    "question_name": "route",
                    "question": q_route(
                        domain=domain,
                        best_pattern=best_now[0],
                        posterior=posterior_now,
                        verified_hits=hits_now,
                        misses=misses_now,
                        patterns_seen=len(stats_now),
                        catch_all=bool(company_now and company_now["is_catch_all"]),
                    ),
                    "rules_answer": "A" if rules_verify else "B",
                    "applied": 0,
                }
                answer = laya_client.ask(route_item["question"])
                temperature = _temperature(
                    conn, "route", len(route_item["question"].criteria)
                )
                followed = False
                if answer.answer == "A":
                    confidence = calibrate.calibrated_confidence(
                        answer.probs, "A", temperature
                    )
                    followed = (
                        confidence is not None and confidence >= ROUTE_FOLLOW_MIN_CONF
                    )
                elif answer.answer == "B":
                    confidence = calibrate.calibrated_confidence(
                        answer.probs, "B", temperature
                    )
                    followed = (
                        confidence is not None and confidence >= ROUTE_FOLLOW_MIN_CONF
                    )
                if followed:
                    decision_verify = answer.answer == "A"
                    if decision_verify != rules_verify:
                        route_item["applied"] = 1
                    force_verify = decision_verify
                    skip_r3 = not decision_verify
                asked.append((route_item, answer))

    # --- R3 pattern_verify --------------------------------------------------
    if route is None and domain and not skip_r3:
        best = patterns.best_pattern(conn, domain)
        thresholds_met = (
            best is not None
            and best[1] >= settings.verify_min_posterior
            and best[2] >= settings.verify_min_hits
        )
        if best is not None and (thresholds_met or force_verify):
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
                    candidate_keys = {
                        candidate: f"c{index + 1}"
                        for index, candidate in enumerate(rank_candidates)
                    }
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
                            "rules_answer": candidate_keys[candidate_email],
                            "candidate_keys": candidate_keys,
                            "verified_email": candidate_email,
                            "applied": 0,
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
                        "rules_answer": "A",
                        "applied": 0,
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
                rules_top = generated[0]
                rank_item: dict | None = None
                if laya_client is not None:
                    rank_candidates = [candidate.email for candidate in generated]
                    candidate_keys = {
                        candidate: f"c{index + 1}"
                        for index, candidate in enumerate(rank_candidates)
                    }
                    rank_item = {
                        "question_name": "rank",
                        "question": q_rank(
                            person=name,
                            company=company,
                            domain=domain,
                            known_formats=_known_formats(conn, domain),
                            similar_formats=_similar_formats(conn),
                            candidate_emails=rank_candidates,
                        ),
                        "rules_answer": candidate_keys[rules_top.email],
                        "candidate_keys": candidate_keys,
                        "verified_email": None,
                        "applied": 0,
                    }
                    if active and "rank" in enabled:
                        answer = laya_client.ask(rank_item["question"])
                        temperature = _temperature(conn, "rank", len(rank_candidates))
                        blended, scores = _blend_rank(
                            generated,
                            answer.probs,
                            candidate_keys,
                            settings.laya_weight,
                            temperature,
                        )
                        if scores:
                            generated = blended
                            candidate_scores = scores
                            rank_item["applied"] = (
                                1 if generated[0].email != rules_top.email else 0
                            )
                        asked.append((rank_item, answer))
                    else:
                        pending.append(rank_item)

                top = generated[0]
                email = top.email
                status = "pattern_guess"
                high_pattern_email = top.email
                confidence = candidate_scores.get(top.email, (None, top.rules_score))[1]
                alternates = [candidate.email for candidate in generated[1:GENERATE_K]]
                email_source = "pattern"
                email_pattern = top.pattern
                if rank_item is not None:
                    rank_item["verified_email"] = (
                        top.email if settings.generate_verify_top else None
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

    # --- Laya Q2 (shadow path): verify-vs-find, only in the gray window -----
    if (
        laya_client is not None
        and route_item is None
        and route in ("pattern_verify", "treg_find")
        and domain
    ):
        best_now = patterns.best_pattern(conn, domain)
        if best_now is not None:
            stats_now = patterns.pattern_stats(conn, domain)
            posterior_now, hits_now = best_now[1], best_now[2]
            misses_now = int(stats_now.get(best_now[0], {}).get("misses", 0))
            if (
                ROUTE_GRAY_MIN_POSTERIOR <= posterior_now < ROUTE_GRAY_MAX_POSTERIOR
                or hits_now == 1
            ):
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
                        "rules_answer": "A" if route == "pattern_verify" else "B",
                        "applied": 0,
                    }
                )

    # --- Laya: ask OUTSIDE the write transaction ----------------------------
    laya_rows: list[tuple[dict, LayaAnswer]] = list(asked)
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
            laya_prob, final_score = candidate_scores.get(
                candidate.email, (None, float(candidate.rules_score))
            )
            conn.execute(
                """
                INSERT INTO candidates
                    (lookup_id, email, pattern, rules_score, laya_prob,
                     final_score, rank, outcome)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    lookup_id,
                    candidate.email,
                    candidate.pattern,
                    float(candidate.rules_score),
                    laya_prob,
                    float(final_score),
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
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    lookup_id,
                    item["question_name"],
                    answer.routed_model,
                    answer.answer,
                    answer.confidence,
                    json.dumps(answer.probs, ensure_ascii=False),
                    item["rules_answer"],
                    int(item.get("applied", 0)),
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
