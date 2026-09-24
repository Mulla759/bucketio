from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from bucketio import config, resolver
from bucketio.api import create_app
from bucketio.config import Settings

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

CONTACT_ITEM_KEYS = {
    "id",
    "name",
    "full_name",
    "company",
    "email",
    "high_pattern_email",
    "verification_status",
    "confidence",
    "seen_count",
    "last_verified_at",
    "route",
}


@pytest.fixture()
def settings(tmp_path, monkeypatch):
    built = Settings(
        _env_file=None,
        db_path=tmp_path / "api.db",
        treg_mode="mock",
        laya_mode="off",
        laya_url="http://127.0.0.1:1",
        treg_find_cost=0.004834,
        treg_verify_cost=0.0015,
    )
    monkeypatch.setattr(config, "get_settings", lambda: built)
    monkeypatch.setattr(resolver, "get_settings", lambda: built)
    return built


@pytest.fixture()
def client(settings):
    with TestClient(create_app(settings)) as test_client:
        yield test_client


def _fetch(client, name="Jane Doe", company="Acme Inc", **extra):
    payload = {"name": name, "company": company}
    payload.update(extra)
    return client.post("/api/fetch", json=payload)


def test_fetch_returns_prd_json(client):
    response = _fetch(client)

    assert response.status_code == 200
    body = response.json()
    assert set(body) == PRD_KEYS
    assert body["name"] == "Jane Doe"
    assert body["company"] == "Acme Inc"
    assert body["email"] == "jane.doe@acme.com"
    assert body["verification_status"] == "valid"
    assert body["route"] == "treg_find"
    assert body["treg_calls"] == {"find": 1, "verify": 0}


def test_fetch_422_on_missing_or_blank_fields(client):
    assert client.post("/api/fetch", json={"name": "Jane Doe"}).status_code == 422
    assert client.post("/api/fetch", json={"company": "Acme Inc"}).status_code == 422
    assert client.post("/api/fetch", json={}).status_code == 422
    assert _fetch(client, name="   ").status_code == 422


def test_fetch_force_bypasses_cache(client):
    first = _fetch(client).json()
    second = _fetch(client).json()
    forced = _fetch(client, force=True).json()

    assert first["route"] == "treg_find"
    assert second["route"] == "cache_hit"
    assert forced["route"] != "cache_hit"
    assert forced["seen_count"] == 3


def test_contacts_list_search_filter_and_paging(client):
    _fetch(client, "Jane Doe", "Acme Inc")
    _fetch(client, "John Smith", "Acme Inc")

    response = client.get("/api/contacts")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert len(body["items"]) == 2
    assert set(body["items"][0]) == CONTACT_ITEM_KEYS
    assert {item["company"] for item in body["items"]} == {"Acme Inc"}
    assert all(item["route"] == "treg_find" for item in body["items"])

    search = client.get("/api/contacts", params={"q": "jane"}).json()
    assert search["total"] == 1
    assert search["items"][0]["full_name"] == "Jane Doe"

    by_email = client.get("/api/contacts", params={"q": "john.smith@"}).json()
    assert by_email["total"] == 1

    by_company = client.get("/api/contacts", params={"q": "acme"}).json()
    assert by_company["total"] == 2

    status = client.get("/api/contacts", params={"status": "valid"}).json()
    assert status["total"] == 2
    assert client.get("/api/contacts", params={"status": "invalid"}).json()["total"] == 0

    paged = client.get("/api/contacts", params={"limit": 1, "offset": 1}).json()
    assert paged["total"] == 2
    assert len(paged["items"]) == 1


def test_contacts_list_tolerates_like_wildcards(client):
    _fetch(client, "Jane Doe", "Acme Inc")

    assert client.get("/api/contacts", params={"q": "%"}).json()["total"] == 0
    assert client.get("/api/contacts", params={"q": "_"}).json()["total"] == 0


def test_contact_detail_and_404(client):
    contact_id = _fetch(client).json()["contact_id"]

    response = client.get(f"/api/contacts/{contact_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["contact"]["id"] == contact_id
    assert body["contact"]["full_name"] == "Jane Doe"
    assert body["contact"]["company"] == "Acme Inc"
    assert body["contact"]["domain"] == "acme.com"
    assert len(body["lookups"]) == 1

    lookup = body["lookups"][0]
    for key in (
        "route",
        "result_email",
        "result_status",
        "cost_usd",
        "est_saved_usd",
        "created_at",
    ):
        assert key in lookup
    assert lookup["route"] == "treg_find"
    assert lookup["result_email"] == "jane.doe@acme.com"

    assert client.get("/api/contacts/999999").status_code == 404


def test_contact_detail_lookups_newest_first(client):
    contact_id = _fetch(client).json()["contact_id"]
    _fetch(client)

    lookups = client.get(f"/api/contacts/{contact_id}").json()["lookups"]

    assert [lookup["route"] for lookup in lookups] == ["cache_hit", "treg_find"]


def test_report_endpoint(client):
    _fetch(client)

    response = client.get("/api/report")
    assert response.status_code == 200
    body = response.json()
    assert body["fetches"] == 1
    assert body["routes"] == {"treg_find": 1}
    assert body["treg"] == {
        "find_calls": 1,
        "verify_calls": 0,
        "cost_usd": pytest.approx(0.004834),
    }
    assert body["contacts"] == 1
    assert body["laya"] == {"agreement": None, "samples": 0}

    assert client.get("/api/report", params={"since": "7d"}).status_code == 200
    assert client.get("/api/report", params={"since": "nonsense"}).status_code == 400


def test_import_and_export_round_trip(client):
    csv_bytes = (
        "Name,Company,Email\n"
        "Jane Doe,Acme Inc,jane.doe@acme.com\n"
        "John Smith,Acme Inc,\n"
    ).encode("utf-8")

    imported = client.post(
        "/api/import",
        files={"file": ("contacts.csv", csv_bytes, "text/csv")},
    )
    assert imported.status_code == 200
    assert imported.json() == {"rows": 2, "created": 2, "updated": 0, "errors": []}

    exported = client.get("/api/export")
    assert exported.status_code == 200
    assert exported.headers["content-type"].startswith("text/csv")
    assert "attachment" in exported.headers["content-disposition"]
    text = exported.text
    assert text.splitlines()[0].startswith("Name,Company,Email")
    assert "jane.doe@acme.com" in text

    again = client.post(
        "/api/import",
        files={"file": ("contacts.csv", text.encode("utf-8"), "text/csv")},
    )
    assert again.json()["updated"] == 2
    assert again.json()["created"] == 0


def test_import_without_required_header_is_400(client):
    response = client.post(
        "/api/import",
        files={"file": ("bad.csv", b"Name,Email\nJane,jane@acme.com\n", "text/csv")},
    )
    assert response.status_code == 400


def test_health_ok_with_laya_unreachable(settings, client):
    settings.laya_mode = "shadow"
    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["db"] is True
    assert body["laya"]["mode"] == "shadow"
    assert body["laya"]["enabled"] is True
    assert body["laya"]["reachable"] is False
    assert body["treg"]["mode"] == "mock"


def test_health_with_laya_off(client):
    body = client.get("/health").json()

    assert body["laya"] == {"mode": "off", "enabled": False, "reachable": False}


def test_static_index_and_app_js(client):
    index = client.get("/")
    assert index.status_code == 200
    assert "text/html" in index.headers["content-type"]
    assert "BucketIO" in index.text

    script = client.get("/app.js")
    assert script.status_code == 200
    assert "javascript" in script.headers["content-type"]
    assert "use strict" in script.text

    style = client.get("/style.css")
    assert style.status_code == 200
    assert "css" in style.headers["content-type"]
