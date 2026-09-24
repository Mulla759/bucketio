# BucketIO

A local, self-hosted contact store (SQLite) that sits **in front of Treg**. It answers
"what is this person's work email?" by spending as little as possible:

1. Known + recently verified contact → return it, **$0**.
2. Company email format known → build the address and ask Treg to **verify** (cheap).
3. Otherwise ask Treg to **find** (expensive) — and learn the company's format from the answer.
4. Nothing found → return the highest-probability generated address.

[Laya](https://huggingface.co/convaiinnovations/laya) runs as a local sidecar and acts as a
**scorer / tie-breaker** in the gray zones — never as a generator.

Full build plan and rationale: [`bucketio.md`](bucketio.md).

## Quick start (offline, no keys)

```powershell
uv sync --extra dev
uv run bucketio --help
uv run pytest -q
```

## Real mode

Copy `.env.example` to `.env`, set `TREG_MODE=http` (token is picked up from `~/.treg/config.json`
if `TREG_TOKEN` is blank), then optionally start the Laya sidecar:

```powershell
scripts\run_laya.ps1        # downloads weights on first run, serves 127.0.0.1:8001
uv run bucketio serve
```
