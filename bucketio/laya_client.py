"""Laya client: HTTP / in-process / off transports plus the Q1-Q4 question builders.

Wire contract (laya 0.3.20) as implemented by ``laya/serve.py`` and
``laya/agent.py::_decode_answers``:

    POST {laya_url}/v1/systemone
    Authorization: Bearer {laya_api_key}
    {"state": ..., "questions": {"<name>": {"type": "choice",
     "instructions": "...", "criteria": {"A": "...", "B": "..."}}}}

    -> {"model": "laya-rl-agent",
        "answers": {"<name>": {"type": "choice", "choice": "<criteria key>",
                    "probabilities": {"A": 0.93, "B": 0.07},
                    "confidence": 0.66, "answer_confidence": 0.93,
                    "action": {"act_probability": 1.0}}},
        "usage": {"input_tokens": 123, "output_tokens": 0},
        "routing": {"model": "english", "repo": ..., "reason": ...}}

For a ``choice`` question the wire ``confidence`` is normalized entropy, while
``answer_confidence`` is max(p) -- the calibrated value the model card gates on.
``LayaAnswer.confidence`` therefore prefers ``answer_confidence`` and only falls
back to ``confidence`` (tolerant of ``answer`` vs ``choice`` vs ``label`` and of
``results`` / ``questions`` nesting; see ``parse_response``).
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from .config import Settings, get_settings

ANSWER_KEYS = ("choice", "answer", "label", "value")
CONFIDENCE_KEYS = ("answer_confidence", "confidence")
PROBS_KEYS = ("probabilities", "probs", "scores")
CONTAINER_KEYS = ("answers", "questions", "results")
NESTED_KEYS = ("results", "result", "data")
CHECKPOINTS = {"english", "multilingual", "typed-decisions"}
MAX_RANK_CANDIDATES = 12
HEALTH_TIMEOUT_S = 2.0


@dataclass(frozen=True)
class LayaQuestion:
    name: str
    state: dict
    instructions: str
    criteria: dict[str, str]


@dataclass
class LayaAnswer:
    question: str
    answer: str | None = None
    confidence: float | None = None
    probs: dict[str, float] = field(default_factory=dict)
    routed_model: str | None = None
    latency_ms: int | None = None
    error: str | None = None


def _question_body(question: LayaQuestion) -> dict[str, Any]:
    return {
        "type": "choice",
        "instructions": question.instructions,
        "criteria": dict(question.criteria),
    }


def build_body(question: LayaQuestion) -> dict[str, Any]:
    """The exact JSON body for ``POST /v1/systemone`` (one question, type choice)."""
    return {"state": question.state, "questions": {question.name: _question_body(question)}}


def _as_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _candidate_nodes(payload: dict) -> list[dict]:
    nodes: list[dict] = []
    queue: list[Any] = [payload]
    while queue and len(nodes) < 8:
        node = queue.pop(0)
        if not isinstance(node, dict):
            continue
        nodes.append(node)
        for key in NESTED_KEYS:
            child = node.get(key)
            if isinstance(child, dict):
                queue.append(child)
    return nodes


def _looks_like_answer(node: dict) -> bool:
    return any(key in node for key in ANSWER_KEYS + CONFIDENCE_KEYS + PROBS_KEYS)


def _find_answer(payload: dict, question: LayaQuestion) -> dict | None:
    for node in _candidate_nodes(payload):
        direct = node.get(question.name)
        if isinstance(direct, dict):
            return direct
        for key in CONTAINER_KEYS:
            container = node.get(key)
            if not isinstance(container, dict):
                continue
            found = container.get(question.name)
            if isinstance(found, dict):
                return found
            if _looks_like_answer(container):
                return container
            if len(container) == 1:
                only = next(iter(container.values()))
                if isinstance(only, dict) and _looks_like_answer(only):
                    return only
        if _looks_like_answer(node):
            return node
    return None


def parse_response(question: LayaQuestion, payload: dict) -> LayaAnswer:
    """Map a Laya response body onto a ``LayaAnswer`` without raising."""
    if not isinstance(payload, dict):
        return LayaAnswer(question=question.name, error="malformed_response")
    answer = LayaAnswer(question=question.name)
    node = _find_answer(payload, question)
    if node is None:
        answer.error = "no_answer"
        return answer

    for key in ANSWER_KEYS:
        value = node.get(key)
        if isinstance(value, str) and value in question.criteria:
            answer.answer = value
            break
    if answer.answer is None:
        for key in ANSWER_KEYS:
            value = node.get(key)
            if isinstance(value, str) and value:
                answer.answer = value
                break

    for key in CONFIDENCE_KEYS:
        value = _as_number(node.get(key))
        if value is not None:
            answer.confidence = min(1.0, max(0.0, value))
            break

    for key in PROBS_KEYS:
        value = node.get(key)
        if isinstance(value, dict):
            answer.probs = {
                str(k): number
                for k, v in value.items()
                if (number := _as_number(v)) is not None
            }
            break

    nodes = _candidate_nodes(payload)
    for candidate in nodes:
        routing = candidate.get("routing")
        if isinstance(routing, dict):
            model = routing.get("model")
            if isinstance(model, str) and model:
                answer.routed_model = model
                break
    if answer.routed_model is None:
        for candidate in nodes:
            model = candidate.get("model")
            if isinstance(model, str) and model in CHECKPOINTS:
                answer.routed_model = model
                break

    for candidate in nodes:
        latency = _as_number(candidate.get("latency_ms"))
        if latency is not None:
            answer.latency_ms = int(latency)
            break

    if answer.answer is None:
        answer.error = "no_answer"
    return answer


class LayaClient:
    """Talk to Laya over HTTP, in-process, or not at all; ``ask`` never raises."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._client: httpx.Client | None = None
        self._router: Any = None

    @property
    def enabled(self) -> bool:
        return self.settings.laya_mode != "off"

    def _http(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(timeout=float(self.settings.laya_timeout_s))
        return self._client

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def _url(self, path: str) -> str:
        return self.settings.laya_url.rstrip("/") + path

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.settings.laya_api_key}"}

    def ask(self, question: LayaQuestion) -> LayaAnswer:
        if not self.enabled:
            return LayaAnswer(question=question.name, error="laya_off")
        started = time.perf_counter()
        transport = str(self.settings.laya_transport).strip().lower()
        if transport == "http":
            answer = self._ask_http(question)
        elif transport == "inprocess":
            answer = self._ask_inprocess(question)
        else:
            answer = LayaAnswer(question=question.name, error="unknown_transport")
        if answer.latency_ms is None:
            answer.latency_ms = int(round((time.perf_counter() - started) * 1000))
        return answer

    def _ask_http(self, question: LayaQuestion) -> LayaAnswer:
        try:
            response = self._http().post(
                self._url("/v1/systemone"),
                json=build_body(question),
                headers=self._headers(),
            )
        except httpx.TimeoutException:
            return LayaAnswer(question=question.name, error="timeout")
        except Exception as exc:
            return LayaAnswer(question=question.name, error=f"transport_error:{type(exc).__name__}")
        if not 200 <= response.status_code < 300:
            return LayaAnswer(question=question.name, error=f"http_{response.status_code}")
        try:
            payload = response.json()
        except ValueError:
            return LayaAnswer(question=question.name, error="malformed_json")
        return parse_response(question, payload)

    def _get_router(self) -> Any:
        if self._router is None:
            import laya

            self._router = laya.Router(preload=True)
        return self._router

    def _ask_inprocess(self, question: LayaQuestion) -> LayaAnswer:
        try:
            router = self._get_router()
        except Exception as exc:
            return LayaAnswer(question=question.name, error=f"import_error:{type(exc).__name__}")
        try:
            payload = router.predict(question.state, {question.name: _question_body(question)})
        except Exception as exc:
            return LayaAnswer(question=question.name, error=f"predict_error:{type(exc).__name__}")
        return parse_response(question, payload)

    def health(self) -> bool:
        if not self.enabled:
            return False
        timeout = min(float(self.settings.laya_timeout_s), HEALTH_TIMEOUT_S)
        try:
            response = self._http().get(self._url("/health"), headers=self._headers(), timeout=timeout)
        except Exception:
            return False
        return 200 <= response.status_code < 300


def q_identity(existing: dict, incoming: dict) -> LayaQuestion:
    """Q1: are these two records the same person (bucketio.md 3.5)?"""
    return LayaQuestion(
        name="identity",
        state={"existing": existing, "incoming": incoming},
        instructions="Do these two records refer to the same real person at the same employer?",
        criteria={"A": "yes, same person", "B": "no, different people"},
    )


def q_route(
    domain: str,
    best_pattern: str | None,
    posterior: float,
    verified_hits: int,
    misses: int,
    patterns_seen: int,
    catch_all: bool,
) -> LayaQuestion:
    """Q2: verify a generated address or pay for a full search?"""
    return LayaQuestion(
        name="route",
        state={
            "domain": domain,
            "best_pattern": best_pattern,
            "posterior": posterior,
            "verified_hits": verified_hits,
            "misses": misses,
            "patterns_seen": patterns_seen,
            "catch_all": catch_all,
        },
        instructions=(
            "Is the learned email format reliable enough to verify a generated "
            "address instead of running a full search?"
        ),
        criteria={
            "A": "reliable enough, verify the generated address",
            "B": "not reliable, run a full search",
        },
    )


def q_rank(
    person: str,
    company: str,
    domain: str,
    known_formats: list[str],
    similar_formats: list[str],
    candidate_emails: list[str],
) -> LayaQuestion:
    """Q3: rank candidate addresses; hard cap of 12 criteria."""
    candidates = [str(email) for email in candidate_emails][:MAX_RANK_CANDIDATES]
    criteria = {f"c{index}": email for index, email in enumerate(candidates, start=1)}
    return LayaQuestion(
        name="rank",
        state={
            "person": person,
            "company": company,
            "domain": domain,
            "known_formats_at_domain": [str(item) for item in known_formats],
            "formats_at_similar_domains": [str(item) for item in similar_formats],
        },
        instructions="Which address is most likely this person's real work email?",
        criteria=criteria,
    )


def q_plausible(
    person: str,
    company: str,
    treg_email: str,
    learned_format: str | None,
) -> LayaQuestion:
    """Q4: does a Treg find look like it belongs to this person?"""
    return LayaQuestion(
        name="plausible",
        state={
            "person": person,
            "company": company,
            "treg_email": treg_email,
            "learned_format": learned_format,
        },
        instructions="Does this email address plausibly belong to this person?",
        criteria={"A": "yes, plausible", "B": "no, looks wrong or belongs to someone else"},
    )
