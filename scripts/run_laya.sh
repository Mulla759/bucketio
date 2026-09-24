#!/usr/bin/env bash
set -euo pipefail

export USE_TF=0
export LAYA_HOST=127.0.0.1
export LAYA_PORT=8001
export LAYA_PRELOAD=1
export LAYA_DEVICE=cpu
export LAYA_API_KEY="${LAYA_API_KEY:-change-me}"

echo "BucketIO Laya sidecar -> http://127.0.0.1:8001 (Ctrl+C to stop)"
echo 'Needs the server extras: uv pip install "laya[serve]"'

exec laya-serve
