from __future__ import annotations

import builtins
import json

import httpx
import respx

from bucketio.config import Settings
from bucketio.laya_client import (
    LayaClient,
    LayaQuestion,
    build_body,
    parse_response,
    q_identity,
    q_plausible,
    q_rank,
    q_route,
)

ENDPOINT = "http://laya.test/v1/systemone"
HEALTH = "http://laya.test/health"


def make_settings(**overrides) -> Settings:
    values = {
        "laya_mode": "shadow",
        "laya_transport": "http",
        "laya_url": "http://laya.test",
        "laya_api_key": "test-key",
        "laya_timeout_s": 1.5,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def route_question() -> LayaQuestion:
    return q_route(
        domain="acme.com",
        best_pattern="first.last",
        posterior=0.52,
        verified_hits=1,
        misses=0,
        patterns_seen=1,
        catch_all=False,
    )


def identity_question() -> LayaQuestion:
    return q_identity(
        existing={"name": "Robert Smith", "company": "ACME Corp", "email": "rsmith@acme.com"},
        incoming={"name": "Bob Smith", "company": "Acme Inc"},
    )


def plausible_question() -> LayaQuestion:
    return q_plausible(
        person="Jane Doe",
        company="Acme",
        treg_email="j.doe.2@acme.com",
        learned_format="first.last",
    )


def rank_question(emails: list[str] | None = None) -> LayaQuestion:
    return q_rank(
        person="Jane van der Berg",
        company="Acme",
        domain="acme.com",
        known_formats=["first.last (3 valid)"],
        similar_formats=["flast", "first.last"],
        candidate_emails=emails or ["jane.vanderberg@acme.com", "jvanderberg@acme.com"],
    )


ALL_BUILDERS = (identity_question, route_question, rank_question, plausible_question)


def test_off_mode_returns_laya_off_without_request():
    client = LayaClient(settings=make_settings(laya_mode="off"))
    with respx.mock(assert_all_called=False) as mock:
        any_route = mock.route(host="laya.test").mock(return_value=httpx.Response(200, json={}))
        assert client.enabled is False
        answer = client.ask(route_question())
        assert answer.error == "laya_off"
        assert answer.answer is None
        assert not any_route.called


def test_ask_http_happy_path_parses_answer_confidence_probs_and_routing():
    client = LayaClient(settings=make_settings())
    payload = {
        "model": "laya-rl-agent",
        "answers": {
            "route": {
                "type": "choice",
                "choice": "A",
                "probabilities": {"A": 0.91, "B": 0.09},
                "confidence": 0.63,
                "answer_confidence": 0.91,
                "action": {"act_probability": 1.0},
            }
        },
        "usage": {"input_tokens": 42, "output_tokens": 0},
        "routing": {"model": "english", "repo": "convaiinnovations/laya", "reason": "latin english"},
    }
    with respx.mock(assert_all_called=False) as mock:
        route = mock.post(ENDPOINT).mock(return_value=httpx.Response(200, json=payload))
        answer = client.ask(route_question())

    assert answer.error is None
    assert answer.question == "route"
    assert answer.answer == "A"
    assert answer.confidence == 0.91
    assert answer.probs == {"A": 0.91, "B": 0.09}
    assert answer.routed_model == "english"
    assert isinstance(answer.latency_ms, int)

    request = route.calls.last.request
    assert request.headers["authorization"] == "Bearer test-key"
    body = json.loads(request.content)
    assert set(body) == {"state", "questions"}
    assert body["state"] == route_question().state
    assert len(body["questions"]) == 1
    assert body["questions"]["route"]["type"] == "choice"
    assert body["questions"]["route"]["criteria"] == {"A": "reliable enough, verify the generated address",
                                                      "B": "not reliable, run a full search"}


def test_ask_timeout_returns_error():
    client = LayaClient(settings=make_settings())
    with respx.mock(assert_all_called=False) as mock:
        mock.post(ENDPOINT).mock(side_effect=httpx.TimeoutException("slow"))
        answer = client.ask(route_question())
    assert answer.answer is None
    assert answer.error == "timeout"


def test_ask_connect_error_returns_error():
    client = LayaClient(settings=make_settings())
    with respx.mock(assert_all_called=False) as mock:
        mock.post(ENDPOINT).mock(side_effect=httpx.ConnectError("refused"))
        answer = client.ask(route_question())
    assert answer.answer is None
    assert answer.error is not None
    assert answer.error.startswith("transport_error")


def test_ask_http_500_returns_error():
    client = LayaClient(settings=make_settings())
    with respx.mock(assert_all_called=False) as mock:
        mock.post(ENDPOINT).mock(return_value=httpx.Response(500, text="boom"))
        answer = client.ask(route_question())
    assert answer.answer is None
    assert answer.error == "http_500"


def test_ask_malformed_json_returns_error():
    client = LayaClient(settings=make_settings())
    with respx.mock(assert_all_called=False) as mock:
        mock.post(ENDPOINT).mock(return_value=httpx.Response(200, text="<html>not json</html>"))
        answer = client.ask(route_question())
    assert answer.answer is None
    assert answer.error == "malformed_json"


def test_ask_unknown_transport_returns_error(monkeypatch):
    client = LayaClient(settings=make_settings())
    monkeypatch.setattr(client.settings, "laya_transport", "carrier-pigeon")
    answer = client.ask(route_question())
    assert answer.answer is None
    assert answer.error == "unknown_transport"


def test_inprocess_import_failure_returns_error(monkeypatch):
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "laya":
            raise ImportError("laya is not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    client = LayaClient(settings=make_settings(laya_transport="inprocess"))
    answer = client.ask(route_question())
    assert answer.answer is None
    assert answer.error is not None
    assert answer.error.startswith("import_error")


def test_health_true_on_200():
    client = LayaClient(settings=make_settings())
    with respx.mock(assert_all_called=False) as mock:
        route = mock.get(HEALTH).mock(return_value=httpx.Response(200, json={"status": "ok"}))
        assert client.health() is True
        assert route.calls.last.request.headers["authorization"] == "Bearer test-key"


def test_health_false_on_503():
    client = LayaClient(settings=make_settings())
    with respx.mock(assert_all_called=False) as mock:
        mock.get(HEALTH).mock(return_value=httpx.Response(503, text="down"))
        assert client.health() is False


def test_health_false_when_disabled_without_request():
    client = LayaClient(settings=make_settings(laya_mode="off"))
    with respx.mock(assert_all_called=False) as mock:
        any_route = mock.route(host="laya.test").mock(return_value=httpx.Response(200))
        assert client.health() is False
        assert not any_route.called


def test_binary_builders_have_exactly_two_criteria():
    for question in (identity_question(), route_question(), plausible_question()):
        assert set(question.criteria) == {"A", "B"}


def test_q_rank_truncates_to_twelve_and_keeps_order():
    emails = [f"candidate{index}@acme.com" for index in range(15)]
    question = rank_question(emails)
    assert list(question.criteria) == [f"c{i}" for i in range(1, 13)]
    assert list(question.criteria.values()) == emails[:12]


def test_q_rank_keeps_all_candidates_under_cap():
    emails = ["a@acme.com", "b@acme.com", "c@acme.com"]
    question = rank_question(emails)
    assert question.criteria == {"c1": "a@acme.com", "c2": "b@acme.com", "c3": "c@acme.com"}


def test_no_builder_emits_noul():
    for builder in ALL_BUILDERS:
        body = build_body(builder())
        for payload in body["questions"].values():
            assert payload["type"] == "choice"
            assert payload["type"] != "noul"
        assert "noul" not in json.dumps(body)


def test_build_body_has_exactly_one_question():
    for builder in ALL_BUILDERS:
        question = builder()
        body = build_body(question)
        assert list(body["questions"]) == [question.name]
        assert list(body) == ["state", "questions"]


def test_body_serialization_is_deterministic():
    question = rank_question(["josé.vanderberg@acme.com", "jvanderberg@acme.com", "jane@acme.com"])
    first = json.dumps(build_body(question))
    second = json.dumps(build_body(question))
    assert first == second
    assert first.encode("utf-8") == second.encode("utf-8")


def test_parse_response_prefers_key_present_in_criteria_and_ignores_unknown():
    question = route_question()
    payload = {
        "answers": {
            "route": {
                "choice": "Z",
                "label": "A",
                "confidence": 0.8,
                "bogus": "ignored",
            }
        }
    }
    answer = parse_response(question, payload)
    assert answer.answer == "A"
    assert answer.confidence == 0.8
    assert answer.error is None


def test_parse_response_accepts_answer_alias():
    payload = {"answers": {"route": {"answer": "B"}}}
    answer = parse_response(route_question(), payload)
    assert answer.answer == "B"
    assert answer.error is None


def test_parse_response_handles_results_questions_nesting():
    payload = {
        "results": {
            "questions": {
                "route": {"choice": "A", "probabilities": {"A": 0.7, "B": 0.3}}
            }
        }
    }
    answer = parse_response(route_question(), payload)
    assert answer.answer == "A"
    assert answer.probs == {"A": 0.7, "B": 0.3}


def test_parse_response_prefers_answer_confidence_and_clamps():
    question = route_question()
    payload = {"answers": {"route": {"choice": "A", "answer_confidence": 0.93, "confidence": 0.44}}}
    answer = parse_response(question, payload)
    assert answer.confidence == 0.93
    high = parse_response(question, {"answers": {"route": {"choice": "A", "confidence": 1.4}}})
    assert high.confidence == 1.0
    low = parse_response(question, {"answers": {"route": {"choice": "A", "confidence": -0.2}}})
    assert low.confidence == 0.0


def test_parse_response_reads_routing_model_and_latency():
    payload = {
        "answers": {"route": {"choice": "A"}},
        "routing": {"model": "multilingual", "reason": "non-latin script"},
        "latency_ms": 33,
    }
    answer = parse_response(route_question(), payload)
    assert answer.routed_model == "multilingual"
    assert answer.latency_ms == 33


def test_parse_response_missing_answer_sets_error():
    payload = {"answers": {"route": {"probabilities": {"A": 0.5, "B": 0.5}}}}
    answer = parse_response(route_question(), payload)
    assert answer.answer is None
    assert answer.error == "no_answer"


def test_parse_response_single_answer_container_without_name():
    payload = {"answers": {"choice": "B"}}
    answer = parse_response(route_question(), payload)
    assert answer.answer == "B"
    assert answer.error is None
