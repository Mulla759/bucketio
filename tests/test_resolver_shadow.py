from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx

from bucketio import db, resolver
from bucketio.config import Settings
from bucketio.laya_client import LayaClient
from bucketio.resolver import fetch, to_json
from bucketio.treg import TregMockClient

FIXTURE = Path(__file__).parent / "fixtures" / "treg_mock.json"
LAYA_URL = "http://127.0.0.1:8001"


def _settings(tmp_path, *, laya_mode: str = "off") -> Settings:
    return Settings(
        _env_file=None,
        db_path=tmp_path / "test.db",
        treg_mode="mock",
        laya_mode=laya_mode,
        laya_transport="http",
        laya_url=LAYA_URL,
        laya_api_key="test-key",
        laya_timeout_s=1.5,
        treg_find_cost=0.004834,
        treg_verify_cost=0.0015,
        cache_ttl_days=90,
        verify_min_posterior=0.60,
        verify_min_hits=2,
        verify_max_tries=2,
        generate_verify_top=True,
    )


@pytest.fixture()
def settings(tmp_path, monkeypatch):
    built = _settings(tmp_path, laya_mode="off")
    monkeypatch.setattr(resolver, "get_settings", lambda: built)
    return built


@pytest.fixture()
def client(settings):
    return TregMockClient(path=FIXTURE, settings=settings)


def _laya_response(request: httpx.Request) -> httpx.Response:
    payload = json.loads(request.content)
    answers = {}
    for qid, question in payload["questions"].items():
        keys = list(question["criteria"].keys())
        probs = {key: (0.85 if key == keys[0] else 0.15 / max(1, len(keys) - 1)) for key in keys}
        answers[qid] = {
            "type": "choice",
            "choice": keys[0],
            "probabilities": probs,
            "confidence": 0.2,
            "answer_confidence": probs[keys[0]],
        }
    return httpx.Response(
        200,
        json={
            "model": "laya-rl-agent",
            "answers": answers,
            "routing": {"model": "english"},
        },
    )


def _rows(conn, question: str | None = None):
    if question is None:
        return conn.execute("SELECT * FROM laya_decisions ORDER BY id").fetchall()
    return conn.execute(
        "SELECT * FROM laya_decisions WHERE question = ? ORDER BY id", (question,)
    ).fetchall()


def _comparable(result) -> dict:
    data = to_json(result)
    data["cost_usd"] = result.cost_usd
    data["identity_method"] = result.identity_method
    return data


SEQUENCE = [
    ("Jane Doe", "Acme Inc"),
    ("John Smith", "Acme"),
    ("Mary Jones", "Acme Inc"),
    ("Casper Ghost", "Ghost Co"),
]


def test_shadow_outputs_identical_to_off(tmp_path, settings, client):
    conn_off = db.migrate(tmp_path / "off.db")
    conn_shadow = db.migrate(tmp_path / "shadow.db")
    try:
        off_results = [
            _comparable(fetch(conn_off, n, c, client=client)) for n, c in SEQUENCE
        ]

        settings.laya_mode = "shadow"
        laya = LayaClient(settings=settings)
        with respx.mock(base_url=LAYA_URL) as router:
            router.post("/v1/systemone").mock(side_effect=_laya_response)
            shadow_results = [
                _comparable(fetch(conn_shadow, n, c, client=client, laya=laya))
                for n, c in SEQUENCE
            ]

        assert shadow_results == off_results
        assert len(_rows(conn_shadow)) > 0
        assert _rows(conn_off) == []
    finally:
        conn_off.close()
        conn_shadow.close()


def test_shadow_row_counts_per_question(conn, client, settings):
    settings.laya_mode = "shadow"
    laya = LayaClient(settings=settings)
    with respx.mock(base_url=LAYA_URL) as router:
        router.post("/v1/systemone").mock(side_effect=_laya_response)
        for name, company in SEQUENCE:
            fetch(conn, name, company, client=client, laya=laya)

    counts = {
        row["question"] for row in _rows(conn)
    }
    by_question = {q: len(_rows(conn, q)) for q in counts}
    # Jane/John are find hits -> Q4; Mary verifies -> Q3; Ghost generates -> Q3.
    # Q2 is asked for Jane only (verified_hits == 1 at decision time).
    assert by_question == {"plausible": 2, "rank": 2, "route": 1}
    assert all(row["applied"] == 0 for row in _rows(conn))
    assert all(row["routed_model"] == "english" for row in _rows(conn))
    assert all(row["error"] is None for row in _rows(conn))


def test_identity_question_in_gray_zone(conn, client, settings):
    fetch(conn, "Jane Doe", "Acme Inc", client=client)
    settings.laya_mode = "shadow"
    laya = LayaClient(settings=settings)
    with respx.mock(base_url=LAYA_URL) as router:
        router.post("/v1/systemone").mock(side_effect=_laya_response)
        # "Jane Do" fuzzy-matches "Jane Doe" inside 80-95 -> identity gray zone
        fetch(conn, "Jane Do", "Acme Inc", client=client, laya=laya)

    rows = _rows(conn, "identity")
    assert len(rows) == 1
    assert rows[0]["rules_answer"] == "B"
    assert rows[0]["answer"] == "A"
    assert rows[0]["confidence"] == pytest.approx(0.85)
    # truth = whether the incoming fetch landed on the existing contact's email
    assert rows[0]["truth"] in ("valid", "invalid")


def test_laya_timeout_never_breaks_a_fetch(conn, client, settings):
    settings.laya_mode = "shadow"
    laya = LayaClient(settings=settings)
    with respx.mock(base_url=LAYA_URL) as router:
        router.post("/v1/systemone").mock(side_effect=httpx.TimeoutException("slow"))
        result = fetch(conn, "Jane Doe", "Acme Inc", client=client, laya=laya)

    assert result.route == "treg_find"
    assert result.email == "jane.doe@acme.com"
    rows = _rows(conn)
    assert rows and all(row["answer"] is None for row in rows)
    assert all(row["error"] == "timeout" for row in rows)


def test_rank_truth_backfilled_from_verify(conn, client, settings):
    settings.laya_mode = "shadow"
    laya = LayaClient(settings=settings)
    with respx.mock(base_url=LAYA_URL) as router:
        router.post("/v1/systemone").mock(side_effect=_laya_response)
        fetch(conn, "Jane Doe", "Acme Inc", client=client, laya=laya)
        fetch(conn, "John Smith", "Acme", client=client, laya=laya)
        fetch(conn, "Mary Jones", "Acme Inc", client=client, laya=laya)

    rank_rows = _rows(conn, "rank")
    assert len(rank_rows) == 1
    assert rank_rows[0]["rules_answer"] == "c1"
    assert rank_rows[0]["truth"] == "c1"

    route_rows = _rows(conn, "route")
    assert route_rows and all(row["truth"] in ("valid", "invalid") for row in route_rows)


def test_off_mode_writes_nothing_and_calls_nothing(conn, client, settings):
    with respx.mock(base_url=LAYA_URL, assert_all_called=False) as router:
        route = router.post("/v1/systemone").mock(side_effect=_laya_response)
        fetch(conn, "Jane Doe", "Acme Inc", client=client)
        assert route.call_count == 0
    assert _rows(conn) == []


def test_active_mode_is_shadow_until_pass6(conn, client, settings):
    settings.laya_mode = "active"
    laya = LayaClient(settings=settings)
    with respx.mock(base_url=LAYA_URL) as router:
        router.post("/v1/systemone").mock(side_effect=_laya_response)
        result = fetch(conn, "Jane Doe", "Acme Inc", client=client, laya=laya)

    assert result.route == "treg_find"
    assert all(row["applied"] == 0 for row in _rows(conn))
    assert conn.execute(
        "SELECT laya_mode FROM lookups ORDER BY id DESC LIMIT 1"
    ).fetchone()["laya_mode"] == "active"
