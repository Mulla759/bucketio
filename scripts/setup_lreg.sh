#!/usr/bin/env sh
# Lreg setup (macOS / Linux) - Laya + treg + BucketIO in one command.
#
#   ./scripts/setup_lreg.sh              # full setup, then serve the web UI
#   ./scripts/setup_lreg.sh --no-start   # set everything up, do not start anything
#   ./scripts/setup_lreg.sh --skip-laya  # BucketIO only (no model download)
set -eu

SKIP_LAYA=0
NO_START=0
LAYA_PORT="${LAYA_PORT:-8001}"
WEB_PORT="${WEB_PORT:-8080}"

for arg in "$@"; do
  case "$arg" in
    --skip-laya) SKIP_LAYA=1 ;;
    --no-start) NO_START=1 ;;
    *) echo "[lreg] unknown option: $arg" >&2; exit 2 ;;
  esac
done

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT"

info() { printf '[lreg] %s\n' "$1"; }
warn() { printf '[lreg] %s\n' "$1" >&2; }
fail() { printf '[lreg] %s\n' "$1" >&2; exit 1; }

# --- 1. prerequisites -------------------------------------------------------
command -v uv >/dev/null 2>&1 || fail "uv is required (Python 3.11-3.13). Install: curl -LsSf https://astral.sh/uv/install.sh | sh"
[ -f .python-version ] || printf '3.13\n' > .python-version

# --- 2. application environment --------------------------------------------
info "syncing BucketIO environment (uv sync --extra dev)"
uv sync --extra dev

# --- 3. .env ----------------------------------------------------------------
if [ ! -f .env ]; then
  cp .env.example .env
  info "created .env from .env.example"
fi
if [ "$SKIP_LAYA" -eq 0 ]; then
  sed -i.bak -e "s|^LAYA_MODE=.*|LAYA_MODE=shadow|" \
             -e "s|^LAYA_URL=.*|LAYA_URL=http://127.0.0.1:${LAYA_PORT}|" \
             -e "s|^LAYA_TIMEOUT_S=.*|LAYA_TIMEOUT_S=4.0|" .env && rm -f .env.bak
fi
grep -q '^TREG_MODE=' .env || printf 'TREG_MODE=http\n' >> .env

# --- 4. Laya sidecar --------------------------------------------------------
if [ "$SKIP_LAYA" -eq 0 ]; then
  if [ ! -d .laya-venv ]; then
    info "creating .laya-venv (Python 3.13) - separate from the app venv"
    uv venv .laya-venv --python 3.13
  fi
  info "installing laya[serve] (torch is large; first run also downloads ~1.5 GB of weights)"
  uv pip install --python .laya-venv/bin/python "laya[serve]>=0.3.20"
fi

# --- 5. database ------------------------------------------------------------
info "applying schema"
uv run bucketio init || warn "bucketio init failed - run it manually after fixing the error"

# --- 6. start ---------------------------------------------------------------
if [ "$SKIP_LAYA" -eq 1 ] || [ "$NO_START" -eq 1 ]; then
  info "setup complete. Next:"
  [ "$SKIP_LAYA" -eq 0 ] && info "  ./scripts/run_laya.sh        # start the Laya sidecar"
  info "  uv run bucketio serve --port ${WEB_PORT}"
  exit 0
fi

mkdir -p .lreg/logs
export USE_TF=0 LAYA_HOST=127.0.0.1 LAYA_PORT="$LAYA_PORT" LAYA_PRELOAD=1 LAYA_DEVICE=cpu
export LAYA_API_KEY="${LAYA_API_KEY:-change-me}"
info "starting Laya sidecar on 127.0.0.1:${LAYA_PORT} (weights download on first run)"
nohup .laya-venv/bin/laya-serve > .lreg/logs/laya.out.log 2> .lreg/logs/laya.err.log &
echo $! > .lreg/laya.pid
info "Laya pid $(cat .lreg/laya.pid) (logs: .lreg/logs/laya.*.log)"

info "starting BucketIO on http://127.0.0.1:${WEB_PORT}"
uv run bucketio serve --host 127.0.0.1 --port "${WEB_PORT}"

