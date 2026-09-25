# Prev — session handoff (2026-09-24)

## Where we are

- Checked out: **`main` @ `e141a46`** (clean tree). The repo is the **BucketIO** local
  contact store: SQLite + FastAPI + typer CLI that fronts Treg (email find/verify) and
  uses a local Laya model as a scored shadow/active tie-breaker.
- **`main` = post-v1 core, 201 tests passing** (re-verified this session: `uv run pytest -q` → 201 passed).
- The entire **directory marketing site / frontend** work from today **sits on unmerged
  branches**, not on `main`:
  1. `origin/design/handoff` (`cddf20b`) — the phone-book design handoff: `design/`
     (prototype `BucketIO Directory v3.dc.html`, `README.md`, fonts, `uploads/` mood
     references, research notes) + a stray `copy-command.png` at repo root.
  2. `origin/feat/companies-endpoint` (`181e321`) — `GET /api/companies` (yellow pages)
     + `test_companies_lists_learned_formats` (+23 lines in `tests/test_api.py`).
  3. `origin/feat/directory-frontend` (`aaf1187`) — Vite 8 + React 19 + TS app in
     `frontend/src/`; build (`npm run build`) writes the site into **`bucketio/web`**
     (deleting `app.js`/`style.css`), which `bucketio serve` mounts. Adds `/api/companies`.
  4. `origin/docs/directory-and-changelog` (`e2fe045` → `c00f53e`) — superset of #3 +
     PROGRESS.md (6 new passes up to "Frontend polish 5"), README.md (202 badges, Web UI
     + Layout + security sections, `.gitignore` for `frontend/`).

  Suggested merge order (they are a linear chain on top of `main`):
  `design/handoff` → `feat/companies-endpoint` → `feat/directory-frontend` →
  `docs/directory-and-changelog`.

## v1 core — everything that shipped on main (Passes 0–7)

Working modules (all under `bucketio/`): `normalize.py` (Unidecode folding, name parts,
nicknames, company suffix stripping), `patterns.py` (12 formats + Beta-posterior priors),
`identity.py` (alias/company keys, fuzzy 95-rule / gray-zone), `treg.py` (mock/http/cli
clients), `resolver.py` (R1 cache → R2 catch-all → R3 verify → R4 find → R5 generate,
cost accounting), `laya_client.py` (off/http/inprocess transports, Q1–Q4 builders),
`calibrate.py` (temperature fit, accuracy gate), `report.py`, `csv_io.py`, `api.py`, `cli.py`.

- Pass 5/6/7 shipped: per-identity thread lock, company-create race fix, `unmerge` CLI,
  DNC compliance on exports, online backups, `calibrate` CLI, Laya shadow + gated active
  (Q1 merge / Q2 route / Q3 rank blend) — all `applied`-flag, reversible via `LAYA_MODE=shadow`.
- CI (`.github/workflows/ci.yml`): pytest on 3.11/3.13 + offline CLI smoke. MIT LICENSE.
- Live end-to-end used mock Treg + a real Laya sidecar (`127.0.0.1:8001`, shadow mode);
  measured CPU latency was 0.7–2.0 s, so `LAYA_TIMEOUT_S=4.0` is the default everywhere.

## The directory frontend (unmerged) — what it is

A Vite+React phone-book site (`frontend/`): one component per section — Cover (3D book,
click-to-open), Features, White Pages, Yellow Pages (`/api/companies`), Directory
Assistance (live `/api/fetch` mapped onto the "toll ticket"), Docs, Setup, Contact
(editorial back-cover spread with newspaper-clipping portrait). Stack: React 19, GSAP +
ScrollTrigger + @gsap/react, Lenis, Vanta/three lazy-loaded, all under
`prefers-reduced-motion`. Build commits hashed assets + self-hosted fonts + favicon/OG
graphics into `bucketio/web`.

**I re-verified the tip (`c00f53e`) this session in a throwaway worktree:**
- `uv run pytest -q` → **202 passed** (new test parses the built `index.html` for the
  hashed JS/CSS bundles instead of `/app.js` + `/style.css`).
- `npm run typecheck` clean, `npm run build` clean, and the rebuilt `bucketio/web`
  was **byte-identical to the committed build** (only `frontend/package-lock.json`
  got touched after `npm install` — npm 10.9.2 lockfile churn).
- `GET /api/companies` returns `{id,name,domain,pattern,confidence,seen,is_catch_all}`
  with beta-posterior confidence; `q`/`limit`/`offset` wired and tested.

## What's working

- Core pipeline, tests, CLI, API, report/CSV (201 green on main / 202 on the branch).
- The new frontend builds and serves via `bucketio serve`; `/api/companies` works.
- Laya shadow/active machinery, calibration gate, hardening, backups, unmerge, DNC export.
- Security sweep clean: no secrets/paths/machine names in the tree; BOM/mojibake fixed on
  the branch (PROGRESS.md is valid UTF-8 there).

## What's NOT working / open gaps

- **Nothing merged.** All four branches above are unpublished work relative to `main`;
  the repo README/badges still claim the old static UI + 201 tests. Merging
  `docs/directory-and-changelog` (after the others) is the pending step.
- **Real Treg lookups still off.** `TREG_MODE=mock` is the default; the token exists in
  `~/.treg/config.json`, but nothing was switched to `TREG_MODE=http` for live lookups.
- **Laya is not self-starting.** The sidecar must be launched manually
  (`scripts/run_laya.sh`), defaults `LAYA_MODE=off`, and activation still needs
  **≥50 labelled shadow samples** with `accuracy > rules_acc` before anything turns on.
- **Frontend not in CI.** `ci.yml` runs pytest only — no `npm ci && npm run typecheck &&
  npm run build`, so a broken build could merge unnoticed. (Branch PROGRESS lists this as
  the optional next step.)
- **Vite chunk-size warning.** `index-*.js` ~438 kB and `three.module-*.js` ~737 kB trip
  the >500 kB warn; code-split Vanta/three already exist but the bundle size was never
  tuned (`dynamic import()` / code-splitting notes are in the build output).
- **Handoff art not ported.** The two airbrush Fig. 01/02 plates and the `image-slot`
  web component were intentionally left out of the React port.
- **`copy-command.png` at repo root** on `design/handoff` is a stray screenshot — probably
  should move under `design/` or be dropped before merge.
- **Rates footnote:** Treg prices ($0.00483 find / $0.0019 verify) are "as of Sept 2026"
  in the site copy and `docs/LREG.md` — re-check before any external launch.
- **Documented spec deviations** (deliberate, pinned in PROGRESS): R2 catch-all falls
  back to the strongest global prior when no pattern rows exist; gray-zone identity is
  treated as `new`; `laya.net` — no, `TregCliClient` needs the `treg` binary; `resolver`
  routes treat `risky`/`unknown` finds as valid-but-uncacheable.
- Minor: `frontend/package-lock.json` gets reformatted by a newer `npm install` (lockfile
  churn only; `npm ci` still works) and `frontend/node_modules` (~102 MB) is gitignored.

## Suggested next steps

1. Merge the four branches in order (or squash `docs/directory-and-changelog`).
2. Add a `frontend` job to `ci.yml` (typecheck + build; assert `bucketio/web` regenerates clean).
3. Run the plan's ~50 fetches in shadow against real Treg (`TREG_MODE=http`), then
   `bucketio calibrate` to decide whether any question type may activate.
4. Pre-launch: re-check Treg rates, port (or consciously drop) the Fig. 01/02 plates,
   and decide on chunk splitting if page weight matters.