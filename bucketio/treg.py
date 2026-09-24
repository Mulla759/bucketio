"""Treg adapter: one interface, three implementations (mock / http / cli).

Treg is an external black box; its real endpoints are [CONFIRM] values, so the
HTTP and CLI clients are tolerant about the routed-response shape and fall back
to configured prices when Treg does not report a cost. The mock client is
deterministic and reads ``tests/fixtures/treg_mock.json``.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol
from urllib.parse import urlparse

import httpx

from .config import Settings, get_settings, read_treg_cli_token
from .normalize import normalize_company, normalize_name

Status = Literal["valid", "invalid", "catch_all", "unknown", "risky", "not_found", "error"]

TREG_MOCK_FIXTURE = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "treg_mock.json"

_VALID_WORDS = frozenset({"valid"})
_INVALID_WORDS = frozenset({"invalid"})
_CATCH_ALL_WORDS = frozenset({"catch_all", "catch-all", "accept_all", "accept-all", "is_accept_all"})
_RISKY_WORDS = frozenset({"risky"})
_NOT_FOUND_WORDS = frozenset({"not_found", "not-found", "miss"})

_STDERR_COST = re.compile(r"charged\s+\$?\s*([0-9]+(?:\.[0-9]+)?)")
_MICRO_USD = 1_000_000.0


def map_status(word: str | None) -> Status:
    """Map Treg's status vocabulary onto BucketIO's enum.

    Unknown or empty words map to ``unknown``; callers decide what to do.
    """
    if word is None:
        return "unknown"
    key = str(word).strip().lower()
    if key in _VALID_WORDS:
        return "valid"
    if key in _INVALID_WORDS:
        return "invalid"
    if key in _CATCH_ALL_WORDS:
        return "catch_all"
    if key in _RISKY_WORDS:
        return "risky"
    if key in _NOT_FOUND_WORDS:
        return "not_found"
    return "unknown"


@dataclass
class TregResult:
    email: str | None
    domain: str | None
    status: Status
    raw: dict
    cost_units: float = 0.0
    kind: Literal["find", "verify"] = "find"


class TregClient(Protocol):
    def find(self, name: str, company: str) -> TregResult: ...

    def verify(self, email: str) -> TregResult: ...


class NotConfigured(RuntimeError):
    """Raised when a real Treg transport is selected without credentials."""


def _default_fixture_path() -> Path:
    if TREG_MOCK_FIXTURE.exists():
        return TREG_MOCK_FIXTURE
    return Path.cwd() / "tests" / "fixtures" / "treg_mock.json"


def _clean_domain(value: object) -> str | None:
    if value is None or not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if "://" in text:
        text = urlparse(text).netloc or ""
    text = text.split("/")[0].strip().lower().strip(".")
    if text.startswith("www."):
        text = text[4:]
    return text or None


def _domain_from_email(email: str | None) -> str | None:
    if not email or "@" not in email:
        return None
    return _clean_domain(email.rpartition("@")[2])


def _registry_cost(headers: httpx.Headers | None) -> float | None:
    if headers is None:
        return None
    raw = headers.get("X-Treg-Cost-Micro")
    if raw is None:
        return None
    try:
        return float(raw) / _MICRO_USD
    except (TypeError, ValueError):
        return None


def _stderr_cost(stderr: str | None) -> float | None:
    match = _STDERR_COST.search(stderr or "")
    if match is None:
        return None
    try:
        return float(match.group(1))
    except ValueError:  # pragma: no cover - regex already constrains this
        return None


def _parse_result(
    body: object,
    *,
    kind: Literal["find", "verify"],
    cost_units: float,
    fallback_email: str | None = None,
) -> TregResult:
    """Tolerant parse of a routed Treg response: {output, raw, _treg}."""
    if not isinstance(body, dict):
        body = {"output": body}
    output = body.get("output")
    output = output if isinstance(output, dict) else {}
    raw = body.get("raw")
    raw = raw if isinstance(raw, dict) else {}
    meta = body.get("_treg")
    meta = meta if isinstance(meta, dict) else {}

    email = output.get("email") or raw.get("email") or fallback_email
    email = str(email) if email else None

    status_word = output.get("status") or raw.get("status") or meta.get("status")
    if status_word is not None:
        status = map_status(str(status_word))
    elif isinstance(output.get("verified"), bool):
        status = "valid" if output["verified"] else "invalid"
    elif isinstance(output.get("verified"), str):
        status = map_status(output["verified"])
    else:
        status = "unknown"

    company = raw.get("company")
    company_domain = company.get("domain") if isinstance(company, dict) else None
    domain = (
        _clean_domain(raw.get("domain"))
        or _clean_domain(output.get("domain"))
        or _clean_domain(raw.get("website_url"))
        or _clean_domain(company_domain)
        or _domain_from_email(email)
    )

    return TregResult(
        email=email,
        domain=domain,
        status=status,
        raw=body,
        cost_units=float(cost_units),
        kind=kind,
    )


class TregMockClient:
    """Deterministic fake Treg backed by a JSON fixture."""

    def __init__(
        self,
        path: Path | str | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.path = Path(path) if path is not None else _default_fixture_path()
        self.data = json.loads(self.path.read_text(encoding="utf-8"))

    def _result(
        self,
        *,
        kind: Literal["find", "verify"],
        email: str | None,
        domain: str | None,
        status: Status,
        cost: float,
        extra: dict | None = None,
    ) -> TregResult:
        raw: dict = {"status": status, "email": email, "domain": domain}
        if extra:
            raw.update(extra)
        return TregResult(
            email=email,
            domain=domain,
            status=status,
            raw=raw,
            cost_units=float(cost),
            kind=kind,
        )

    def find(self, name: str, company: str) -> TregResult:
        key = normalize_company(company)
        domain = (self.data.get("company_domains") or {}).get(key)
        if not domain:
            return self._result(
                kind="find", email=None, domain=None, status="not_found", cost=0.0
            )

        info = (self.data.get("domains") or {}).get(domain) or {}
        if info.get("not_found"):
            return self._result(
                kind="find", email=None, domain=domain, status="not_found", cost=0.0
            )

        local = (info.get("people") or {}).get(normalize_name(name).name_key)
        if not local:
            return self._result(
                kind="find", email=None, domain=domain, status="not_found", cost=0.0
            )

        status: Status = "catch_all" if info.get("catch_all") else "valid"
        return self._result(
            kind="find",
            email=f"{local}@{domain}",
            domain=domain,
            status=status,
            cost=float(self.settings.treg_find_cost),
            extra={"pattern": info.get("pattern")},
        )

    def verify(self, email: str) -> TregResult:
        local, _, domain = (email or "").rpartition("@")
        domain = _clean_domain(domain)
        info = (self.data.get("domains") or {}).get(domain) if domain else None
        if info is None:
            return self._result(
                kind="verify", email=email, domain=domain, status="unknown", cost=0.0
            )

        cost = float(self.settings.treg_verify_cost)
        if info.get("catch_all"):
            return self._result(
                kind="verify", email=email, domain=domain, status="catch_all", cost=cost
            )

        known = info.get("known_valid") or []
        status: Status = "valid" if local in known else "invalid"
        return self._result(
            kind="verify", email=email, domain=domain, status=status, cost=cost
        )


class TregHttpClient:
    """HTTP transport: POST {base}/call/treg.people.email.{find,verify}."""

    FIND_ENDPOINT = "treg.people.email.find"
    VERIFY_ENDPOINT = "treg.people.email.verify"

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        client: httpx.Client | None = None,
        token: str | None = None,
        base_url: str | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.base_url = (
            base_url if base_url is not None else (self.settings.treg_base_url or "")
        ).strip().rstrip("/")
        self.token = token if token is not None else (
            self.settings.treg_token or read_treg_cli_token()
        )
        if not self.base_url:
            raise NotConfigured("TREG_BASE_URL is not configured")
        if not self.token:
            raise NotConfigured("TREG_TOKEN is not configured (and no treg CLI login found)")
        self._client = client or httpx.Client(timeout=self.settings.treg_timeout_s)

    def close(self) -> None:
        self._client.close()

    def _headers(self) -> dict[str, str]:
        headers = {"X-Treg-Token": self.token, "Content-Type": "application/json"}
        if self.settings.treg_org:
            headers["X-Treg-Org"] = self.settings.treg_org
        return headers

    def _post(self, endpoint: str, payload: dict) -> tuple[object, float | None]:
        response = self._client.post(
            f"{self.base_url}/call/{endpoint}",
            json=payload,
            headers=self._headers(),
        )
        response.raise_for_status()
        try:
            body: object = response.json()
        except ValueError:
            body = {"output": {"raw_text": response.text}}
        return body, _registry_cost(response.headers)

    def find(self, name: str, company: str) -> TregResult:
        body, cost = self._post(
            self.FIND_ENDPOINT, {"domain": company, "full_name": name}
        )
        return _parse_result(
            body,
            kind="find",
            cost_units=cost if cost is not None else float(self.settings.treg_find_cost),
        )

    def verify(self, email: str) -> TregResult:
        body, cost = self._post(self.VERIFY_ENDPOINT, {"email": email})
        return _parse_result(
            body,
            kind="verify",
            cost_units=cost if cost is not None else float(self.settings.treg_verify_cost),
            fallback_email=email,
        )


class TregCliClient:
    """CLI transport: ``treg call <endpoint> --data <json>``."""

    FIND_ENDPOINT = "treg.people.email.find"
    VERIFY_ENDPOINT = "treg.people.email.verify"

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        executable: str = "treg",
    ) -> None:
        self.settings = settings or get_settings()
        self.executable = executable
        token = self.settings.treg_token or read_treg_cli_token()
        if not token:
            raise NotConfigured("TREG_TOKEN is not configured (and no treg CLI login found)")

    def _run(self, endpoint: str, payload: dict) -> tuple[object, float | None]:
        command = [
            self.executable,
            "call",
            endpoint,
            "--data",
            json.dumps(payload),
        ]
        try:
            proc = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=self.settings.treg_timeout_s,
            )
        except FileNotFoundError as exc:
            raise NotConfigured(
                f"treg CLI executable not found: {self.executable!r}"
            ) from exc
        if proc.returncode != 0:
            raise RuntimeError(
                f"treg call {endpoint} failed ({proc.returncode}): {proc.stderr.strip()}"
            )
        try:
            body: object = json.loads(proc.stdout)
        except ValueError as exc:
            raise ValueError(
                f"treg CLI returned non-JSON stdout: {proc.stdout[:200]!r}"
            ) from exc
        return body, _stderr_cost(proc.stderr)

    def find(self, name: str, company: str) -> TregResult:
        body, cost = self._run(
            self.FIND_ENDPOINT, {"domain": company, "full_name": name}
        )
        return _parse_result(
            body,
            kind="find",
            cost_units=cost if cost is not None else float(self.settings.treg_find_cost),
        )

    def verify(self, email: str) -> TregResult:
        body, cost = self._run(self.VERIFY_ENDPOINT, {"email": email})
        return _parse_result(
            body,
            kind="verify",
            cost_units=cost if cost is not None else float(self.settings.treg_verify_cost),
            fallback_email=email,
        )


def make_client(settings: Settings | None = None) -> TregClient:
    """Build the client selected by ``TREG_MODE`` (mock / http / cli)."""
    settings = settings or get_settings()
    mode = str(settings.treg_mode).strip().lower()
    if mode == "mock":
        return TregMockClient(settings=settings)
    if mode == "http":
        return TregHttpClient(settings=settings)
    if mode == "cli":
        return TregCliClient(settings=settings)
    raise NotConfigured(f"unknown TREG_MODE: {settings.treg_mode!r}")
