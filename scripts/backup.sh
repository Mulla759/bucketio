#!/usr/bin/env sh
# Backup the BucketIO SQLite database (safe while the app is running: uses
# sqlite3's online backup API, so WAL writers are not disturbed).
#
#   ./scripts/backup.sh [db_path] [out_dir]
set -eu
DB_PATH="${1:-./bucketio.db}"
OUT_DIR="${2:-./backups}"
[ -f "$DB_PATH" ] || { echo "[backup] no database at $DB_PATH" >&2; exit 1; }
mkdir -p "$OUT_DIR"
TARGET="$OUT_DIR/bucketio-$(date +%Y%m%d-%H%M%S).db"
uv run python -c "import sqlite3, sys; src = sqlite3.connect(sys.argv[1]); dst = sqlite3.connect(sys.argv[2]); src.backup(dst); dst.close(); src.close(); print('backed up ->', sys.argv[2])" "$DB_PATH" "$TARGET"
