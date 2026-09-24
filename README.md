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
