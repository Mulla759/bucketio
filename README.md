# BucketIO

A local, self-hosted contact store (SQLite) that sits **in front of [Treg](https://treg.to)**.
It answers "what is this person's work email?" while spending as little as possible:

1. Known + recently verified contact → return it, **$0**.
2. Company email format known → build the address and ask Treg to **verify** (~$0.0015).
3. Otherwise ask Treg to **find** (~$0.0048–$0.15) — and learn the company's format
   from the answer, so the next person at that company is cheap.
4. Nothing found → return the highest-probability generated address with a confidence.

[Laya](https://huggingface.co/convaiinnovations/laya) runs as a **local sidecar** and acts as a
scorer / tie-breaker in the gray zones — never as a generator, and never trusted blindly:
it starts in `shadow` (asked and logged, zero influence) and is switched on per question type
only when `bucketio calibrate` shows it beats the rules.

Full build plan and rationale: [`bucketio.md`](bucketio.md).
Stack guide (Laya + treg + BucketIO): [`docs/LREG.md`](docs/LREG.md).

## How it saves money

Every fetch takes the first route that applies, and the route decides the cost:

| Route | When | Treg calls | Cost |
|---|---|---|---|
| `cache_hit` | known contact, verified within `CACHE_TTL_DAYS` (90) | 0 | $0 |
| `catch_all` | domain is catch-all and a pattern is learned | 0 | $0 |
| `pattern_verify` | domain pattern known (posterior ≥ 0.60, ≥ 2 verified hits) | 1 verify | ~$0.0015 |
| `treg_find` | nothing known yet | 1 find | $0.0048–$0.15 |
| `generate` | find missed; rank patterns by learned posterior | 0–1 verify | $0–$0.0015 |

A `treg_find` teaches the domain's format (`jane.doe@acme.com` → `first.last`), so the
**next** person at that company is a `pattern_verify`. Measured on the live end-to-end run:
6 fetches, 4 finds, 2 verifies → **$0.0115 saved** against an all-find baseline.

Every outcome (valid or invalid) updates a per-domain Beta posterior, so a wrong guess is
avoided next time. Catch-all domains are marked once and never spend a verify again.

## Quick start (offline, no keys)

```powershell
uv sync --extra dev
uv run bucketio init
uv run bucketio fetch "Jane Doe" "Acme Inc" --json   # TREG_MODE=mock by default
uv run pytest -q                                     # 201 tests
```

## Quick start (the Lreg bundle)

```powershell
.\scripts\setup_lreg.ps1     # macOS/Linux: ./scripts/setup_lreg.sh
```

Installs the app + `laya[serve]` (separate venv), creates `.env`, applies the schema, starts
the Laya sidecar on `127.0.0.1:8001` and the web UI on `http://127.0.0.1:8080`.

```powershell
uv run bucketio lreg status      # what is up / what is configured
uv run bucketio report --since 7d
uv run bucketio calibrate
```

## Treg calls (live, 2026-09-24)

| Job | Endpoint | Price |
|---|---|---|
| Find a work email | `treg.people.email.find` (routed, 22 providers) | from $0.004834/hit |
| Verify an email | `treg.people.email.verify` (routed, 11 providers) | $0 (ContactOut) → $0.0138 |

`TREG_MODE=http` uses the token from `TREG_TOKEN` or, if blank, from `~/.treg/config.json`
(written by `treg login`). Verify is 3–60× cheaper than find, which is the whole point.

## Laya: shadow first, active when measured

Laya is a **classifier** — it never writes an email. BucketIO generates candidates from the
learned patterns and asks Laya up to four choice questions per fetch:

| Question | Asked when | Active effect (gated) |
|---|---|---|
| Q1 identity | fuzzy match lands in 80–95 | merge into the existing contact at ≥ 0.80 |
| Q2 route | best pattern posterior in [0.45, 0.60) or only 1 verified hit | force/skip the pattern verify at ≥ 0.75 |
| Q3 rank | every `generate` and `pattern_verify` | blend `0.7·rules + 0.3·Laya` and re-rank |
| Q4 plausible | every `treg_find` hit | logged only (conflict audit) |

Modes: `off` → `shadow` (asked and logged, **zero** influence — a golden test asserts
byte-identical outputs to `off`) → `active`. Activation is per question type and
data-driven: `bucketio calibrate` fits one temperature per (question, option count) and
enables a type only when `accuracy > rules_accuracy` with `n_samples ≥ 50`. Flip back to
`shadow` at any time.

Measured on this machine (CPU, `LAYA_PRELOAD=1`): ~0.7–1.0 s for a `route` question and
~1.3–2.0 s for a `rank` question with 12 candidates — hence `LAYA_TIMEOUT_S=4.0`. A Laya
timeout or error is recorded and never blocks a fetch.

## Operations

```powershell
uv run bucketio lreg status        # stack health (DB, Laya, treg, web)
uv run bucketio report --since 7d  # routes, calls, $ saved, Laya agreement
uv run bucketio calibrate          # fit temperatures + show the activation gate
uv run bucketio unmerge 412        # undo a soft merge
.\scripts\backup.ps1               # online SQLite backup -> backups/
```

`do_not_contact = 1` contacts are never exported (CSV or `/api/export`). Concurrent
identical fetches are serialised per identity, so a duplicate in flight costs nothing extra.

## Results (live end-to-end: mock Treg + real Laya sidecar, `shadow`)

| Input | Route | Result |
|---|---|---|
| Jane Doe / Acme Inc | `treg_find` | jane.doe@acme.com (valid) |
| John Smith / Acme | `treg_find` | john.smith@acme.com (valid) |
| Mary Jones / Acme Inc | `pattern_verify` | mary.jones@acme.com — 1 verify, 0 finds |
| Casper Ghost / Ghost Co | `generate` | casper.ghost@ghost.co (pattern_guess) |
| Peter Gibbons / Initech | `treg_find` | catch-all domain learned from the hit |
| Milton Waddams / Initech | `catch_all` | 0 Treg calls |

Report: `find=4 verify=2 cost=$0.0175 est_saved=$0.0115`; Laya answered all 6 questions
(`routed_model: english`, `applied: 0`) with truth backfilled; calibration fitted 1 row and
correctly enabled nothing (< 50 samples).

## Layout

```
bucketio/
  schema.sql          # SQLite schema (packaged; migrate() is idempotent)
  config.py           # pydantic-settings, safe offline defaults
  db.py               # connect / migrate / tx
  normalize.py        # names, nicknames, ASCII folding, company keys
  identity.py         # exact + fuzzy identity, company aliases
  patterns.py         # 12 email patterns, reverse-match, Beta posteriors
  treg.py             # Treg adapter: mock / http / cli
  resolver.py         # the pipeline: R1 cache → R2 catch_all → R3 verify → R4 find → R5 generate
  laya_client.py      # Laya sidecar client + Q1–Q4 question builders
  calibrate.py        # temperature fit + activation gate
  report.py           # finds avoided, $ saved, Laya lift
  csv_io.py           # sheet import/export (do_not_contact respected)
  api.py  cli.py      # FastAPI + typer
  web/                # index.html, style.css, app.js (no build step)
scripts/              # setup_lreg.*, run_laya.*, backup.*
tests/                # 201 tests; fixtures/treg_mock.json
```
