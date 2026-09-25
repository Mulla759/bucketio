"""Vercel Python serverless entry point for the BucketIO FastAPI app.

Vercel's Python runtime looks for an ASGI ``app`` in this module. We make the
repository root importable, force SQLite onto a writable path (``/tmp`` is the
only writable directory on Vercel), run the idempotent migration at import time
so the schema exists even when the ASGI lifespan is not executed, then re-export
the FastAPI application from :mod:`bucketio.api`.
"""

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault("DB_PATH", "/tmp/bucketio.db")

from bucketio import config, db  # noqa: E402

_conn = db.migrate(config.get_settings().db_path)
_conn.close()

from bucketio.api import app  # noqa: E402,F401
