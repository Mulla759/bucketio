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

## Pass 5 (groundwork) — Laya client

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

**Real `POST /v1/systemone` schema** (fetched 2026-09-24, laya 0.3.20 —
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

**Deviations from bucketio.md §3.5:**
- States/criteria match §3.5 Q1-Q4 exactly; question **names** are
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

**Next:** resolver wiring (Pass 3 owns `bucketio/resolver.py`) — `LayaClient`,
the Q1-Q4 builders and `laya_decisions` rows are ready to consume.
