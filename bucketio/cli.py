"""BucketIO CLI: init, fetch, import/export, report, serve, lreg status.

Everything runs with ``TREG_MODE=mock`` and ``LAYA_MODE=off`` and needs no
``.env``. Settings are read through ``config.get_settings()`` so tests can
monkeypatch that one function.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer

from . import __version__, config, csv_io, db
from . import report as report_mod
from .laya_client import LayaClient
from .resolver import FetchResult, fetch as resolver_fetch, to_json
from .treg import make_client

app = typer.Typer(
    name="bucketio",
    help="Local contact store in front of Treg: cheap verifies, learned email patterns.",
    no_args_is_help=True,
    add_completion=False,
)

lreg_app = typer.Typer(
    help="Lreg stack (Laya + treg + BucketIO) status.",
    no_args_is_help=True,
)

app.add_typer(lreg_app, name="lreg")

LREG_DEFAULT_HOST = "127.0.0.1"
LREG_DEFAULT_PORT = 8080


@app.callback()
def _root() -> None:
    """BucketIO — cheap contact lookups: cache first, verify second, find last."""


@app.command()
def version() -> None:
    """Print the BucketIO version."""
    typer.echo(__version__)


def _open_db():
    """Migrate (idempotent) and return an open connection; caller closes it."""
    return db.migrate(config.get_settings().db_path)


def _human_result(result: FetchResult) -> str:
    email = result.email or "(no email)"
    return (
        f"{result.name} @ {result.company} -> {email} "
        f"[{result.verification_status}] route={result.route} "
        f"seen={result.seen_count} saved=${result.est_cost_saved:.4f}"
    )


def _print_report(built: report_mod.Report) -> None:
    routes = " ".join(f"{key}={value}" for key, value in sorted(built.routes.items()))
    typer.echo(f"Fetches:     {built.fetches}")
    typer.echo(f"Routes:      {routes or '-'}")
    typer.echo(
        f"Treg calls:  find={built.find_calls} verify={built.verify_calls} "
        f"(${built.cost_usd:.4f})"
    )
    typer.echo(f"Est. saved:  ${built.est_saved_usd:.4f}")
    typer.echo(f"Contacts:    {built.contacts}")
    if built.laya_agreement is None:
        typer.echo("Laya:        no labelled decisions yet")
    else:
        typer.echo(
            f"Laya:        {built.laya_agreement * 100:.0f}% agreement "
            f"({built.laya_samples} samples)"
        )


@app.command()
def init() -> None:
    """Create or upgrade the SQLite database and print its location."""
    settings = config.get_settings()
    conn = db.migrate(settings.db_path)
    try:
        tables = len(db.table_names(conn))
    finally:
        conn.close()
    typer.echo(f"Database: {settings.db_path}")
    typer.echo(f"Tables: {tables}")


@app.command()
def fetch(
    name: str = typer.Argument(..., help='Full name, e.g. "Jane Doe".'),
    company: str = typer.Argument(..., help='Company name, e.g. "Acme Inc".'),
    force: bool = typer.Option(False, "--force", help="Bypass the cache and re-verify."),
    as_json: bool = typer.Option(False, "--json", help="Print the full section 2.5 JSON."),
) -> None:
    """Fetch one contact and print the result."""
    settings = config.get_settings()
    conn = db.migrate(settings.db_path)
    try:
        result = resolver_fetch(
            conn, name, company, force=force, client=make_client(settings)
        )
    finally:
        conn.close()
    if as_json:
        typer.echo(json.dumps(to_json(result), indent=2, ensure_ascii=False))
    else:
        typer.echo(_human_result(result))


@app.command("import")
def import_csv(
    path: Path = typer.Argument(
        ...,
        exists=True,
        dir_okay=False,
        readable=True,
        help="CSV with a Name,Company[,Email] header.",
    ),
) -> None:
    """Import contacts from a CSV file."""
    conn = _open_db()
    try:
        result = csv_io.import_contacts(conn, path)
    finally:
        conn.close()
    typer.echo(
        f"Imported {result['rows']} row(s): {result['created']} created, "
        f"{result['updated']} updated, {len(result['errors'])} error(s)"
    )
    for error in result["errors"]:
        typer.echo(f"  row {error['row']}: {error['error']}", err=True)


@app.command("export")
def export_csv(
    path: Path = typer.Argument(..., dir_okay=False, help="Destination CSV path."),
) -> None:
    """Export all contacts to a CSV file."""
    conn = _open_db()
    try:
        count = csv_io.export_contacts(conn, path)
    finally:
        conn.close()
    typer.echo(f"Exported {count} contact(s) to {path}")


@app.command()
def report(
    since: str | None = typer.Option(
        None, "--since", help="Window: 7d, 24h or an ISO date (default: all time)."
    ),
    as_json: bool = typer.Option(False, "--json", help="Print JSON instead of the table."),
) -> None:
    """Print the cost / route / Laya report."""
    conn = _open_db()
    try:
        try:
            built = report_mod.build_report(conn, since=since)
        except ValueError as exc:
            raise typer.BadParameter(str(exc), param_hint="--since") from exc
    finally:
        conn.close()
    if as_json:
        typer.echo(json.dumps(built.to_json(), indent=2))
    else:
        _print_report(built)


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", "--host", help="Bind address."),
    port: int = typer.Option(8080, "--port", help="Bind port."),
) -> None:
    """Run the web UI and JSON API (uvicorn)."""
    import uvicorn

    uvicorn.run("bucketio.api:app", host=host, port=port)


def _parse_scalar(text: str) -> Any:
    value = text.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        value = value[1:-1]
    lowered = value.lower()
    if lowered in {"true", "yes"}:
        return True
    if lowered in {"false", "no"}:
        return False
    if lowered in {"null", "none", "~"}:
        return None
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        return value


def _read_lreg(path: Path) -> dict[str, Any]:
    """Tiny YAML-subset reader: nested mappings, scalars and # comments."""
    data: dict[str, Any] = {}
    stack: list[tuple[int, dict[str, Any]]] = [(0, data)]
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        key, separator, value = line.strip().partition(":")
        if not separator:
            continue
        while len(stack) > 1 and indent < stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]
        if value.strip() == "":
            child: dict[str, Any] = {}
            parent[key.strip()] = child
            stack.append((indent + 1, child))
        else:
            parent[key.strip()] = _parse_scalar(value)
    return data


@lreg_app.command()
def status() -> None:
    """Report the Lreg stack: config file, DB, Laya, Treg, web URL.

    Never fails on a down service: problems are printed and the exit code
    stays 0.
    """
    settings = config.get_settings()

    lreg_path = Path("lreg.yaml")
    cfg: dict[str, Any] = {}
    if lreg_path.is_file():
        typer.echo(f"lreg.yaml:   {lreg_path.resolve()}")
        try:
            cfg = _read_lreg(lreg_path)
        except Exception as exc:
            typer.echo(f"lreg.yaml:   unreadable ({exc}); using defaults", err=True)
            cfg = {}
    else:
        typer.echo("lreg.yaml:   not found (using defaults)")

    bucketio_cfg = cfg.get("bucketio")
    if not isinstance(bucketio_cfg, dict):
        bucketio_cfg = {}
    web_cfg = bucketio_cfg.get("web")
    if not isinstance(web_cfg, dict):
        web_cfg = {}
    host = web_cfg.get("host", LREG_DEFAULT_HOST)
    port = web_cfg.get("port", LREG_DEFAULT_PORT)

    conn = None
    try:
        conn = db.migrate(settings.db_path)
        tables = len(db.table_names(conn))
        db_line = f"{settings.db_path} (tables: {tables})"
    except Exception as exc:
        db_line = f"{settings.db_path} (unavailable: {exc})"
    finally:
        if conn is not None:
            conn.close()
    declared_db = bucketio_cfg.get("db_path")
    if declared_db and str(declared_db) != str(settings.db_path):
        db_line += f" [lreg.yaml: {declared_db}]"
    typer.echo(f"BucketIO db: {db_line}")

    laya = LayaClient(settings)
    try:
        laya_health = "up" if laya.health() else "down"
    except Exception:
        laya_health = "down"
    finally:
        laya.close()
    laya_line = (
        f"mode={settings.laya_mode} transport={settings.laya_transport} "
        f"health={laya_health}"
    )
    declared_mode = bucketio_cfg.get("laya_mode")
    if declared_mode and str(declared_mode) != str(settings.laya_mode):
        laya_line += f" [lreg.yaml: {declared_mode}]"
    typer.echo(f"Laya:        {laya_line}")

    typer.echo(f"Treg:        mode={settings.treg_mode}")
    typer.echo(f"Web:         http://{host}:{port}")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
