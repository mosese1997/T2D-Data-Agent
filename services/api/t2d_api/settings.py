"""API settings — env-driven, zero extra deps (plain dataclass)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _bool(name: str, default: str = "false") -> bool:
    return os.environ.get(name, default).lower() in ("1", "true", "yes")


def _find_semantic_config_dir() -> str:
    """Env var first; then walk up (dev tree vs container layouts differ)."""
    env = os.environ.get("SEMANTIC_CONFIG_DIR")
    if env:
        return env
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "config" / "semantics"
        if (candidate / "metrics.yaml").is_file():
            return str(candidate)
    # Container layout: config is COPY'd to /app/config (not a parent of
    # site-packages) — explicit fallback.
    if Path("/app/config/semantics/metrics.yaml").is_file():
        return "/app/config/semantics"
    return "config/semantics"  # let load_semantics surface the error


@dataclass(frozen=True)
class Settings:
    env: str = os.environ.get("APP_ENV", "dev")
    brand: str = os.environ.get("APP_BRAND", "t2d")
    secret_key: str = os.environ.get("APP_SECRET_KEY", "dev-insecure-secret")
    token_ttl_hours: int = int(os.environ.get("APP_TOKEN_TTL_HOURS", "72"))
    api_port: int = int(os.environ.get("API_PORT", "8001"))
    model_api_base: str = os.environ.get("MODEL_API_BASE", "http://localhost:4000/v1")
    model_name: str = os.environ.get("MODEL_NAME", "t2d/deepseek-v4.1-flash-1017")
    semantic_config_dir: str = os.environ.get("SEMANTIC_CONFIG_DIR", _find_semantic_config_dir())
    # demo banner is forced on when cloud credentials are absent.
    force_demo_banner: bool = field(default_factory=lambda: _bool("APP_DEMO_BANNER", "true"))


settings = Settings()
