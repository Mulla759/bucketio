from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx

from bucketio import treg
from bucketio.config import Settings
from bucketio.treg import (
    NotConfigured,
    TregCliClient,
    TregHttpClient,
    TregMockClient,
    make_client,
    map_status,
)

FIXTURE = Path(__file__).parent / "fixtures" / "treg_mock.json"


def _settings(**overrides) -> Settings:
    values = {
        "_env_file": None,
        "treg_mode": "http",
        "treg_base_url": "https://treg.example",
        "treg_token": "test-token",
        "treg_org": "test-org",
        "treg_timeout_s": 5.0,
        "treg_find_cost": 0.004834,
        "treg_verify_cost": 0.0015,
    }
    values.update(overrides)
    return Settings(**values)


def _mock(**overrides) -> TregMockClient:
    return TregMockClient(path=FIXTURE, settings=_settings(**overrides))


@pytest.mark.parametrize(
    ("word", "expected"),
    [
        ("valid", "valid"),
        ("VALID", "valid"),
        (" invalid ", "invalid"),
        ("catch_all", "catch_all"),
        ("accept_all", "catch_all"),
        ("accept-all", "catch_all"),
        ("is_accept_all", "catch_all"),
        ("risky", "risky"),
        ("not_found", "not_found"),
        ("not-found", "not_found"),
        ("miss", "not_found"),
        ("unknown", "unknown"),
        (None, "unknown"),
        ("", "unknown"),
        ("something_new", "unknown"),
    ],
)
def test_map_status(word, expected):
    assert map_status(word) == expected


def test_mock_find_valid_and_cost():
    result = _mock().find("Jane Doe", "Acme Inc")
    assert result.status == "valid"
    assert result.email == "jane.doe@acme.com"
    assert result.domain == "acme.com"
    assert result.kind == "find"
    assert result.cost_units == pytest.approx(0.004834)
    assert result.raw["status"] == "valid"
    assert result.raw["domain"] == "acme.com"
    json.dumps(result.raw)


def test_mock_find_catch_all():
    result = _mock().find("Peter Gibbons", "Initech")
    assert result.status == "catch_all"
    assert result.email == "peter.gibbons@initech.com"
    assert result.cost_units == pytest.approx(0.004834)


def test_mock_find_not_found_keeps_domain_for_ghost():
    result = _mock().find("Casper Ghost", "Ghost Co")
    assert result.status == "not_found"
    assert result.email is None
    assert result.domain == "ghost.co"
    assert result.cost_units == 0.0


def test_mock_find_unknown_company_is_free():
    result = _mock().find("Zed Zulu", "Hoax LLC")
    assert result.status == "not_found"
    assert result.domain is None
    assert result.cost_units == 0.0


def test_mock_find_unknown_person_keeps_domain():
    result = _mock().find("Nobody Here", "Acme")
    assert result.status == "not_found"
    assert result.domain == "acme.com"
    assert result.cost_units == 0.0


def test_mock_find_non_latin_name():
    result = _mock().find("Анна Иванова", "Acme Inc")
    assert result.status == "valid"
    assert result.email == "anna.ivanova@acme.com"


def test_mock_verify_valid_invalid_unknown_catch_all():
    client = _mock()
    valid = client.verify("jane.doe@acme.com")
    assert (valid.status, valid.domain, valid.cost_units) == (
        "valid",
        "acme.com",
        pytest.approx(0.0015),
    )
    invalid = client.verify("nope@acme.com")
    assert invalid.status == "invalid"
    unknown = client.verify("a@nowhere.example")
    assert unknown.status == "unknown"
    assert unknown.cost_units == 0.0
    catch_all = client.verify("anyone@initech.com")
    assert catch_all.status == "catch_all"
    assert catch_all.cost_units == pytest.approx(0.0015)


@respx.mock
def test_http_find_headers_body_and_parse():
    route = respx.post(
        "https://treg.example/call/treg.people.email.find"
    ).mock(
        return_value=httpx.Response(
            200,
            headers={"X-Treg-Cost-Micro": "4834"},
            json={
                "output": {"email": "jane.doe@acme.com", "status": "valid"},
                "raw": {
                    "domain": "acme.com",
                    "website_url": "https://www.acme.com/about",
                    "company": {"domain": "acme.com"},
                },
                "_treg": {"endpoint": "treg.people.email.find"},
            },
        )
    )
    client = TregHttpClient(_settings())
    result = client.find("Jane Doe", "Acme Inc")

    request = route.calls[0].request
    assert request.headers["X-Treg-Token"] == "test-token"
    assert request.headers["X-Treg-Org"] == "test-org"
    assert json.loads(request.content) == {
        "domain": "Acme Inc",
        "full_name": "Jane Doe",
    }

    assert result.status == "valid"
    assert result.email == "jane.doe@acme.com"
    assert result.domain == "acme.com"
    assert result.kind == "find"
    assert result.cost_units == pytest.approx(0.004834)


@respx.mock
def test_http_verify_boolean_status_and_cost_header():
    route = respx.post(
        "https://treg.example/call/treg.people.email.verify"
    ).mock(
        return_value=httpx.Response(
            200,
            headers={"X-Treg-Cost-Micro": "1500"},
            json={"output": {"verified": True}, "raw": {"email": "jane.doe@acme.com"}},
        )
    )
    client = TregHttpClient(_settings())
    result = client.verify("jane.doe@acme.com")

    assert json.loads(route.calls[0].request.content) == {"email": "jane.doe@acme.com"}
    assert result.status == "valid"
    assert result.email == "jane.doe@acme.com"
    assert result.domain == "acme.com"
    assert result.kind == "verify"
    assert result.cost_units == pytest.approx(0.0015)


@respx.mock
def test_http_verify_false_verified_is_invalid_and_missing_cost_falls_back():
    respx.post("https://treg.example/call/treg.people.email.verify").mock(
        return_value=httpx.Response(200, json={"output": {"verified": False}})
    )
    client = TregHttpClient(_settings())
    result = client.verify("nope@acme.com")
    assert result.status == "invalid"
    assert result.email == "nope@acme.com"
    assert result.cost_units == pytest.approx(0.0015)


@respx.mock
def test_http_maps_accept_all_and_website_url_domain():
    respx.post("https://treg.example/call/treg.people.email.find").mock(
        return_value=httpx.Response(
            200,
            json={
                "output": {"email": "peter.gibbons@initech.com", "status": "accept_all"},
                "raw": {"website_url": "initech.com/contact"},
            },
        )
    )
    client = TregHttpClient(_settings())
    result = client.find("Peter Gibbons", "Initech")
    assert result.status == "catch_all"
    assert result.domain == "initech.com"


def test_http_requires_base_url_and_token(monkeypatch):
    monkeypatch.setattr(treg, "read_treg_cli_token", lambda: None)
    with pytest.raises(NotConfigured):
        TregHttpClient(_settings(treg_base_url=""))
    with pytest.raises(NotConfigured):
        TregHttpClient(_settings(treg_token=None))


def test_cli_requires_token(monkeypatch):
    monkeypatch.setattr(treg, "read_treg_cli_token", lambda: None)
    with pytest.raises(NotConfigured):
        TregCliClient(_settings(treg_mode="cli", treg_token=None))


def test_make_client_selects_by_mode(monkeypatch):
    assert isinstance(make_client(_settings(treg_mode="mock")), TregMockClient)
    assert isinstance(make_client(_settings(treg_mode="http")), TregHttpClient)
    monkeypatch.setattr(treg, "read_treg_cli_token", lambda: "token")
    assert isinstance(make_client(_settings(treg_mode="cli")), TregCliClient)
