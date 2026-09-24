# Lreg — Laya + treg + BucketIO in one stack

**Lreg** is the bundle: BucketIO (this repo) + the [Laya](https://huggingface.co/convaiinnovations/laya)
decision model running as a local sidecar + the [treg](https://treg.to) contact-data gateway.
One command brings all three up; BucketIO works with any one of them missing.

```
CLI / HTTP ─► BucketIO resolver ─┬─► SQLite (bucketio.db, WAL)
                                 ├─► treg  (find / verify, pay per success)
                                 └─► Laya  (127.0.0.1:8001, classifier, free, local)
```

## Quick start (Windows)

```powershell
git clone <this repo> bucketio
cd bucketio
.\scripts\setup_lreg.ps1
```

macOS / Linux:

```sh
./scripts/setup_lreg.sh
```

What the script does, in order:

1. `uv sync --extra dev` — the app venv (Python 3.13).
2. Creates `.env` from `.env.example` if missing.
3. Creates `.laya-venv` and `uv pip install "laya[serve]>=0.3.20"` — a **separate** venv, because
   the model stack (torch) is heavy and BucketIO never imports it.
4. `bucketio init` — applies `bucketio/schema.sql` and seeds pattern priors.
5. Starts `laya-serve` on `127.0.0.1:8001` (first run downloads ~1.5 GB of weights from
   HuggingFace; logs in `.lreg/logs/`).
6. Starts `bucketio serve` on `http://127.0.0.1:8080`.

Useful flags: `-SkipLaya` (BucketIO only), `-NoStart` (set up, start nothing).

## What runs where

| Piece | Process | Port | Config |
|---|---|---|---|
| BucketIO API + UI | `bucketio serve` | 8080 | `.env` (`DB_PATH`, `TREG_MODE`) |
| Laya sidecar | `laya-serve` | 8001 | env only (`LAYA_HOST`, `LAYA_PORT`, `LAYA_PRELOAD`, `LAYA_DEVICE`, `LAYA_API_KEY`, `USE_TF=0`) |
| treg | remote | 443 | `TREG_MODE=http`, token from `TREG_TOKEN` or `~/.treg/config.json` |

`lreg.yaml` describes the stack; `bucketio lreg status` reads it and reports what is actually
running (DB, Laya health, treg mode, web URL) — it exits 0 even when something is down.

## Modes (safe by default)

- `TREG_MODE=mock` — deterministic fixture, no network, no cost. Default.
- `TREG_MODE=http` — real treg calls (`treg.people.email.find` / `treg.people.email.verify`).
- `LAYA_MODE=off|shadow|active` — `shadow` asks and logs Laya but never lets it change an
  outcome; `active` applies it only for question types where calibration shows it beats the
  rules (`accuracy > rules_acc` with `n_samples >= 50`). Flip back to `shadow` at any time —
  activation is per question type and reversible.

## Day-2 operations

```powershell
uv run bucketio lreg status          # what is up, what is configured
uv run bucketio report --since 7d    # finds avoided, verifies used, $ saved, Laya lift
uv run bucketio calibrate            # fit temperatures + show the activation gate
uv run bucketio fetch "Jane Doe" "Acme Inc" --json
```

Stop the sidecar: kill the pid in `.lreg/laya.pid` (or `Stop-Process -Id (Get-Content .lreg/laya.pid)`).

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| First Laya call times out | The first request loads a checkpoint, and longer states (candidate lists) cost more: ~0.5 s for a short route question, ~1.3–1.5 s for a rank question on CPU. `LAYA_TIMEOUT_S=4.0` covers both; retry once if a cold start still exceeds it. |
| `laya-serve` hangs at startup | TensorFlow is installed in the same env. `USE_TF=0` is already set by the scripts. |
| `/health` shows `laya.reachable: false` | Sidecar not running, wrong port, or `LAYA_API_KEY` mismatch. Check `.lreg/logs/laya.err.log`. |
| treg returns 402 | Out of balance. `treg balance`; top up in the treg dashboard, or connect your own key. |
| treg returns 503 `provider_capacity_unavailable` | treg's own provider account is out; retry in a minute or use your own key. Nothing was charged. |
| Laya answers look overconfident | Run `bucketio calibrate`; `active` only ever uses calibrated, gated question types. |

## Security

- Laya binds `127.0.0.1` and requires `LAYA_API_KEY` (`change-me` by default — change it in
  `.env`/`lreg.yaml` for anything shared).
- Secrets live in `.env` only (git-ignored); never in the DB or logs.
- BucketIO stores business contact data; you own CAN-SPAM/GDPR compliance for how you use it.
  The `do_not_contact` flag is respected on export.
