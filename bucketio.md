# BucketIO — Build Plan (PRD · Design Doc · Data Model · Agent Passes)

> **For the CLI agent:** Read this whole file once. Then execute the passes in §7 **in order**. Do not start a pass until the previous pass's acceptance checks are green. Every pass ends with `pytest -q` passing and a short note appended to `PROGRESS.md`. Anything marked **[CONFIRM]** needs a real value from the owner before it can go live, and must be stubbed until then.

---

## 0. TL;DR

BucketIO is a local, self-hosted contact store (SQLite) that sits **in front of Treg**. When asked to fetch a contact (Name + Company), it:

1. Checks whether it already knows this person → return for **$0**.
2. Checks whether it knows the company's **email format** → build the email itself and ask Treg only to **verify** (cheap) instead of **find** (expensive).
3. Otherwise calls Treg **find**, stores the result, and **learns the company's format** from it so the next person at that company is cheap.
4. If Treg finds nothing, it **generates the most probable email(s)** from learned patterns and returns a "high-pattern" guess.

Laya (the `convaiinnovations/laya` decision model) is used as a **scorer and tie-breaker**, never as a generator. The deterministic pattern cache does most of the cost saving; Laya improves the gray-zone decisions and gets switched on gradually (shadow → active) once measured.

---

## 1. Key facts that shape the design (read before building)

These come from the Laya model card (Sept 2026, `laya` 0.3.12) and change how Laya can be used:

| Fact | Consequence for BucketIO |
|---|---|
| Laya is a **classifier**: given a `state` and typed `questions` (`choice`, `score`, `noul`), it returns calibrated probabilities. **It never generates text.** | Laya cannot "write" an email. Our code generates candidate emails from patterns; Laya **ranks/judges** them. |
| `Router` auto-detects script/language and dispatches to English or multilingual checkpoint; one forward pass per call. | Use `Router` so non-English names (Devanagari, CJK, Cyrillic, accented Latin) go to the multilingual checkpoint automatically. |
| **Base checkpoints are near chance zero-shot on typed-decision tasks** (~0.36 vs 0.46 majority baseline); strength comes from fine-tuning. | Laya must **not** be trusted blindly on day 1. Run it in **shadow mode**, log its answers against real verification outcomes, and only give it weight once it beats the rule engine. |
| Ships **over-confident**; per-(question type, option count) temperature fitting drops ECE 0.47 → 0.08. | Build a calibration script (Pass 6) that fits temperatures from our own labeled lookups. |
| `choice` degrades above ~20 options (shared token budget). | Keep candidate lists ≤ 12 emails per question. |
| `noul` (yes/no) can follow its labels instead of the input on the English checkpoint. | **Never use `noul`.** Ask yes/no as a 2-option `choice` with neutral keys `A`/`B`. |
| `action.act_probability` carries no usable signal. | Gate on `confidence` only. |
| `laya-serve` exposes the Router over HTTP (`POST /v1/systemone`, Jev-compatible), binds `0.0.0.0` with **no auth** unless `LAYA_API_KEY` is set. | Run Laya as a **localhost sidecar** with `LAYA_API_KEY` set. Keeps the ~0.8 GB model out of the web process and lets it stay warm. |
| CPU latency with preload: ~193–464 ms per call; GPU ~33 ms. `laya.load()` can hang if TensorFlow is installed → set `USE_TF=0`. | CPU is fine for this workload. Always set `USE_TF=0`. |
| Apache-2.0, `$0` self-hosted. | No per-call cost for Laya. |

**Treg** is treated as an external black box. We do not modify it; we call it and store its output. Its exact interface is **[CONFIRM]** (see §9).

---

## 2. PRD

### 2.1 Problem
Every contact lookup currently goes to Treg's discovery ("find"/cold outreach) path, which is the expensive one. Many lookups are redundant: the same person is requested again, or a new person works at a company whose email format we already know. We pay full price every time and throw away the pattern knowledge.

### 2.2 Goals (in priority order)
1. **Cut cost**: route to Treg *verify* instead of *find* whenever the company's format is known; skip Treg entirely for known, recently verified contacts.
2. **Remove redundancy**: one canonical record per real person (identity resolution across name variants and company-name variants).
3. **Pattern efficiency**: learn each domain's email format from every result and reuse it.
4. **Always return something useful**: a verified email if possible, otherwise the highest-probability pattern email with a confidence.
5. **Identity**: every contact has a stable ID, a verification status, a seen count, and an audit trail of how its email was obtained.

### 2.3 Non-goals
- No changes to Treg.
- No fancy frontend (plain HTML/CSS table + search box).
- No multi-user auth, no cloud hosting, no sending email.
- No fine-tuning Laya in v1 (the calibration data we collect makes that possible later).

### 2.4 Users & entry points
- **The CLI agent** (primary): `bucketio fetch "Jane Doe" "Acme Inc"` → JSON on stdout.
- **HTTP**: `POST /api/fetch` with the same payload (for other tools).
- **Human**: `http://localhost:8080` — table of contacts, status, confidence, seen count; search; CSV import/export.

### 2.5 Core user story
> "Fetch Jane Doe at Acme." → BucketIO returns within seconds:
> ```json
> {
>   "contact_id": 412,
>   "name": "Jane Doe",
>   "company": "Acme Inc",
>   "domain": "acme.com",
>   "email": "jane.doe@acme.com",
>   "verification_status": "valid",
>   "high_pattern_email": "jane.doe@acme.com",
>   "alternates": ["jdoe@acme.com", "jane@acme.com"],
>   "confidence": 0.93,
>   "route": "pattern_verify",
>   "treg_calls": {"find": 0, "verify": 1},
>   "seen_count": 1,
>   "est_cost_saved": 0.09
> }
> ```

### 2.6 Functional requirements
| ID | Requirement |
|---|---|
| F1 | `fetch(name, company)` resolves identity, picks a route, calls Treg at most as needed, stores everything, returns the JSON above. |
| F2 | Seen tracking: each fetch of an existing identity increments `seen_count` and `last_seen_at`. If `seen_count ≥ 2` **and** status is `valid` within TTL, never call Treg. |
| F3 | Pattern learning: any email confirmed valid (from Treg find or verify) is reverse-matched to a pattern and updates that domain's pattern stats. Invalid results count as misses. |
| F4 | Routing: `cache_hit` → `pattern_verify` → `treg_find` → `generate` (see §3.3). |
| F5 | Generation: when no verified email exists, produce ranked candidates; top one is `high_pattern_email`. |
| F6 | Catch-all domains: if Treg reports catch-all, don't spend verify calls on that domain; return pattern email with status `catch_all`. |
| F7 | Audit: every fetch writes one `lookups` row with route, Treg calls, Laya answers, latency, outcome. Raw Treg output stored verbatim. |
| F8 | Laya modes: `off` / `shadow` (called and logged, zero influence) / `active` (blended into decisions). Default `shadow`. |
| F9 | Cost report: `bucketio report` prints find calls avoided, verify calls used, estimated $ saved, Laya-vs-rules agreement. |
| F10 | CSV import (Name, Company, Email optional) and export of the contacts "sheet". |
| F11 | `--force` flag to bypass cache and re-verify. |

### 2.7 Non-functional
- Runs on one machine, CPU only acceptable. Python 3.11+.
- p50 fetch latency (excluding Treg network time): < 600 ms on CPU with Laya shadow on.
- SQLite in WAL mode; safe for concurrent CLI + web reads.
- Works fully with Laya **off** and Treg **mocked** (for tests and outages).
- Secrets (Treg key, Laya key) only in `.env`, never in the DB or logs.

### 2.8 Success metrics
- **Treg find-rate** (find calls / fetches) drops week over week; target < 40% after the first ~500 contacts at overlapping companies.
- **Cost per fetch** vs. baseline (all-find).
- **Pattern hit rate**: % of `pattern_verify` routes that come back `valid`; target ≥ 80%.
- **Duplicate rate**: identities merged / total fetches.
- **Laya lift**: accuracy of Laya-ranked top candidate vs. rules-ranked top candidate on verified outcomes. Laya goes `active` only if lift > 0.

---

## 3. Design Doc

### 3.1 Architecture

```
            ┌──────────────┐        ┌───────────────────────────┐
 CLI agent ─┤ bucketio CLI ├──┐     │  laya-serve (sidecar)     │
            └──────────────┘  │     │  127.0.0.1:8001           │
            ┌──────────────┐  ├────►│  POST /v1/systemone       │
 Browser ───┤ FastAPI :8080├──┤     │  Router, preloaded, warm  │
            └──────────────┘  │     └───────────────────────────┘
                              ▼
                     ┌──────────────────┐        ┌──────────────┐
                     │ Resolver (core)  ├───────►│ Treg adapter │──► Treg (untouched)
                     │ identity→route→  │        │ find / verify│
                     │ generate→learn   │        └──────────────┘
                     └────────┬─────────┘
                              ▼
                     SQLite (bucketio.db, WAL)
```

Both CLI and API call the same `Resolver.fetch()`; the CLI does **not** need the web server running (it opens the DB directly). Laya is reached over HTTP so the model stays warm across CLI invocations. A fallback `LAYA_TRANSPORT=inprocess` loads `laya.Router` directly for single-process use.

### 3.2 Stack (chosen for speed of build + low ops)
- Python 3.11, `uv` for env.
- `sqlite3` stdlib (no ORM; schema in `schema.sql`, tiny migration runner).
- `FastAPI` + `uvicorn` for API; static `index.html` + `style.css` + ~100 lines of vanilla JS.
- `typer` for CLI.
- `httpx` for Treg (if HTTP) and Laya calls.
- `rapidfuzz` for fuzzy name/company matching; `unidecode` for ASCII folding of names into email local parts.
- `dnspython` for MX check of domains (cheap sanity check, cached).
- `laya[serve]` in a separate venv or the same one, run as sidecar.
- `pytest` + `respx` (HTTP mocking).

### 3.3 The resolution pipeline (the core)

```
fetch(name, company, force=False)
│
├─ 1. NORMALIZE
│     name → first, last, middle, name_key   (lowercase, ASCII-folded, punctuation stripped,
│                                              suffixes Jr/III/PhD dropped, nickname map bob→robert)
│     company → company_key                  (lowercase, strip Inc/LLC/Ltd/Corp/GmbH/"The", punctuation)
│
├─ 2. IDENTITY
│     a. exact (name_key, company_id) match → existing contact
│     b. else fuzzy candidates (rapidfuzz ≥ 88 on name, same company_id or company_key ≥ 90)
│          score ≥ 95 → same person (rules)
│          80–95     → GRAY ZONE → Laya Q1 (identity). In shadow mode, rules decide (treat as new).
│          < 80      → new contact
│     c. upsert contact, seen_count += 1, last_seen_at = now
│
├─ 3. ROUTE  (first rule that matches wins)
│     R1 cache_hit       contact.email exists AND status='valid' AND verified within TTL (90d) AND !force
│                        → return, 0 Treg calls
│     R2 catch_all       domain.is_catch_all = 1 AND domain has a pattern with posterior ≥ 0.5
│                        → build pattern email, status='catch_all', 0 Treg calls
│     R3 pattern_verify  domain known AND best pattern posterior ≥ VERIFY_MIN_POSTERIOR (0.60)
│                        AND best pattern verified_hits ≥ VERIFY_MIN_HITS (2)
│                        → build email → Treg.verify(email)
│                            valid   → done, pattern hit++
│                            invalid → pattern miss++, try next pattern if its posterior ≥ 0.35
│                                      (max VERIFY_MAX_TRIES = 2), else fall to R4
│                            catch_all → mark domain catch-all, status='catch_all'
│     R4 treg_find       → Treg.find(name, company)
│                            hit  → store email + domain, reverse-match pattern, stats update
│                            miss → R5
│     R5 generate        domain known? (from company table, Treg output, or [optional] MX-checked guess)
│                          no  → status='no_domain', return best-effort nothing
│                          yes → candidates = render all patterns, score = prior × pattern posterior
│                                (+ Laya Q3 blend when active) → top = high_pattern_email
│                                optional: Treg.verify(top) if GENERATE_VERIFY_TOP=1 (default 1)
│
│     GRAY ZONE for routing: if best posterior is 0.45–0.60 or hits == 1, ask Laya Q2
│     (verify-vs-find). Shadow: log only. Active: follow Laya if confidence ≥ 0.75.
│
├─ 4. LEARN   every valid/invalid outcome updates domain_patterns (Beta counts)
│
└─ 5. RECORD  lookups row + treg_calls rows + laya_decisions rows; return JSON
```

**Why this order saves money:** R1 and R2 are free, R3 costs one verify (cheap), R4 is the only expensive call and it teaches us the format so future lookups at that company hit R3.

**Inverse direction (the user's "other way around"):** if Treg find returns an email that does *not* reverse-match any known pattern for that domain, or conflicts with a strong learned pattern, BucketIO asks Laya Q4 (plausibility) and records a `conflict` flag; it keeps Treg's answer (Treg is the source of truth for finds) but does not update pattern stats until a verify confirms it.

### 3.4 Pattern engine

Patterns are templates over normalized `first`, `last`, `f` (first initial), `l` (last initial), `middle`/`m`:

```
first.last   flast     first      firstlast   first_last   f.last
firstl       last.first lastf     last        first-last   fl
```
(12 patterns → fits Laya's ≤20-option budget.)

- **Render**: `render(pattern, name) -> local_part`, ASCII-folded, lowercase; multi-part last names try both joined (`vandamme`) and first token.
- **Reverse-match**: `match(local_part, name) -> [patterns]` — which patterns produce this local part. Used to learn from any email Treg returns. If none match, store pattern `custom` (no learning).
- **Stats** per (domain, pattern): `hits`, `misses`, `verified_hits`. Posterior mean = `(hits + α·prior) / (hits + misses + α)`, with α = 2 and `prior` from `pattern_priors` (global table, itself updated from all domains' aggregate counts).
- **Seed priors** (starting guesses, overwritten by our data): first.last 0.40, flast 0.18, first 0.10, firstlast 0.06, f.last 0.05, first_last 0.04, firstl 0.04, last.first 0.03, lastf 0.03, last 0.02, first-last 0.02, fl 0.03.
- **Candidates**: all patterns rendered for the domain, deduped, scored, top 5 returned as `alternates`.

### 3.5 Where Laya is used (exact questions)

All calls go to `POST {LAYA_URL}/v1/systemone` with `Authorization: Bearer {LAYA_API_KEY}`. States are compact JSON (keep < ~300 tokens for the English checkpoint's state budget). **No `noul`.** Each answer's `confidence` is stored.

**Q1 — Identity (gray zone only)**
```json
{
  "state": {"existing": {"name": "Robert Smith", "company": "ACME Corp", "email": "rsmith@acme.com"},
            "incoming": {"name": "Bob Smith", "company": "Acme Inc"}},
  "questions": {"same_person": {"type": "choice",
     "instructions": "Do these two records refer to the same real person at the same employer?",
     "criteria": {"A": "yes, same person", "B": "no, different people"}}}
}
```
Active: merge if `A` with confidence ≥ 0.80, else treat as new.

**Q2 — Route (gray zone only)**
```json
{
  "state": {"domain": "acme.com", "best_pattern": "first.last", "posterior": 0.52,
            "verified_hits": 1, "misses": 0, "patterns_seen": 1, "catch_all": false},
  "questions": {"route": {"type": "choice",
     "instructions": "Is the learned email format reliable enough to verify a generated address instead of running a full search?",
     "criteria": {"A": "reliable enough, verify the generated address", "B": "not reliable, run a full search"}}}
}
```

**Q3 — Candidate ranking (generate route, and shadow on pattern_verify)**
```json
{
  "state": {"person": "Jane van der Berg", "company": "Acme", "domain": "acme.com",
            "known_formats_at_domain": ["first.last (3 valid)"],
            "formats_at_similar_domains": ["flast", "first.last"]},
  "questions": {"best_email": {"type": "choice",
     "instructions": "Which address is most likely this person's real work email?",
     "criteria": {"c1": "jane.vanderberg@acme.com", "c2": "jvanderberg@acme.com", "c3": "jane@acme.com", "...": "≤ 12 total"}}}
}
```
Active blend: `final = (1 - W) · rules_score + W · laya_prob`, `W = LAYA_WEIGHT` (start 0.3; calibrated in Pass 6).

**Q4 — Treg output plausibility (inverse direction)**
```json
{
  "state": {"person": "Jane Doe", "company": "Acme", "treg_email": "j.doe.2@acme.com",
            "learned_format": "first.last"},
  "questions": {"plausible": {"type": "choice",
     "instructions": "Does this email address plausibly belong to this person?",
     "criteria": {"A": "yes, plausible", "B": "no, looks wrong or belongs to someone else"}}}
}
```

**Batching:** when generating, Q3 is one call. The CSV bulk-import path uses `Router.predict_batch` via in-process mode or sequential HTTP calls.

**Failure policy:** Laya timeout (1.5 s) or error → log `laya_error`, continue with rules. Laya can never block a fetch.

### 3.6 Treg adapter
One interface, two implementations:

```python
class TregClient(Protocol):
    def find(self, name: str, company: str) -> TregResult: ...
    def verify(self, email: str) -> TregResult: ...

@dataclass
class TregResult:
    email: str | None
    domain: str | None
    status: Literal["valid","invalid","catch_all","unknown","risky","not_found","error"]
    raw: dict          # stored verbatim in treg_calls.raw_json
    cost_units: float  # from config if Treg doesn't report it
```
- `TregHttpClient` / `TregCliClient` — **[CONFIRM]** which one Treg is and the exact endpoints/commands and status vocabulary. Write a `map_status()` function that maps Treg's words onto our enum.
- `TregMockClient` — deterministic fake with a fixture file, used by all tests and by `TREG_MODE=mock`.

### 3.7 API & CLI surface
```
CLI
  bucketio fetch "NAME" "COMPANY" [--force] [--json]
  bucketio import contacts.csv          # Name,Company[,Email]
  bucketio export contacts.csv
  bucketio report [--since 7d]
  bucketio calibrate                    # Pass 6
  bucketio serve                        # web UI + API on :8080

HTTP
  POST /api/fetch        {"name","company","force"} → fetch JSON
  GET  /api/contacts?q=&status=&limit=&offset=
  GET  /api/contacts/{id}               → contact + lookups history
  GET  /api/report
  POST /api/import (multipart CSV)   GET /api/export
  GET  /health                          → db ok, laya ok/off, treg mode
```

### 3.8 Frontend
Single `index.html`: search box, "Fetch" form (Name, Company), and a table: Name | Company | Email | High-pattern email | Status (colored pill) | Confidence | Seen | Last verified | Route. Row click shows lookup history. Plain CSS, no framework, no build step.

### 3.9 Config (`.env`)
```
DB_PATH=./bucketio.db
TREG_MODE=mock            # mock | http | cli   [CONFIRM]
TREG_BASE_URL=            # [CONFIRM]
TREG_API_KEY=             # [CONFIRM]
TREG_FIND_COST=0.10       # [CONFIRM] $ per find
TREG_VERIFY_COST=0.01     # [CONFIRM] $ per verify
LAYA_MODE=shadow          # off | shadow | active
LAYA_TRANSPORT=http       # http | inprocess
LAYA_URL=http://127.0.0.1:8001
LAYA_API_KEY=change-me
LAYA_TIMEOUT_S=1.5
LAYA_WEIGHT=0.3
CACHE_TTL_DAYS=90
VERIFY_MIN_POSTERIOR=0.60
VERIFY_MIN_HITS=2
VERIFY_MAX_TRIES=2
GENERATE_VERIFY_TOP=1
USE_TF=0
```

### 3.10 Risks
| Risk | Mitigation |
|---|---|
| Laya zero-shot is weak on these custom questions | Shadow mode first; only activate on measured lift; calibrate temperatures; fine-tune later with collected labels. |
| Treg interface unknown | Adapter + mock; all logic testable without it. |
| Wrong merges (two different "John Smith"s at one company) | Merge only at ≥ 95 fuzzy or Laya ≥ 0.80; keep `merged_from` audit; `bucketio unmerge` in Pass 7. |
| Catch-all domains inflate "valid" | Store catch-all separately; never count catch-all as a pattern hit. |
| Stale data | TTL re-verify; `--force`. |
| Laya server exposed on network | Bind 127.0.0.1 via `--host` / env; always set `LAYA_API_KEY`. |
| Compliance | Store only business contact data; owner is responsible for CAN-SPAM/GDPR use of the output. Add a `do_not_contact` flag. |

---

## 4. Data Model (`schema.sql`)

```sql
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;
PRAGMA busy_timeout = 5000;

CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL);

-- Companies and their email domains
CREATE TABLE IF NOT EXISTS companies (
  id            INTEGER PRIMARY KEY,
  name          TEXT NOT NULL,               -- as first seen
  company_key   TEXT NOT NULL UNIQUE,        -- normalized
  domain        TEXT,                        -- e.g. acme.com (nullable until known)
  is_catch_all  INTEGER NOT NULL DEFAULT 0,
  mx_ok         INTEGER,                     -- 1/0/NULL unknown
  created_at    TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_companies_domain ON companies(domain);

-- Aliases so "ACME Corp" and "Acme Inc" resolve to one company
CREATE TABLE IF NOT EXISTS company_aliases (
  alias_key   TEXT PRIMARY KEY,
  company_id  INTEGER NOT NULL REFERENCES companies(id)
);

-- The "sheet": one row per real person
CREATE TABLE IF NOT EXISTS contacts (
  id                  INTEGER PRIMARY KEY,
  full_name           TEXT NOT NULL,          -- display, as first seen
  first_name          TEXT,
  middle_name         TEXT,
  last_name           TEXT,
  name_key            TEXT NOT NULL,          -- normalized "first last"
  company_id          INTEGER NOT NULL REFERENCES companies(id),
  email               TEXT,                   -- best known email
  email_source        TEXT CHECK (email_source IN
                        ('cache','treg_find','treg_verify','pattern','import','manual')),
  email_pattern       TEXT,                   -- e.g. first.last or 'custom'
  verification_status TEXT NOT NULL DEFAULT 'unverified' CHECK (verification_status IN
                        ('unverified','valid','invalid','catch_all','risky','unknown',
                         'pattern_guess','not_found','no_domain')),
  high_pattern_email  TEXT,                   -- top generated candidate
  confidence          REAL,                   -- 0..1
  seen_count          INTEGER NOT NULL DEFAULT 0,
  first_seen_at       TEXT NOT NULL DEFAULT (datetime('now')),
  last_seen_at        TEXT NOT NULL DEFAULT (datetime('now')),
  last_verified_at    TEXT,
  do_not_contact      INTEGER NOT NULL DEFAULT 0,
  merged_into         INTEGER REFERENCES contacts(id),   -- soft-merge
  UNIQUE (name_key, company_id)
);
CREATE INDEX IF NOT EXISTS idx_contacts_email  ON contacts(email);
CREATE INDEX IF NOT EXISTS idx_contacts_status ON contacts(verification_status);

-- Learned email formats per domain (Beta counts)
CREATE TABLE IF NOT EXISTS domain_patterns (
  domain         TEXT NOT NULL,
  pattern        TEXT NOT NULL,
  hits           INTEGER NOT NULL DEFAULT 0,   -- valid outcomes
  misses         INTEGER NOT NULL DEFAULT 0,   -- invalid outcomes
  verified_hits  INTEGER NOT NULL DEFAULT 0,   -- valid via Treg (find or verify)
  last_hit_at    TEXT,
  PRIMARY KEY (domain, pattern)
);

-- Global pattern priors (seeded, then re-estimated from all domains)
CREATE TABLE IF NOT EXISTS pattern_priors (
  pattern  TEXT PRIMARY KEY,
  prior    REAL NOT NULL
);

-- One row per fetch request (audit + metrics + Laya training labels)
CREATE TABLE IF NOT EXISTS lookups (
  id              INTEGER PRIMARY KEY,
  contact_id      INTEGER REFERENCES contacts(id),
  input_name      TEXT NOT NULL,
  input_company   TEXT NOT NULL,
  route           TEXT NOT NULL CHECK (route IN
                    ('cache_hit','catch_all','pattern_verify','treg_find','generate','error')),
  identity_method TEXT CHECK (identity_method IN ('exact','fuzzy_rule','laya','new')),
  result_email    TEXT,
  result_status   TEXT,
  confidence      REAL,
  cost_usd        REAL NOT NULL DEFAULT 0,
  est_saved_usd   REAL NOT NULL DEFAULT 0,     -- vs. baseline of one find
  laya_mode       TEXT NOT NULL,
  latency_ms      INTEGER,
  forced          INTEGER NOT NULL DEFAULT 0,
  created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_lookups_created ON lookups(created_at);

-- Every Treg call, raw output kept verbatim
CREATE TABLE IF NOT EXISTS treg_calls (
  id          INTEGER PRIMARY KEY,
  lookup_id   INTEGER NOT NULL REFERENCES lookups(id),
  kind        TEXT NOT NULL CHECK (kind IN ('find','verify')),
  request     TEXT NOT NULL,                 -- name|company or email
  status      TEXT NOT NULL,
  email       TEXT,
  cost_usd    REAL NOT NULL DEFAULT 0,
  raw_json    TEXT NOT NULL,
  created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Candidate emails generated per lookup
CREATE TABLE IF NOT EXISTS candidates (
  lookup_id    INTEGER NOT NULL REFERENCES lookups(id),
  email        TEXT NOT NULL,
  pattern      TEXT NOT NULL,
  rules_score  REAL NOT NULL,
  laya_prob    REAL,
  final_score  REAL NOT NULL,
  rank         INTEGER NOT NULL,
  outcome      TEXT,                          -- filled when verified: valid/invalid/catch_all
  PRIMARY KEY (lookup_id, email)
);

-- Every Laya question asked (shadow or active) + eventual ground truth
CREATE TABLE IF NOT EXISTS laya_decisions (
  id            INTEGER PRIMARY KEY,
  lookup_id     INTEGER NOT NULL REFERENCES lookups(id),
  question      TEXT NOT NULL CHECK (question IN ('identity','route','rank','plausible')),
  routed_model  TEXT,                         -- english / multilingual (from response.routing)
  answer        TEXT,                         -- chosen key
  confidence    REAL,
  probs_json    TEXT,                         -- full distribution
  rules_answer  TEXT,                         -- what the rule engine chose
  applied       INTEGER NOT NULL DEFAULT 0,   -- 1 if it changed the outcome (active mode)
  truth         TEXT,                         -- filled later from verification
  latency_ms    INTEGER,
  error         TEXT,
  created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Laya calibration output (Pass 6)
CREATE TABLE IF NOT EXISTS laya_calibration (
  question     TEXT NOT NULL,
  n_options    INTEGER NOT NULL,
  temperature  REAL NOT NULL,
  n_samples    INTEGER NOT NULL,
  accuracy     REAL,
  rules_acc    REAL,
  fitted_at    TEXT NOT NULL DEFAULT (datetime('now')),
  PRIMARY KEY (question, n_options)
);
```

**Identity key** = `(name_key, company_id)`. `company_id` is resolved through `company_aliases` and, once known, `domain` (two company names with the same domain collapse to one company).

---

## 5. Repository layout

```
bucketio/
  pyproject.toml
  .env.example
  schema.sql
  PROGRESS.md
  bucketio/
    __init__.py
    config.py          # pydantic-settings from .env
    db.py              # connect(), migrate(), tx() context manager
    normalize.py       # names, companies, nicknames, ASCII folding
    identity.py        # exact + fuzzy + Laya gray zone
    patterns.py        # render, reverse_match, stats, candidates, priors
    treg.py            # TregClient protocol, Http/Cli/Mock clients, map_status
    laya_client.py     # http + inprocess + off; question builders Q1–Q4
    resolver.py        # fetch() pipeline, routes R1–R5, learning, recording
    report.py          # metrics + cost report
    calibrate.py       # temperature fit + lift measurement
    csv_io.py
    api.py             # FastAPI app
    cli.py             # typer app
    web/index.html  web/style.css  web/app.js
  tests/
    fixtures/treg_mock.json
    test_normalize.py test_patterns.py test_identity.py
    test_resolver_routes.py test_laya_client.py test_api.py test_cli.py
```

---

## 6. Test fixtures the agent must create
`tests/fixtures/treg_mock.json` — deterministic mock Treg:
- `acme.com`: format `first.last`; `jane.doe`, `john.smith`, `mary.jones` valid; everything else invalid.
- `globex.io`: format `flast`.
- `initech.com`: catch-all (every verify returns `catch_all`).
- `ghost.co`: find always `not_found`, verify always `invalid`.
- A non-Latin name (e.g. `Анна Иванова` at `acme.com`) to prove ASCII folding / multilingual routing doesn't crash.

---

## 7. Agent passes (execute in order)

Each pass: implement → write tests → `pytest -q` green → append to `PROGRESS.md` (what was done, anything stubbed, next pass).

### Pass 0 — Scaffold
- `uv init`, deps, `pyproject.toml` with `bucketio` console script.
- `config.py`, `.env.example`, `db.py` with migration runner applying `schema.sql` and seeding `pattern_priors`.
- **Accept:** `bucketio --help` works; `python -c "from bucketio.db import migrate; migrate()"` creates all tables; test asserts tables and seed rows exist; re-running migrate is a no-op.

### Pass 1 — Normalization & identity (rules only)
- `normalize.py`: name splitting (handles "Last, First", middle names, suffixes, particles van/de/von), nickname map (~50 common), `unidecode` folding, company key stripping legal suffixes.
- `identity.py`: exact match, fuzzy via rapidfuzz, thresholds per §3.3, company alias resolution, seen_count increments. Gray zone → new contact (Laya comes later).
- **Accept:** "Bob Smith / Acme Inc" and "Robert Smith / ACME Corp" resolve to one contact; "Jane Doe" at two companies are two contacts; fetching the same person twice gives `seen_count=2`; Cyrillic name normalizes without error.

### Pass 2 — Pattern engine
- `patterns.py`: 12 patterns, `render`, `reverse_match`, Beta posterior, `record_outcome(domain, pattern, outcome)`, `candidates(name, domain, k=5)`, `reprior()` recomputing global priors from all domains.
- **Accept:** `reverse_match("jane.doe","Jane Doe") == ["first.last"]`; `jdoe` → `["flast"]`; after 3 valid `first.last` at acme.com, posterior > 0.6 and it ranks first; catch-all outcomes don't change counts.

### Pass 3 — Treg adapter + resolver (the money pass)
- `treg.py`: protocol, `TregMockClient` from fixture, stub `TregHttpClient`/`TregCliClient` raising `NotConfigured` until **[CONFIRM]** values set.
- `resolver.py`: full pipeline R1–R5 without Laya, recording `lookups`, `treg_calls`, `candidates`; cost + est_saved computed from config.
- **Accept (all with mock):**
  1. First `Jane Doe/Acme` → route `treg_find`, 1 find.
  2. `John Smith/Acme` → still `treg_find` (only 1 verified hit so far).
  3. `Mary Jones/Acme` → `pattern_verify`, 0 finds, 1 verify, valid.
  4. Re-fetch Jane → `cache_hit`, 0 Treg calls.
  5. Anyone at `initech.com` after first find → `catch_all`, 0 verifies.
  6. `ghost.co` → `generate`, returns `high_pattern_email` with confidence < 0.5 and 5 alternates.
  7. Invalid verify at a pattern domain increments misses and tries next pattern (max 2).
  8. `--force` bypasses R1.

### Pass 4 — CLI, API, frontend
- `cli.py`: fetch/import/export/report/serve. `fetch` prints the §2.5 JSON.
- `api.py`: endpoints §3.7, `/health`.
- `web/`: page per §3.8.
- **Accept:** `bucketio fetch "Jane Doe" "Acme Inc" --json` prints valid JSON matching the §2.5 keys; API tests via `TestClient`; CSV round-trip import→export preserves rows; page loads and lists contacts (manual check, screenshot noted in PROGRESS.md).

### Pass 5 — Laya in shadow mode
- Install `laya[serve]`; add `scripts/run_laya.sh`: `USE_TF=0 LAYA_PRELOAD=1 LAYA_API_KEY=$LAYA_API_KEY laya-serve` bound to 127.0.0.1:8001 (check `laya-serve --help` for the host/port flags; if none, run behind `uvicorn` host flag or firewall and note it).
- `laya_client.py`: builders for Q1–Q4 per §3.5; HTTP transport with timeout; `inprocess` transport using `laya.Router(preload=True)`; `off` transport.
- Wire into resolver: in `shadow`, ask Q1 (gray zone), Q2 (gray zone), Q3 (every generate + every pattern_verify), Q4 (every find hit); store in `laya_decisions` with `rules_answer`; **never** change outcomes.
- Backfill `truth`: when a verify result arrives, update matching `laya_decisions.truth` and `candidates.outcome`.
- **Accept:** with `respx`-mocked Laya, shadow mode produces identical fetch outputs to `LAYA_MODE=off` (golden test); Laya timeout doesn't fail fetch; `/health` shows Laya status; one real smoke test against the live sidecar (skipped in CI if not reachable) returns a `routing.model` value.

### Pass 6 — Calibration and activation
- `calibrate.py`: from `laya_decisions` with `truth`, fit one temperature per (question, n_options) by minimizing log loss (grid search 0.5–5.0 is fine), compute Laya accuracy vs rules accuracy, write `laya_calibration`.
- `report` shows lift. `LAYA_MODE=active` applies calibrated temperatures and uses Laya only for question types where `accuracy > rules_acc` and `n_samples ≥ 50`; other question types stay rules-only automatically.
- **Accept:** synthetic test data where Laya is better on `rank` and worse on `route` → activation enables only `rank`; blended ranking changes top candidate in a constructed case; with <50 samples nothing activates.

### Pass 7 — Hardening
- Concurrency test: 20 parallel fetches (threads) against WAL DB, no `database is locked` errors.
- Idempotency: same fetch in flight twice → one Treg call (per-identity lock).
- `bucketio unmerge <id>`, `do_not_contact` flag respected in export.
- Nightly `sqlite3 .backup` script; `bucketio report --since 7d`.
- **Accept:** all tests green; `PROGRESS.md` has final metrics section template.

---

## 8. Definition of done (v1)
- Fetch works end-to-end with mock Treg and live Laya sidecar in shadow mode.
- Report shows find calls avoided and $ saved.
- Swapping `TREG_MODE=mock` → real adapter is a config change plus `map_status()` fill-in.
- Laya activation is data-driven, per question type, and reversible by setting `LAYA_MODE=shadow`.

---

## 9. Open questions for the owner [CONFIRM]
1. **Treg interface:** HTTP API or CLI? Endpoints/commands for find and verify, auth, rate limits, and its exact status words (valid / invalid / catch-all / risky / unknown?).
2. **Treg prices** per find and per verify (drives the cost report and thresholds).
3. **Does Treg return the company domain** on a find? If not, is there another cheap domain source we should use, or should BucketIO guess `companyname.com` + MX check?
4. Default `CACHE_TTL_DAYS` (90 proposed) and whether catch-all emails are acceptable output for your use.
5. GPU available? (Changes nothing functionally; Laya calls go from ~300 ms to ~35 ms.)