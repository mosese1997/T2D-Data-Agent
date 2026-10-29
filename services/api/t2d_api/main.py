"""t2d FastAPI app: auth, workspaces, dashboards, healthz.

SSE + tasks + sources + files routers land with the worker (phase 3);
the OpenAPI snapshot is re-frozen each phase (make freeze-openapi).
"""

from __future__ import annotations

import os
import urllib.request

from fastapi import FastAPI

from .routers import (
    admin, auth, conversations, dashboards, files, patches, publish, refresh,
    shares, sources, tasks, versions, workspaces,
)
from .settings import settings


def _litellm_reachable() -> bool:
    base = settings.model_api_base.rstrip("/")
    key = os.environ.get("MODEL_API_KEY", "")
    try:
        req = urllib.request.Request(f"{base}/models", method="GET")
        if key:
            req.add_header("Authorization", f"Bearer {key}")
        with urllib.request.urlopen(req, timeout=3) as resp:
            return resp.status == 200
    except urllib.error.HTTPError as exc:
        # 401/403 means the endpoint is alive (probe just lacks auth scope).
        return exc.code in (401, 403)
    except Exception:
        return False


def _business_pg_reachable() -> bool:
    try:
        from cloud_adapters.dw.postgres_dw import PostgresDataWarehouse

        return PostgresDataWarehouse().test_connection()
    except Exception:
        return False


def create_app() -> FastAPI:
    app = FastAPI(
        title=f"{settings.brand} API",
        version="0.1.0",
        description="Agentic Talk to Data — 演示环境（HTTP，非生产）",
    )
    app.include_router(auth.router)
    app.include_router(workspaces.router)
    app.include_router(dashboards.router)
    app.include_router(files.router)
    app.include_router(conversations.router)
    app.include_router(tasks.router)
    app.include_router(patches.router)
    app.include_router(sources.router)
    app.include_router(versions.router)
    app.include_router(publish.router)
    app.include_router(shares.router)
    app.include_router(refresh.router)
    app.include_router(admin.router)

    @app.get("/api/healthz", tags=["ops"])
    def healthz():
        from .deps import demo_mode

        return {
            "status": "ok",
            "brand": settings.brand,
            "env": settings.env,
            "demo_mode": demo_mode(),
            "model": settings.model_name,
            "checks": {
                "litellm": _litellm_reachable(),
                "business_pg": _business_pg_reachable(),
                "state_db": True,  # serving this response proves it
            },
        }

    return app


app = create_app()
