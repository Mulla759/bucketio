# PROGRESS

Append one entry per completed pass: what was done, anything stubbed, what is next.
A pass is done only when `pytest -q` is green.

---

## Pass 0 â€” Scaffold (done 2026-09-24)

- `git init` (branch `main`), initial commit of `bucketio.md` + `.gitignore`.
- `pyproject.toml` (hatchling, console script `bucketio = bucketio.cli:main`),
  `requires-python = ">=3.11,<3.14"` and `.python-version` = 3.13 (laya supports 3.10â€“3.13;
  system Python here is 3.14, so 3.13 is the build interpreter).
- `bucketio/config.py` â€” pydantic-settings, safe offline defaults
  (`TREG_MODE=mock`, `LAYA_MODE=off`), token falls back to `~/.treg/config.json`.
- `bucketio/db.py` â€” `connect()` (WAL, FK, busy_timeout), `migrate()` (idempotent),
  `tx()` context manager, `PATTERN_PRIORS` seed.
- `bucketio/schema.sql` â€” full Â§4 schema, shipped **inside the package** (so it is
  importable and included in the wheel) rather than at repo root. Single source of truth.
- `bucketio/cli.py` â€” minimal typer app (`bucketio --help`, `bucketio version`).
- `.env.example`, `README.md`, `tests/conftest.py`, `tests/test_db.py`.
- Deps: runtime (pydantic, typer, httpx, rapidfuzz, Unidecode, dnspython, fastapi,
  uvicorn, python-multipart) + extras `dev` (pytest, respx) and `laya` (`laya[serve]>=0.3.20`).

**Accept:** `bucketio --help` works; migrate creates all 11 tables + 12 seed priors;
re-running migrate is a no-op; WAL is on. `pytest -q` green.

**Stubbed:** `TREG_MODE=http|cli` adapters (Pass 3), Laya client (Pass 5), web UI (Pass 4).

**Next:** Pass 1 (normalize) + Pass 2 (patterns) in worktree `wt/core`;
Pass 5 client groundwork in worktree `wt/laya`; laya[serve] install on Python 3.13.

---

## Pass 1+2 â€” Normalization, identity, pattern engine (done 2026-09-24)

- `bucketio/normalize.py` â€” `fold_ascii` (Unidecode â†’ lowercase â†’ keep `[a-z0-9]`,
  hyphens become single spaces), `NameParts` (full_name, first, middle, last,
  name_key, initials, last_variants), `normalize_name` (comma last-first, middle
  names, suffix stripping, particles kept with the last name, non-Latin fallback),
  `canonical_first_name`, `NICKNAMES` (95 entries, canonical direction), `SUFFIXES`,
  `PARTICLES`, `normalize_company` (drops leading "the" + legal/entity suffixes).
- `bucketio/identity.py` â€” `get_or_create_company` (alias â†’ company_key â†’ domain â†’
  insert, alias always written, domain backfilled when NULL, `updated_at` bumped),
  `resolve_contact` (exact on `(name_key, company_id)`, else rapidfuzz
  `token_set_ratio`: â‰¥95 fuzzy_rule, 80â€“95 gray zone â†’ new, <80 new),
  `create_contact`, `touch_seen`, `find_contact_by_email` (case-insensitive,
  skips merged). No function commits; all writes join the caller's `db.tx`.
- `bucketio/patterns.py` â€” the 12 `PATTERNS` in spec order, `render`,
  `render_variants` (joined + token last variants), `reverse_match`, `posterior`
  (Beta mean, ALPHA=2, prior fallback 0.02), `pattern_stats`, `best_pattern`,
  `record_outcome` (valid/invalid/catch_all upsert), `Candidate`, `candidates`
  (prior Ã— posterior, deduped, PATTERNS tie-break, top k), `reprior` (no-op under
  20 outcomes, else `(sum_hits_p+1)/(total+12)`), `seed_priors`.
- Tests: `tests/test_normalize.py`, `tests/test_identity.py`, `tests/test_patterns.py`
  â€” **47 tests pass** (`uv run pytest -q`, including existing `test_db.py`).

**Decisions / deviations (spec was silent or ambiguous):**
- `normalize_company` strips the listed `group`, `holdings`, `technologies`
  suffix words but **not** `labs` (spec explicitly keeps "Acme Labs" distinct).
- Hyphens fold to a single space (spec allowed space or removal; one rule used
  everywhere). Apostrophes also fold to a space (`O'Brien` â†’ `o brien`).
- `resolve_contact` exact match returns soft-merged rows as-is (fuzzy excludes
  them per spec; no merge path exists until Pass 7, this avoids UNIQUE errors).
- `record_outcome(..., "catch_all")` leaves counts untouched and creates a
  zero-count row if the (domain, pattern) row does not exist yet.
- Domains are lowercased/stripped before storage and matching; `get_or_create_company`
  matches domains case-insensitively via normalisation.
- `create_contact` never commits and will raise `IntegrityError` on a duplicate
  `(name_key, company_id)`, as the schema's UNIQUE constraint intends.

**Next:** Pass 3 (Treg adapter + resolver R1â€“R5, mock fixture).

---

## Pass 5 (groundwork) â€” Laya client

- `bucketio/laya_client.py`: `LayaQuestion` (frozen) / `LayaAnswer` dataclasses;
  `LayaClient(settings=None)` with `enabled`, `ask()` (never raises), `health()`;
  transports `http` (httpx POST `{laya_url}/v1/systemone`, Bearer auth) /
  `inprocess` (lazy `import laya; laya.Router(preload=True)`; import failure ->
  error answer) / anything else -> `unknown_transport`; `laya_mode == "off"` ->
  `error="laya_off"` with no network call. `build_body()` and `parse_response()`
  are exported so tests (and Pass 5 proper) can pin the wire mapping.
- Builders: `q_identity`, `q_route`, `q_rank` (hard cap 12, order preserved),
  `q_plausible`; every question is `type: "choice"` (no `noul`).
- `scripts/run_laya.ps1` / `scripts/run_laya.sh`: launch the official
  `laya-serve` sidecar, env-var configured only (serve.py `main()` reads
  `LAYA_HOST`/`LAYA_PORT`; there are no host/port CLI flags):
  `USE_TF=0`, `LAYA_HOST=127.0.0.1`, `LAYA_PORT=8001`, `LAYA_PRELOAD=1`,
  `LAYA_DEVICE=cpu`, `LAYA_API_KEY` defaulting to `change-me`; each prints the
  `uv pip install "laya[serve]"` hint. Both pass syntax checks (`Parser::ParseFile`,
  `bash -n`).
- `tests/test_laya_client.py`: **24 tests** (off / happy / timeout / connect /
  500 / malformed JSON / unknown transport / inprocess import failure / health
  200-503-off / builders / parse variants / golden determinism). Full suite
  `uv run pytest -q`: **30 passed** (24 + 6 existing test_db.py).

**Real `POST /v1/systemone` schema** (fetched 2026-09-24, laya 0.3.20 â€”
https://github.com/NandhaKishorM/laya/blob/main/laya/serve.py and
https://github.com/NandhaKishorM/laya/blob/main/laya/agent.py `_decode_answers`):

Request: `{"state": <str|dict|list>, "questions": {"<qid>": {"type": "choice",
"instructions": "...", "criteria": {"A": "...", "B": "..."}}}, "model": optional}`
with `Authorization: Bearer <LAYA_API_KEY>` when the sidecar sets one. Limits:
64 questions, 50k state chars, 2 MiB body; 400/401/413/422/500 on bad input.

Response: `{"model": "laya-rl-agent", "answers": {"<qid>": {"type": "choice",
"choice": "<criteria key>", "probabilities": {key: p}, "confidence": <normalized
entropy>, "answer_confidence": <max(p)>, "action": {"act_probability": ...}}},
"usage": {"input_tokens": n, "output_tokens": 0}, "routing": {"model":
"english"|"multilingual"|"typed-decisions", "repo": ..., "reason": ...}}`.
`routing` is added by `Router.predict` (what both `laya-serve` and the
in-process transport use). `GET /health` -> 200 `{"status": "ok", "loaded":
bool, "device": str}`.

**Deviations from bucketio.md Â§3.5:**
- States/criteria match Â§3.5 Q1-Q4 exactly; question **names** are
  `identity`/`route`/`rank`/`plausible` per the Pass 5 interface (bucketio.md's
  `same_person`/`best_email` were JSON examples, not names).
- The response label lives in `choice` and probabilities in `probabilities`
  (not `answer`/`probs`); the parser also accepts `answer`/`label`/`value` and
  `probs`/`scores`, plus `results`/`questions` nesting and name-less
  single-answer payloads.
- For `choice`, wire `confidence` is normalized entropy, **not** the calibrated
  probability the 0.80 gate needs; `answer_confidence` is max(p) (the calibrated
  value per `agent.py`). `LayaAnswer.confidence` therefore prefers
  `answer_confidence` and falls back to `confidence` only when absent.
- `latency_ms` is not in the wire response: the client records measured
  wall-clock ms, but still reads an explicit `latency_ms` if a proxy adds one.
- `routed_model` comes from `routing.model`; the top-level `model` is always
  `laya-rl-agent`, so it is only used as a fallback when it names a checkpoint.

**Next:** resolver wiring (Pass 3 owns `bucketio/resolver.py`) â€” `LayaClient`,
the Q1-Q4 builders and `laya_decisions` rows are ready to consume.

**Verified live (2026-09-24):** `laya-serve` 0.3.20 running on 127.0.0.1:8001 with
`LAYA_PRELOAD=1` on CPU, weights pulled from HF `convaiinnovations/laya` (English +
multilingual checkpoints).

---

## Pass 3 â€” Treg adapter + resolver (R1â€“R5)

- `bucketio/treg.py` â€” `Status` enum, `TregResult` (email, domain, status, raw,
  cost_units, kind), `TregClient` protocol, `NotConfigured`. `map_status()` maps
  Treg words (valid/invalid/catch_all|accept_all|accept-all|is_accept_all/risky/
  not_found|not-found|miss/unknown/None) onto the enum. Three clients:
  - `TregMockClient` â€” deterministic, reads `tests/fixtures/treg_mock.json`
    (path overridable), costs from `settings.treg_find_cost` / `treg_verify_cost`;
    miss on an unknown company costs 0; a domain's `not_found: true` reports the
    domain on a miss.
  - `TregHttpClient` â€” `POST {base}/call/treg.people.email.find` with
    `{"domain","full_name"}` and `.../treg.people.email.verify` with `{"email"}`;
    `X-Treg-Token` (+ `X-Treg-Org` when set); cost from `X-Treg-Cost-Micro`
    (micro-USD â†’ USD) else config; httpx timeout `treg_timeout_s`.
    Parsing is tolerant: email from `output.email`/`raw.email`; status from
    `output.status`/`raw.status`/`output.verified` (bool/word); domain from
    `raw.domain`/`output.domain`/`raw.website_url`/`raw.company.domain`/email.
  - `TregCliClient` â€” `treg call <id> --data <json>`, stdout JSON, cost from a
    stderr `charged $<usd>` line else config. Both real transports raise
    `NotConfigured` without token/base URL (HTTP) or token (CLI).
  - `make_client()` selects by `TREG_MODE` (mock default).
- `bucketio/resolver.py` â€” `FetchResult` + `to_json()` (exact Â§2.5 keys) and
  `fetch(conn, name, company, *, force=False, laya=None, client=None)`:
  normalize/identity â†’ R1 cache_hit â†’ R2 catch_all â†’ R3 pattern_verify
  (max 2 verifies, next pattern â‰¥ 0.35, miss recorded before retry) â†’
  R4 treg_find (learns the pattern, sets company domain on hit and miss) â†’
  R5 generate (k=6, `high_pattern_email`, 5 alternates, optional verify-top),
  then one `db.tx` writes the `lookups`, `treg_calls` (raw JSON verbatim) and
  `candidates` rows. `cost_usd` = spend; `est_saved_usd` = the Â§3.3 formula.
  All Treg-call exceptions become `status="error"` results (NotConfigured
  still propagates) so routes can fall through.
- `tests/fixtures/treg_mock.json` â€” the Â§6 fixture (acme/globex/initech/
  umbrella/ghost + `anna ivanova` ASCII-folding case).
- Tests: `tests/test_treg.py` (29: `map_status` table, mock semantics, respx
  find/verify headers+body+parse+cost fallback, NotConfigured, make_client) and
  `tests/test_resolver_routes.py` (13: the 10 acceptance cases + no-domain,
  TTL expiry, `to_json` keys). Suite: **113 passed** (71 existing + 42 new).

**Deviations / decisions (spec silent or conflicting):**
- R2 fallback: a catch-all hit deliberately records no pattern stats (Â§3.10), so
  Initech has no `best_pattern`; the literal R2 condition ("best_pattern exists
  with posterior â‰¥ 0.5") would send the second person back to R4 and break
  acceptance 5. When the domain is catch-all and has **no** pattern rows, R2
  renders the strongest global prior instead; a row with posterior < 0.5 still
  falls through as specified.
- R3 verify returning `catch_all` reports route `pattern_verify` (the action
  taken) with status `catch_all`; R2 is the only route named `catch_all`.
- `patterns.candidates()` returns local parts (its merged tests assert
  `jane.doe`, not a full address), so the resolver appends `@domain` before
  storing `candidates.email`, `high_pattern_email` and `alternates`.
- Find hits with status `risky`/`unknown` record a `valid` outcome per the
  written spec but do **not** stamp `last_verified_at` (so they stay
  uncacheable).
- `est_saved_usd` is the literal formula `max(0, treg_find_cost - cost_usd)`
  except route `treg_find`; a free `not_found` miss therefore makes `generate`
  report `treg_find_cost` "saved" against the all-find baseline.
- `candidates` rows are written for R5 generate only; the verified top
  candidate carries `outcome`, `final_score = rules_score`, `laya_prob` NULL.
  `--force` bypasses R1 (and `lookups.forced = 1`).
- Gray-zone identity is ignored (Pass 3): gray zone â†’ `new` contact,
  `identity_method = "new"`; exact/fuzzy_rule call `touch_seen`.

**Next:** Pass 4 (CLI/API/web consume `fetch`/`to_json`); Pass 5 wires Laya into
the accepted-but-unused `laya` parameter and `laya_decisions`.

---

## Pass 4 (frontend) â€” static web UI

- `bucketio/web/` â€” exactly three files, no framework, no build step:
  - `index.html` â€” single semantic page; search box, fetch form (Name + Company +
    `force`), Â§2.5 result card, contacts table (Name | Company | Email |
    High-pattern email | Status pill | Confidence | Seen | Last verified | Route),
    clickable rows â†’ detail panel with lookup history, report strip, CSV import
    form (multipart field `file`) and export link. Loads `./style.css` + `./app.js`
    (relative, so FastAPI can serve them from `/static`).
  - `style.css` â€” plain CSS, dark-first with a `prefers-color-scheme: light`
    override; system font stack, no external fonts/CDN. Pills: `valid` green,
    `invalid` red, `catch_all` amber, `risky` orange, `pattern_guess` blue,
    `unverified`/`unknown`/`no_domain`/`not_found` grey.
  - `app.js` â€” vanilla ES2020, no dependencies, no `innerHTML` (textContent +
    `createElement` only). Functions: `api`, `renderResult`, `loadContacts`,
    `renderTable`, `showDetail`, `loadReport`, `importCsv` (+ `debounce` 200 ms,
    pill/format helpers, banner, `disableApiControls`, `init`).
- Endpoints consumed: `POST /api/fetch`, `GET /api/contacts?q=&status=&limit=&offset=`
  (`{items,total}`), `GET /api/contacts/{id}` (`{contact,lookups}`), `GET /api/report`
  (`{fetches,routes,treg:{find_calls,verify_calls},est_saved_usd,laya:{agreement,samples}}`),
  `POST /api/import` (multipart `file`), `GET /api/export` (plain link).
- Missing report/contact fields render `-` (never throw); "find calls avoided" uses
  `find_calls_avoided` if present else `fetches - treg.find_calls`. Every fetch is
  try/catch'd and surfaces errors in the banner. `file://` shows "run `bucketio serve`",
  disables API controls and skips auto-loads.
- Verified: `node --check bucketio/web/app.js` clean; `index.html` references the two
  assets with exact names; a throwaway Node smoke test (temp DOM stub, not committed)
  exercised boot loads, table/result/detail rendering, report totals, missing-field
  fallbacks and the `file://` guard â€” all green.
- Still needs a manual browser check against `bucketio serve` once the Pass 4 backend
  (`api.py`, `cli.py serve`) exists in this worktree: search/status/paging,
  `POST /api/fetch` round-trip, CSV import + export download, pill appearance.

**Next:** Pass 3 (`treg.py` + `resolver.py`) and the Pass 4 API (`api.py`,
`cli.py serve`) so the page can be checked end to end.

---

## Pass 4 (CLI/API/report/CSV)

- `bucketio/report.py` — `Report` dataclass + `to_json()` (exact keys:
  fetches / routes / treg{find_calls,verify_calls,cost_usd} / est_saved_usd /
  contacts / laya{agreement,samples}) and `build_report(conn, *, since=None)`.
  `since` accepts "7d"/"24h"/"90m"/"30s"/"2w" or an ISO date/datetime (naive or
  tz-aware, converted to UTC); anything else raises `ValueError`. routes =
  counts per `lookups.route`; find/verify = COUNT over `treg_calls.kind` joined
  to the windowed lookups; est_saved/cost = SUM over `lookups`; contacts =
  COUNT(contacts WHERE merged_into IS NULL) (current total, not windowed).
  Laya agreement = share of `laya_decisions` rows with a non-null `truth` whose
  `answer` matches: truth "valid" -> answer "A", "invalid" -> "B" for
  identity/route/plausible; for rank the truth is the verified candidate key
  ("c1"); "agree"/"disagree" truths are used as-is. Uninterpretable rows (e.g.
  rank truth "valid") are excluded from `laya_samples`; no rows -> None/0.
- `bucketio/csv_io.py` — `import_contacts(conn, path, *, client=None)` (path or
  open stream; header case-insensitive, BOM-tolerant, aliases and extra columns
  tolerated) uses `get_or_create_company` + `resolve_contact`/`create_contact`
  per row, sets email/email_source="import"/verification_status="unverified"
  when Email is present, and returns {"rows","created","updated","errors"} with
  per-row errors (row number + message) instead of aborting. Missing Name or
  Company header -> ValueError. `export_contacts(conn, path) -> int` writes
  Name,Company,Email,High-pattern email,Status,Confidence,Seen,Last verified,Route
  (skips merged_into; Route = latest lookup route) to a file or stream.
- `bucketio/api.py` — `create_app(settings=None)` + module-level `app`. Routes:
  POST /api/fetch (422 on missing/blank name/company; 503 NotConfigured),
  GET /api/contacts (q LIKE name/company/email with escaped wildcards, status,
  limit=50, offset=0 -> {items,total}), GET /api/contacts/{id}
  ({contact,lookups} newest first; 404), GET /api/report?since= (400 bad since),
  POST /api/import (multipart `file`), GET /api/export (text/csv attachment),
  GET /health (db/laya{mode,enabled,reachable}/treg{mode}, never raises when
  Laya is down), then the `/` StaticFiles(html=True) mount last so / serves
  index.html and ./app.js + ./style.css resolve. Fresh sqlite connection per
  request; migrate in the lifespan.
- `bucketio/cli.py` — kept `version` + callback; added `init`, `fetch NAME
  COMPANY [--force] [--json]`, `import PATH`, `export PATH`, `report [--since]
  [--json]`, `serve [--host 127.0.0.1] [--port 8080]` (uvicorn) and the `lreg`
  sub-app `lreg status` (tiny YAML-subset reader for lreg.yaml, defaults when
  absent; prints db path/table count, Laya mode/transport/health, Treg mode and
  web URL; always exits 0). Every DB command migrates first; all commands run
  with TREG_MODE=mock + LAYA_MODE=off and no .env.
- Tests: `tests/test_report.py` (18), `tests/test_csv_io.py` (11),
  `tests/test_api.py` (13), `tests/test_cli.py` (13) — suite **168 passed**
  (113 existing + 55 new). Every test points at a tmp DB and the mock fixture
  by monkeypatching `bucketio.config.get_settings` (+ `bucketio.resolver`).
- Verified end-to-end outside pytest: `bucketio init/fetch/report/import/
  export/lreg status` against a temp DB with mock Treg, and a real
  `uvicorn bucketio.api:app` on 127.0.0.1:8099 — `/` 200 text/html, `/app.js`
  200 application/javascript, `/api/contacts` {items,total}, `/health` ok,
  `/api/report` ok (HTTP smoke only, no browser screenshot).

**Deviations / decisions:**
- `treg.cost_usd` in the report is `SUM(lookups.cost_usd)` (as specified), not
  a re-sum of `treg_calls.cost_usd`.
- `contacts` in the report is the current non-merged total, not filtered by
  `since` (the spec only says to filter `lookups.created_at`).
- Import does not touch `seen_count` (an import is not a fetch) and passes the
  email's domain to `get_or_create_company` so imports teach company domains.
- `import_contacts(..., client=None)` accepts the Treg client for the future
  verify-on-import path but ignores it in Pass 4.
- `lreg status` reports runtime settings (env/.env) and annotates values that
  differ from lreg.yaml (e.g. `[lreg.yaml: shadow]`); lreg.yaml supplies the
  web URL and is read with a tiny built-in YAML-subset parser (PyYAML is not a
  dependency).
- `report --since` with an invalid value exits non-zero via
  `typer.BadParameter` (the API returns 400).

**Next:** Pass 5 wires Laya into `resolver.fetch` (`laya_decisions`, the `laya`
parameter) — the report's agreement metric is ready for it.


---

## Pass 5 — Laya in shadow mode (done 2026-09-24)

- `bucketio/resolver.py` now resolves a Laya client via `_laya_for()` (`off` -> None,
  otherwise the injected client or a fresh `LayaClient()` when enabled). In shadow
  (and, for now, `active`) Laya is asked and logged; it **never** changes a route,
  email, status, cost, candidate or outcome — verified by a golden test that runs the
  same sequence on two fresh DBs (`off` vs `shadow`) and asserts identical results.
- Questions wired exactly as §3.5:
  - `identity` (Q1) — only in the 80–95 identity gray zone, with the closest existing
    contact as the `existing` state.
  - `route` (Q2) — only in the routing gray window: best posterior in [0.45, 0.60) or
    `verified_hits == 1`, and only when the route taken was `pattern_verify`/`treg_find`.
  - `rank` (Q3) — every `generate` and every `pattern_verify` (candidates = the verify
    target + up to 11 rendered alternatives, capped by the builder).
  - `plausible` (Q4) — every `treg_find` hit.
- Laya is asked **outside** the final write transaction (a slow model never holds the
  SQLite write lock); one `laya_decisions` row per question is written inside the same
  transaction as its `lookups` row, `applied = 0` always.
- Truth backfill convention (consumed by `report.py`):
  - `identity` -> `valid` when the incoming fetch landed on the existing contact's exact
    email, else `invalid` (ground truth for "same person").
  - `route` -> `valid` when the route produced a `valid` email, else `invalid`.
  - `plausible` -> `valid` when the find hit verified `valid`, else NULL.
  - `rank` -> the criteria key (`c1`…) of the candidate that verified valid, else NULL.
- Timeout/error policy: every Laya exception is caught into the row's `error` column
  (`timeout` for `httpx.TimeoutException`); the fetch is unaffected.
- Tests: `tests/test_resolver_shadow.py` — 7 tests (golden, per-question counts,
  gray-zone identity, timeout safety, rank truth, off-mode silence, active==shadow).
  Full suite **175 passed**.
- Live smoke (this machine): `laya-serve` 0.3.20 on CPU, warm calls 450–624 ms,
  `routed_model: english`; the first (cold) call exceeded the 1.5 s default, so
  `.env.example`/`lreg.yaml` now use `LAYA_TIMEOUT_S=2.5`.

**Next:** Pass 6 — `calibrate.py` (temperature fit + accuracy vs rules per question
type), `LAYA_MODE=active` gated on `accuracy > rules_acc` and `n_samples >= 50`,
reversible via `LAYA_MODE=shadow`.

---

## Pass 6 - Calibration and activation (done 2026-09-24)

- `bucketio/calibrate.py` turns the `laya_decisions` audit trail into
  `laya_calibration`:
  - `fit_temperatures(conn, *, grid=None)` groups labelled rows by
    `(question, n_options)` where `n_options` is the number of keys in the
    stored probability distribution; it grid-searches 0.5-5.0 step 0.05 for the
    temperature minimising the mean NLL of the **truth** key under
    `softmax(ln(p)/T)` and upserts one row per group (with `fitted_at`).
  - `accuracy` = share of usable rows with `answer == truth`; `rules_acc` =
    share with `rules_answer == truth` over the rows that have a `rules_answer`
    (NULL when none do, and such a group can never enable).
  - Rows without truth/answer, with unparseable `probs_json`, or whose truth
    key is absent from the distribution are skipped and never written.
  - `calibrated_probs`/`calibrated_confidence` are pure (`softmax(ln p / T)`,
    max-shifted for stability; argmax preserved; sums to 1).
  - `format_report(rows)` renders a table for a future `report` wiring
    (cli.py untouched this pass).
- `rules_answer` is now always a criteria KEY (Pass 5 stored mixed values):
  identity "B" (rules never merge), route "A" for `pattern_verify` / "B" for
  `treg_find`, plausible "A", rank the rules-chosen candidate's key ("c1"...).
  `tests/test_resolver_shadow.py` assertions updated.
- `LAYA_MODE=active` is gated per fetch on
  `calibrate.enabled_questions(conn)`: `n_samples >= 50 AND accuracy >
  rules_acc` (both non-null). Off, shadow, or an unenabled question type stays
  exactly as shadow - logged, `applied = 0`.
- Active behaviour:
  - Q1 identity: calibrated P("A") >= 0.80 -> reuse the existing fuzzy contact
    (`touch_seen`, `identity_method = "laya"`, no new row). The ask happens
    before the contact write.
  - Q2 route: the ask moves to decision time (before R3) inside the gray
    window; calibrated "A"/"B" >= 0.75 forces/skips the pattern verify. In
    shadow the ask stays after routing, unchanged.
  - Q3 rank (generate only): `final = (1-W)*rules_score + W*calibrated_prob`
    with `W = LAYA_WEIGHT`, re-rank, blended `laya_prob`/`final_score` written
    to `candidates`, new top used as email/high_pattern_email/verify target.
  - Q4 plausible never changes behaviour.
- `applied` = 1 only when the answer changed something: Q1 merge happened, Q2
  followed answer changed the verify-vs-find decision, Q3 blend changed the top
  candidate. It is 0 for every shadow/off row and every logged-but-unenabled
  question.
- Laya asks (Q1 at identity, Q2 before R3, Q3 before ranking, Q4 after find)
  stay outside the write transactions.
- Tests: `tests/test_calibrate.py` (13) + `tests/test_resolver_active.py` (8)
  cover the fit direction/accuracy/upsert/skip rules, the enabled gate, the
  pure functions, rank-only activation, the blend changing the top, <50-sample
  inertness (byte-identical `to_json` vs shadow), Q1 merge (and below-threshold
  no-merge), Q2 force/skip, and shadow reversibility. Full suite **196 passed**.

**Deviations / decisions:**
- `rules_acc` denominator is the rows with a non-null `rules_answer` (NULL when
  a group has none); the gate requires both accuracy and rules_acc non-null.
- Active rank blending requires the answer's distribution to cover every
  candidate key; a partial/empty answer is a no-op (rules scores kept).
- The generate-route `confidence` becomes the blended `final_score` of the new
  top (it is the score of the choice); shadow is unchanged.
- Q2 `applied` compares the followed decision with the rules decision at ask
  time (a forced verify that later falls through to find still counts as
  applied, because the routing path changed).
- Active Q2 still logs the post-routing ask when the pre-R3 gray window did not
  hold (the answer cannot change the route then, so `applied = 0`).

**Next:** Pass 7 - hardening (concurrency, idempotency, unmerge, backup).
