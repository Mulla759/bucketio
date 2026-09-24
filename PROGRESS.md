# PROGRESS

Append one entry per completed pass: what was done, anything stubbed, what is next.
A pass is done only when `pytest -q` is green.

---

## Pass 0 — Scaffold (done 2026-09-24)

- `git init` (branch `main`), initial commit of `bucketio.md` + `.gitignore`.
- `pyproject.toml` (hatchling, console script `bucketio = bucketio.cli:main`),
  `requires-python = ">=3.11,<3.14"` and `.python-version` = 3.13 (laya supports 3.10–3.13;
  system Python here is 3.14, so 3.13 is the build interpreter).
- `bucketio/config.py` — pydantic-settings, safe offline defaults
  (`TREG_MODE=mock`, `LAYA_MODE=off`), token falls back to `~/.treg/config.json`.
- `bucketio/db.py` — `connect()` (WAL, FK, busy_timeout), `migrate()` (idempotent),
  `tx()` context manager, `PATTERN_PRIORS` seed.
- `bucketio/schema.sql` — full §4 schema, shipped **inside the package** (so it is
  importable and included in the wheel) rather than at repo root. Single source of truth.
- `bucketio/cli.py` — minimal typer app (`bucketio --help`, `bucketio version`).
- `.env.example`, `README.md`, `tests/conftest.py`, `tests/test_db.py`.
- Deps: runtime (pydantic, typer, httpx, rapidfuzz, Unidecode, dnspython, fastapi,
  uvicorn, python-multipart) + extras `dev` (pytest, respx) and `laya` (`laya[serve]>=0.3.20`).

**Accept:** `bucketio --help` works; migrate creates all 11 tables + 12 seed priors;
re-running migrate is a no-op; WAL is on. `pytest -q` green.

**Stubbed:** `TREG_MODE=http|cli` adapters (Pass 3), Laya client (Pass 5), web UI (Pass 4).

**Next:** Pass 1 (normalize) + Pass 2 (patterns) in worktree `wt/core`;
Pass 5 client groundwork in worktree `wt/laya`; laya[serve] install on Python 3.13.

---

## Pass 1+2 — Normalization, identity, pattern engine (done 2026-09-24)

- `bucketio/normalize.py` — `fold_ascii` (Unidecode → lowercase → keep `[a-z0-9]`,
  hyphens become single spaces), `NameParts` (full_name, first, middle, last,
  name_key, initials, last_variants), `normalize_name` (comma last-first, middle
  names, suffix stripping, particles kept with the last name, non-Latin fallback),
  `canonical_first_name`, `NICKNAMES` (95 entries, canonical direction), `SUFFIXES`,
  `PARTICLES`, `normalize_company` (drops leading "the" + legal/entity suffixes).
- `bucketio/identity.py` — `get_or_create_company` (alias → company_key → domain →
  insert, alias always written, domain backfilled when NULL, `updated_at` bumped),
  `resolve_contact` (exact on `(name_key, company_id)`, else rapidfuzz
  `token_set_ratio`: ≥95 fuzzy_rule, 80–95 gray zone → new, <80 new),
  `create_contact`, `touch_seen`, `find_contact_by_email` (case-insensitive,
  skips merged). No function commits; all writes join the caller's `db.tx`.
- `bucketio/patterns.py` — the 12 `PATTERNS` in spec order, `render`,
  `render_variants` (joined + token last variants), `reverse_match`, `posterior`
  (Beta mean, ALPHA=2, prior fallback 0.02), `pattern_stats`, `best_pattern`,
  `record_outcome` (valid/invalid/catch_all upsert), `Candidate`, `candidates`
  (prior × posterior, deduped, PATTERNS tie-break, top k), `reprior` (no-op under
  20 outcomes, else `(sum_hits_p+1)/(total+12)`), `seed_priors`.
- Tests: `tests/test_normalize.py`, `tests/test_identity.py`, `tests/test_patterns.py`
  — **47 tests pass** (`uv run pytest -q`, including existing `test_db.py`).

**Decisions / deviations (spec was silent or ambiguous):**
- `normalize_company` strips the listed `group`, `holdings`, `technologies`
  suffix words but **not** `labs` (spec explicitly keeps "Acme Labs" distinct).
- Hyphens fold to a single space (spec allowed space or removal; one rule used
  everywhere). Apostrophes also fold to a space (`O'Brien` → `o brien`).
- `resolve_contact` exact match returns soft-merged rows as-is (fuzzy excludes
  them per spec; no merge path exists until Pass 7, this avoids UNIQUE errors).
- `record_outcome(..., "catch_all")` leaves counts untouched and creates a
  zero-count row if the (domain, pattern) row does not exist yet.
- Domains are lowercased/stripped before storage and matching; `get_or_create_company`
  matches domains case-insensitively via normalisation.
- `create_contact` never commits and will raise `IntegrityError` on a duplicate
  `(name_key, company_id)`, as the schema's UNIQUE constraint intends.

**Next:** Pass 3 (Treg adapter + resolver R1–R5, mock fixture).

