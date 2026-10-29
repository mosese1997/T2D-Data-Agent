"""API settings — env-driven, zero extra deps (plain dataclass)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _bool(name: str, default: str = "false") -> bool:
    return os.environ.get(name, default).lower() in ("1", "true", "yes")


@dataclass(frozen=True)
class Settings:
    env: str = os.environ.get("APP_ENV", "dev")
    brand: str = os.environ.get("APP_BRAND", "t2d")
    secret_key: str = os.environ.get("APP_SECRET_KEY", "dev-insecure-secret")
    token_ttl_hours: int = int(os.environ.get("APP_TOKEN_TTL_HOURS", "72"))
    api_port: int = int(os.environ.get("API_PORT", "8001"))
    model_api_base: str = os.environ.get("MODEL_API_BASE", "http://localhost:4000/v1")
    model_name: str = os.environ.get("MODEL_NAME", "t2d/deepseek-v4.1-flash-1017")
    semantic_config_dir: str = os.environ.get(
        "SEMANTIC_CONFIG_DIR",
        os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.abspath(__file__))))), "config", "semantics"),
    )
    # demo banner is forced on when cloud credentials are absent.
    force_demo_banner: bool = field(default_factory=lambda: _bool("APP_DEMO_BANNER", "true"))


settings = Settings()
