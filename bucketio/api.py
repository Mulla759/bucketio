"""FastAPI app: JSON API + the static web UI.

``create_app(settings)`` builds a fresh app around one Settings object; the
module-level ``app`` is what ``uvicorn bucketio.api:app`` (and ``bucketio
serve``) imports. A connection is opened and closed per request because
sqlite3 connections are not safe to share across threads. All API routes are
registered before the ``/`` static mount, which must come last.
"""

from __future__ import annotations

import io
import sqlite3
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from typing import Iterator

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from . import __version__, config, csv_io, db, patterns
from . import report as report_mod
from .laya_client import LayaClient
from .resolver import fetch as resolver_fetch, to_json
from .treg import NotConfigured, make_client

WEB_DIR = Path(__file__).resolve().parent / "web"


class FetchRequest(BaseModel):
    name: str = Field(min_length=1)
    company: str = Field(min_length=1)
    force: bool = False

    @field_validator("name", "company")
    @classmethod
    def _strip_required(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("must not be blank")
        return text


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _contact_item(row: sqlite3.Row) -> dict:
    return {
        "id": int(row["id"]),
        "name": row["full_name"],
        "full_name": row["full_name"],
        "company": row["company"],
        "email": row["email"],
        "high_pattern_email": row["high_pattern_email"],
        "verification_status": row["verification_status"],
        "confidence": row["confidence"],
        "seen_count": int(row["seen_count"]),
        "last_verified_at": row["last_verified_at"],
        "route": row["route"],
    }


def _contact_detail(row: sqlite3.Row) -> dict:
    data = {key: row[key] for key in row.keys()}
    data["id"] = int(row["id"])
    data["name"] = row["full_name"]
    data["company"] = row["company"]
    data["company_name"] = row["company"]
    data["domain"] = row["company_domain"]
    data["company_domain"] = row["company_domain"]
    data["company_id"] = int(row["company_id"])
    data["seen_count"] = int(row["seen_count"])
    data["do_not_contact"] = bool(row["do_not_contact"])
    data["merged_into"] = row["merged_into"]
    return data


_LOOKUP_COLUMNS = (
    "id",
    "input_name",
    "input_company",
    "route",
    "identity_method",
    "result_email",
    "result_status",
    "confidence",
    "cost_usd",
    "est_saved_usd",
    "laya_mode",
    "latency_ms",
    "forced",
    "created_at",
)


def _lookup_item(row: sqlite3.Row) -> dict:
    data = {key: row[key] for key in _LOOKUP_COLUMNS}
    data["id"] = int(row["id"])
    data["forced"] = bool(row["forced"])
    if row["latency_ms"] is not None:
        data["latency_ms"] = int(row["latency_ms"])
    return data


def create_app(settings=None) -> FastAPI:
    settings = settings or config.get_settings()
    db_path = settings.db_path

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        conn = db.migrate(db_path)
        conn.close()
        yield

    app = FastAPI(title="BucketIO", version=__version__, lifespan=lifespan)

    @contextmanager
    def connection() -> Iterator[sqlite3.Connection]:
        conn = db.connect(db_path)
        try:
            yield conn
        finally:
            conn.close()

    @app.post("/api/fetch")
    def api_fetch(payload: FetchRequest) -> dict:
        client = make_client(settings)
        try:
            with connection() as conn:
                result = resolver_fetch(
                    conn,
                    payload.name,
                    payload.company,
                    force=payload.force,
                    client=client,
                )
        except NotConfigured as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        finally:
            close = getattr(client, "close", None)
            if callable(close):
                close()
        return to_json(result)

    @app.get("/api/contacts")
    def api_contacts(
        q: str = "",
        status: str = "",
        limit: int = Query(50, ge=0),
        offset: int = Query(0, ge=0),
    ) -> dict:
        where = ["c.merged_into IS NULL"]
        params: list[object] = []
        if q.strip():
            like = f"%{_escape_like(q.strip())}%"
            where.append(
                "(c.full_name LIKE ? ESCAPE '\\' OR co.name LIKE ? ESCAPE '\\' "
                "OR c.email LIKE ? ESCAPE '\\')"
            )
            params.extend([like, like, like])
        if status.strip():
            where.append("c.verification_status = ?")
            params.append(status.strip())
        clause = " AND ".join(where)
        with connection() as conn:
            total = int(
                conn.execute(
                    "SELECT COUNT(*) AS n FROM contacts c "
                    "JOIN companies co ON co.id = c.company_id "
                    f"WHERE {clause}",
                    params,
                ).fetchone()["n"]
            )
            rows = conn.execute(
                f"""
                SELECT c.id, c.full_name, c.email, c.high_pattern_email,
                       c.verification_status, c.confidence, c.seen_count,
                       c.last_verified_at, co.name AS company,
                       (SELECT l.route FROM lookups l WHERE l.contact_id = c.id
                         ORDER BY l.id DESC LIMIT 1) AS route
                FROM contacts c JOIN companies co ON co.id = c.company_id
                WHERE {clause}
                ORDER BY c.id DESC
                LIMIT ? OFFSET ?
                """,
                params + [limit, offset],
            ).fetchall()
        return {"items": [_contact_item(row) for row in rows], "total": total}

    @app.get("/api/companies")
    def api_companies(
        q: str = "",
        limit: int = Query(500, ge=0),
        offset: int = Query(0, ge=0),
    ) -> dict:
        """The yellow pages: companies with their best learned format.

        ``confidence`` is the Beta posterior for the winning pattern, so a
        company only reads as sure once Treg has confirmed the format.
        """
        where = []
        params: list[object] = []
        if q.strip():
            like = f"%{_escape_like(q.strip())}%"
            where.append("(co.name LIKE ? ESCAPE '\\' OR co.domain LIKE ? ESCAPE '\\')")
            params.extend([like, like])
        clause = f"WHERE {' AND '.join(where)}" if where else ""
        with connection() as conn:
            total = int(
                conn.execute(
                    f"SELECT COUNT(*) AS n FROM companies co {clause}", params
                ).fetchone()["n"]
            )
            rows = conn.execute(
                f"""
                SELECT co.id, co.name, co.domain, co.is_catch_all,
                       (SELECT COUNT(*) FROM contacts c
                         WHERE c.company_id = co.id AND c.merged_into IS NULL) AS seen
                FROM companies co
                {clause}
                ORDER BY co.name COLLATE NOCASE, co.id
                LIMIT ? OFFSET ?
                """,
                params + [limit, offset],
            ).fetchall()
            items = []
            for row in rows:
                domain = row["domain"]
                pattern: str | None = None
                confidence: float | None = None
                if domain:
                    stats = patterns.pattern_stats(conn, domain)
                    if stats:
                        best = min(
                            stats,
                            key=lambda name: (
                                -stats[name]["posterior"],
                                -stats[name]["hits"],
                                name,
                            ),
                        )
                        pattern = best
                        confidence = round(float(stats[best]["posterior"]), 4)
                items.append(
                    {
                        "id": int(row["id"]),
                        "name": row["name"],
                        "domain": domain,
                        "pattern": pattern,
                        "confidence": confidence,
                        "seen": int(row["seen"]),
                        "is_catch_all": bool(row["is_catch_all"]),
                    }
                )
        return {"items": items, "total": total}

    @app.get("/api/contacts/{contact_id}")
    def api_contact(contact_id: int) -> dict:
        with connection() as conn:
            row = conn.execute(
                """
                SELECT c.*, co.name AS company, co.domain AS company_domain
                FROM contacts c JOIN companies co ON co.id = c.company_id
                WHERE c.id = ?
                """,
                (contact_id,),
            ).fetchone()
            if row is None:
                raise HTTPException(
                    status_code=404, detail=f"contact {contact_id} not found"
                )
            lookups = conn.execute(
                f"""
                SELECT {", ".join(_LOOKUP_COLUMNS)}
                FROM lookups WHERE contact_id = ? ORDER BY id DESC
                """,
                (contact_id,),
            ).fetchall()
        return {
            "contact": _contact_detail(row),
            "lookups": [_lookup_item(lookup) for lookup in lookups],
        }

    @app.get("/api/report")
    def api_report(since: str | None = None) -> dict:
        with connection() as conn:
            try:
                built = report_mod.build_report(conn, since=since)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
        return built.to_json()

    @app.post("/api/import")
    async def api_import(file: UploadFile = File(...)) -> dict:
        raw = await file.read()
        stream = io.StringIO(raw.decode("utf-8-sig", errors="replace"))
        with connection() as conn:
            try:
                return csv_io.import_contacts(conn, stream)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/export")
    def api_export() -> Response:
        buffer = io.StringIO()
        with connection() as conn:
            csv_io.export_contacts(conn, buffer)
        return Response(
            content=buffer.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": 'attachment; filename="contacts.csv"'},
        )

    @app.get("/health")
    def health() -> dict:
        db_ok = True
        try:
            with connection() as conn:
                conn.execute("SELECT 1").fetchone()
        except Exception:
            db_ok = False

        laya = LayaClient(settings)
        try:
            reachable = bool(laya.health())
        except Exception:
            reachable = False
        finally:
            laya.close()

        return {
            "status": "ok" if db_ok else "degraded",
            "db": db_ok,
            "laya": {
                "mode": settings.laya_mode,
                "enabled": settings.laya_mode != "off",
                "reachable": reachable,
            },
            "treg": {"mode": settings.treg_mode},
        }

    if WEB_DIR.is_dir():
        app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")

    return app


app = create_app()
