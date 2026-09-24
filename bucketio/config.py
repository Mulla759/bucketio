"""Configuration, loaded from .env / environment with safe defaults.

Defaults are chosen so that a fresh checkout runs fully offline:
TREG_MODE=mock and LAYA_MODE=off need no network and no credentials.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

TREG_CONFIG_PATH = Path.home() / ".treg" / "config.json"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- storage ---
    db_path: Path = Path("./bucketio.db")

    # --- Treg ---
    treg_mode: Literal["mock", "http", "cli"] = "mock"
    treg_base_url: str = "https://treg.to"
    treg_token: str | None = Field(
        default=None,
        validation_alias=AliasChoices("TREG_TOKEN", "TREG_API_KEY"),
    )
    treg_org: str | None = None
    treg_find_cost: float = 0.004834
    treg_verify_cost: float = 0.0015
    treg_timeout_s: float = 60.0

    # --- Laya ---
    laya_mode: Literal["off", "shadow", "active"] = "off"
    laya_transport: Literal["http", "inprocess"] = "http"
    laya_url: str = "http://127.0.0.1:8001"
    laya_api_key: str = "change-me"
    laya_timeout_s: float = 1.5
    laya_weight: float = 0.3

    # --- routing ---
    cache_ttl_days: int = 90
    verify_min_posterior: float = 0.60
    verify_min_hits: int = 2
    verify_max_tries: int = 2
    generate_verify_top: bool = True

    # --- misc ---
    use_tf: bool = True

    @property
    def auth_token(self) -> str | None:
        """Treg token from .env/env, falling back to the treg CLI's config."""
        if self.treg_token:
            return self.treg_token
        return read_treg_cli_token()


def read_treg_cli_token(path: Path | None = None) -> str | None:
    """Read the token written by `treg login`, if the CLI is installed."""
    cfg = path or TREG_CONFIG_PATH
    try:
        data = json.loads(cfg.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    token = data.get("token")
    return token if isinstance(token, str) and token else None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    get_settings.cache_clear()


def load_dotenv(path: Path | str = ".env") -> None:
    """Minimal .env loader for code paths that run before Settings exists."""
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value
