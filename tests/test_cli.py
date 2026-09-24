from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from bucketio import config, resolver
from bucketio.cli import app
from bucketio.config import Settings

runner = CliRunner()

PRD_KEYS = {
    "contact_id",
    "name",
    "company",
    "domain",
    "email",
    "verification_status",
    "high_pattern_email",
    "alternates",
    "confidence",
    "route",
    "treg_calls",
    "seen_count",
    "est_cost_saved",
}


@pytest.fixture()
def settings(tmp_path, monkeypatch):
    built = Settings(
        _env_file=None,
        db_path=tmp_path / "cli.db",
        treg_mode="mock",
        laya_mode="off",
        laya_url="http://127.0.0.1:1",
        treg_find_cost=0.004834,
        treg_verify_cost=0.0015,
    )
    monkeypatch.setattr(config, "get_settings", lambda: built)
    monkeypatch.setattr(resolver, "get_settings", lambda: built)
    return built


def test_help_lists_commands(settings):
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    for command in ("init", "fetch", "import", "export", "report", "serve", "lreg", "version"):
        assert command in result.output


def test_version(settings):
    result = runner.invoke(app, ["version"])

    assert result.exit_code == 0
    assert result.output.strip() == "0.1.0"


def test_init_creates_tmp_db(settings):
    result = runner.invoke(app, ["init"])

    assert result.exit_code == 0
    assert str(settings.db_path) in result.output
    assert "Tables: 11" in result.output
    assert Path(settings.db_path).exists()


def test_fetch_json_matches_prd_keys(settings):
    result = runner.invoke(app, ["fetch", "Jane Doe", "Acme Inc", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert set(payload) == PRD_KEYS
    assert payload["email"] == "jane.doe@acme.com"
    assert payload["treg_calls"] == {"find": 1, "verify": 0}
    assert payload["verification_status"] == "valid"


def test_fetch_human_line_and_cache_hit(settings):
    runner.invoke(app, ["fetch", "Jane Doe", "Acme Inc"])
    result = runner.invoke(app, ["fetch", "Jane Doe", "Acme Inc"])

    assert result.exit_code == 0
    assert "jane.doe@acme.com" in result.output
    assert "route=cache_hit" in result.output
    assert "seen=2" in result.output


def test_fetch_requires_arguments(settings):
    result = runner.invoke(app, ["fetch"])

    assert result.exit_code != 0


def test_import_export_round_trip(settings, tmp_path):
    source = tmp_path / "in.csv"
    source.write_text(
        "Name,Company,Email\nJane Doe,Acme Inc,jane.doe@acme.com\n",
        encoding="utf-8",
    )

    imported = runner.invoke(app, ["import", str(source)])
    assert imported.exit_code == 0
    assert "1 created" in imported.output
    assert "0 error(s)" in imported.output

    exported_path = tmp_path / "out.csv"
    exported = runner.invoke(app, ["export", str(exported_path)])
    assert exported.exit_code == 0
    assert "Exported 1 contact(s)" in exported.output

    rows = list(csv.reader(exported_path.read_text(encoding="utf-8").splitlines()))
    assert rows[0][0] == "Name"
    assert rows[1][:3] == ["Jane Doe", "Acme Inc", "jane.doe@acme.com"]

    reimported = runner.invoke(app, ["import", str(exported_path)])
    assert reimported.exit_code == 0
    assert "0 created, 1 updated" in reimported.output


def test_import_reports_bad_rows(settings, tmp_path):
    source = tmp_path / "bad.csv"
    source.write_text("Name,Company\n,Acme Inc\n", encoding="utf-8")

    result = runner.invoke(app, ["import", str(source)])

    assert result.exit_code == 0
    assert "1 error(s)" in result.output
    assert "row 2" in result.output


def test_report_human_and_json(settings):
    runner.invoke(app, ["fetch", "Jane Doe", "Acme Inc"])

    human = runner.invoke(app, ["report"])
    assert human.exit_code == 0
    assert "Fetches:     1" in human.output
    assert "find=1 verify=0" in human.output
    assert "Contacts:    1" in human.output

    as_json = runner.invoke(app, ["report", "--json"])
    assert as_json.exit_code == 0
    payload = json.loads(as_json.output)
    assert payload["fetches"] == 1
    assert payload["routes"] == {"treg_find": 1}
    assert payload["treg"]["find_calls"] == 1
    assert payload["contacts"] == 1
    assert payload["laya"] == {"agreement": None, "samples": 0}


def test_report_since_window(settings):
    runner.invoke(app, ["fetch", "Jane Doe", "Acme Inc"])

    assert runner.invoke(app, ["report", "--since", "7d"]).exit_code == 0
    bad = runner.invoke(app, ["report", "--since", "yesterday"])
    assert bad.exit_code != 0


def test_serve_is_registered_with_defaults(settings):
    result = runner.invoke(app, ["serve", "--help"])

    assert result.exit_code == 0
    assert "127.0.0.1" in result.output
    assert "8080" in result.output


def test_lreg_status_reports_stack_without_failing(settings, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["lreg", "status"])

    assert result.exit_code == 0
    assert "not found (using defaults)" in result.output
    assert "BucketIO db:" in result.output
    assert "tables: 11" in result.output
    assert "Laya:" in result.output
    assert "health=down" in result.output
    assert "Treg:        mode=mock" in result.output
    assert "http://127.0.0.1:8080" in result.output


def test_lreg_status_reads_yaml(settings, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "lreg.yaml").write_text(
        "version: 1\n"
        "bucketio:\n"
        "  db_path: ./bucketio.db\n"
        "  web:\n"
        "    host: 0.0.0.0\n"
        "    port: 9099\n"
        "  laya_mode: shadow\n",
        encoding="utf-8",
    )

    result = runner.invoke(app, ["lreg", "status"])

    assert result.exit_code == 0
    assert "lreg.yaml:" in result.output
    assert "http://0.0.0.0:9099" in result.output
    assert "[lreg.yaml: shadow]" in result.output
