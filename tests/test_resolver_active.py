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


def _settings(tmp_path, *, laya_mode: str = "off", **overrides) -> Settings:
    values = dict(
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
    values.update(overrides)
    return Settings(**values)


@pytest.fixture()
def settings(tmp_path, monkeypatch):
    built = _settings(tmp_path, laya_mode="off")
    monkeypatch.setattr(resolver, "get_settings", lambda: built)
    return built


@pytest.fixture()
def client(settings):
    return TregMockClient(path=FIXTURE, settings=settings)


def _laya_handler(
    *,
    rank_index: int = 0,
    route_answer: str = "A",
    identity_answer: str = "A",
    prob: float = 0.9,
):
    """Mock Laya: pick a criteria key per question with a lopsided distribution."""

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        answers = {}
        for qid, question in payload["questions"].items():
            keys = list(question["criteria"].keys())
            chosen = keys[0]
            if qid == "rank" and rank_index < len(keys):
                chosen = keys[rank_index]
            elif qid == "route" and route_answer in keys:
                chosen = route_answer
            elif qid == "identity" and identity_answer in keys:
                chosen = identity_answer
            probs = {
                key: (prob if key == chosen else (1.0 - prob) / max(1, len(keys) - 1))
                for key in keys
            }
            answers[qid] = {
                "type": "choice",
                "choice": chosen,
                "probabilities": probs,
                "confidence": 0.2,
                "answer_confidence": probs[chosen],
            }
        return httpx.Response(
            200,
            json={
                "model": "laya-rl-agent",
                "answers": answers,
                "routing": {"model": "english"},
            },
        )

    return handler


def _seed_calibration(
    conn,
    *,
    question: str,
    n_options: int,
    n_samples: int,
    accuracy: float,
    rules_acc: float,
    temperature: float = 1.0,
) -> None:
    conn.execute(
        """
        INSERT INTO laya_calibration
            (question, n_options, temperature, n_samples, accuracy, rules_acc)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(question, n_options) DO UPDATE SET
            temperature = excluded.temperature,
            n_samples = excluded.n_samples,
            accuracy = excluded.accuracy,
            rules_acc = excluded.rules_acc
        """,
        (question, n_options, temperature, n_samples, accuracy, rules_acc),
    )
    conn.commit()


def _rows(conn, question: str | None = None):
    if question is None:
        return conn.execute("SELECT * FROM laya_decisions ORDER BY id").fetchall()
    return conn.execute(
        "SELECT * FROM laya_decisions WHERE question = ? ORDER BY id", (question,)
    ).fetchall()


def test_only_rank_activates(conn, client, settings):
    _seed_calibration(conn, question="rank", n_options=6, n_samples=60, accuracy=0.9, rules_acc=0.5)
    _seed_calibration(conn, question="route", n_options=2, n_samples=60, accuracy=0.4, rules_acc=0.5)

    settings.laya_mode = "active"
    laya = LayaClient(settings=settings)
    with respx.mock(base_url=LAYA_URL) as router:
        router.post("/v1/systemone").mock(side_effect=_laya_handler(rank_index=1))
        fetch(conn, "Casper Ghost", "Ghost Co", client=client, laya=laya)
        fetch(conn, "Jane Doe", "Acme Inc", client=client, laya=laya)

    rank_rows = _rows(conn, "rank")
    assert len(rank_rows) == 1
    assert rank_rows[0]["applied"] == 1

    route_rows = _rows(conn, "route")
    assert route_rows
    assert all(row["applied"] == 0 for row in route_rows)


def test_rank_blend_changes_top_candidate(conn, client, settings):
    _seed_calibration(conn, question="rank", n_options=6, n_samples=60, accuracy=0.9, rules_acc=0.5)

    settings.laya_mode = "active"
    laya = LayaClient(settings=settings)
    with respx.mock(base_url=LAYA_URL) as router:
        router.post("/v1/systemone").mock(side_effect=_laya_handler(rank_index=1))
        result = fetch(conn, "Casper Ghost", "Ghost Co", client=client, laya=laya)

    assert result.route == "generate"
    assert result.high_pattern_email == "cghost@ghost.co"
    assert result.email == "cghost@ghost.co"
    assert result.alternates[0] == "casper.ghost@ghost.co"

    candidates = conn.execute(
        "SELECT * FROM candidates WHERE lookup_id = ? ORDER BY rank",
        (result.lookup_id,),
    ).fetchall()
    by_email = {row["email"]: row for row in candidates}
    winner = by_email["cghost@ghost.co"]
    assert winner["rank"] == 1
    assert winner["laya_prob"] == pytest.approx(0.9)
    expected = (
        (1.0 - settings.laya_weight) * winner["rules_score"]
        + settings.laya_weight * 0.9
    )
    assert winner["final_score"] == pytest.approx(expected)
    assert winner["outcome"] == "invalid"  # ghost.co verifies everything invalid

    runner_up = by_email["casper.ghost@ghost.co"]
    assert runner_up["rank"] == 2
    assert runner_up["laya_prob"] == pytest.approx(0.02)
    assert runner_up["final_score"] < winner["final_score"]

    rank_row = _rows(conn, "rank")[0]
    assert rank_row["applied"] == 1
    assert rank_row["rules_answer"] == "c1"


def test_under_50_samples_activates_nothing(tmp_path, settings, client):
    conn_shadow = db.migrate(tmp_path / "shadow.db")
    conn_active = db.migrate(tmp_path / "active.db")
    try:
        for connection in (conn_shadow, conn_active):
            _seed_calibration(
                connection, question="rank", n_options=6, n_samples=49, accuracy=0.9, rules_acc=0.5
            )
        sequence = [("Casper Ghost", "Ghost Co"), ("Jane Doe", "Acme Inc")]
        handler = _laya_handler(rank_index=1)

        settings.laya_mode = "shadow"
        laya = LayaClient(settings=settings)
        with respx.mock(base_url=LAYA_URL) as router:
            router.post("/v1/systemone").mock(side_effect=handler)
            shadow_results = [
                to_json(fetch(conn_shadow, name, company, client=client, laya=laya))
                for name, company in sequence
            ]

        settings.laya_mode = "active"
        laya = LayaClient(settings=settings)
        with respx.mock(base_url=LAYA_URL) as router:
            router.post("/v1/systemone").mock(side_effect=handler)
            active_results = [
                to_json(fetch(conn_active, name, company, client=client, laya=laya))
                for name, company in sequence
            ]

        assert active_results == shadow_results
        assert all(row["applied"] == 0 for row in _rows(conn_active))
    finally:
        conn_shadow.close()
        conn_active.close()


def test_identity_active_merges_gray_zone(conn, client, settings):
    first = fetch(conn, "Jane Doe", "Acme Inc", client=client)
    _seed_calibration(conn, question="identity", n_options=2, n_samples=60, accuracy=0.9, rules_acc=0.5)

    settings.laya_mode = "active"
    laya = LayaClient(settings=settings)
    with respx.mock(base_url=LAYA_URL) as router:
        router.post("/v1/systemone").mock(side_effect=_laya_handler(identity_answer="A"))
        second = fetch(conn, "Jane Do", "Acme Inc", client=client, laya=laya)

    assert second.contact_id == first.contact_id
    assert second.seen_count == 2
    assert second.identity_method == "laya"
    assert second.route == "cache_hit"
    assert second.email == "jane.doe@acme.com"
    assert conn.execute("SELECT COUNT(*) AS n FROM contacts").fetchone()["n"] == 1

    identity_rows = _rows(conn, "identity")
    assert len(identity_rows) == 1
    assert identity_rows[0]["applied"] == 1
    assert identity_rows[0]["answer"] == "A"
    assert identity_rows[0]["truth"] == "valid"


def test_identity_active_below_threshold_stays_new(conn, client, settings):
    first = fetch(conn, "Jane Doe", "Acme Inc", client=client)
    _seed_calibration(conn, question="identity", n_options=2, n_samples=60, accuracy=0.9, rules_acc=0.5)

    settings.laya_mode = "active"
    laya = LayaClient(settings=settings)
    with respx.mock(base_url=LAYA_URL) as router:
        # A at 0.70 calibrated < 0.80: rules still create a new contact.
        router.post("/v1/systemone").mock(side_effect=_laya_handler(identity_answer="A", prob=0.7))
        second = fetch(conn, "Jane Do", "Acme Inc", client=client, laya=laya)

    assert second.identity_method == "new"
    assert second.contact_id != first.contact_id
    assert conn.execute("SELECT COUNT(*) AS n FROM contacts").fetchone()["n"] == 2
    identity_rows = _rows(conn, "identity")
    assert len(identity_rows) == 1
    assert identity_rows[0]["applied"] == 0


def test_route_active_a_forces_verify_below_thresholds(conn, client, settings):
    _seed_calibration(conn, question="route", n_options=2, n_samples=60, accuracy=0.9, rules_acc=0.5)

    settings.laya_mode = "active"
    laya = LayaClient(settings=settings)
    with respx.mock(base_url=LAYA_URL) as router:
        router.post("/v1/systemone").mock(side_effect=_laya_handler(route_answer="A"))
        fetch(conn, "Jane Doe", "Acme Inc", client=client, laya=laya)
        result = fetch(conn, "John Smith", "Acme", client=client, laya=laya)

    assert result.route == "pattern_verify"
    assert result.email == "john.smith@acme.com"
    assert result.treg_calls == {"find": 0, "verify": 1}

    route_rows = _rows(conn, "route")
    assert route_rows[-1]["applied"] == 1
    assert route_rows[-1]["rules_answer"] == "B"


def test_route_active_b_skips_verify(conn, tmp_path, monkeypatch):
    built = _settings(
        tmp_path,
        laya_mode="off",
        verify_min_hits=1,
        verify_min_posterior=0.50,
    )
    monkeypatch.setattr(resolver, "get_settings", lambda: built)
    treg = TregMockClient(path=FIXTURE, settings=built)
    _seed_calibration(conn, question="route", n_options=2, n_samples=60, accuracy=0.9, rules_acc=0.5)

    built.laya_mode = "active"
    laya = LayaClient(settings=built)
    with respx.mock(base_url=LAYA_URL) as router:
        router.post("/v1/systemone").mock(side_effect=_laya_handler(route_answer="B"))
        fetch(conn, "Jane Doe", "Acme Inc", client=treg, laya=laya)
        result = fetch(conn, "John Smith", "Acme", client=treg, laya=laya)

    assert result.route == "treg_find"
    assert result.email == "john.smith@acme.com"
    assert result.treg_calls == {"find": 1, "verify": 0}

    route_rows = _rows(conn, "route")
    assert route_rows[-1]["applied"] == 1
    assert route_rows[-1]["rules_answer"] == "A"


def test_reversibility_shadow_matches_off(tmp_path, settings, client):
    conn_off = db.migrate(tmp_path / "off.db")
    conn_shadow = db.migrate(tmp_path / "shadow.db")
    conn_active = db.migrate(tmp_path / "active.db")
    try:
        for connection in (conn_shadow, conn_active):
            _seed_calibration(
                connection, question="rank", n_options=6, n_samples=60, accuracy=0.9, rules_acc=0.5
            )
        sequence = [("Casper Ghost", "Ghost Co"), ("Jane Doe", "Acme Inc")]
        handler = _laya_handler(rank_index=1)

        settings.laya_mode = "off"
        off_results = [
            to_json(fetch(conn_off, name, company, client=client))
            for name, company in sequence
        ]

        settings.laya_mode = "shadow"
        laya = LayaClient(settings=settings)
        with respx.mock(base_url=LAYA_URL) as router:
            router.post("/v1/systemone").mock(side_effect=handler)
            shadow_results = [
                to_json(fetch(conn_shadow, name, company, client=client, laya=laya))
                for name, company in sequence
            ]

        settings.laya_mode = "active"
        laya = LayaClient(settings=settings)
        with respx.mock(base_url=LAYA_URL) as router:
            router.post("/v1/systemone").mock(side_effect=handler)
            active_results = [
                to_json(fetch(conn_active, name, company, client=client, laya=laya))
                for name, company in sequence
            ]

        assert shadow_results == off_results
        assert active_results != off_results
    finally:
        conn_off.close()
        conn_shadow.close()
        conn_active.close()
