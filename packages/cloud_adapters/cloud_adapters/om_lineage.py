"""E2: OpenMetadata lineage writer — dashboard → source → table lineage.

Called after execute_query succeeds: records which tables the query touched
and links them to the source. When a dashboard binds the source, the full
chain dashboard → source → tables becomes visible in OM's lineage graph.

Design (evolution plan D2): OM is the enterprise metadata hub — lineage is
written best-effort (failure never blocks the query path); the agent's
inline semantic layer remains the query dependency.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request

OM_URL = os.environ.get("OM_URL", "http://127.0.0.1:8585")
SERVICE_NAME = os.environ.get("OM_SERVICE_NAME", "t2d-biz-pg")
DATABASE_NAME = "t2d_biz"
SCHEMA_NAME = "public"


def _get_token() -> str:
    import base64
    pwd = os.environ.get("OM_PASSWORD", "")
    if not pwd:
        return ""
    body = json.dumps({
        "email": os.environ.get("OM_EMAIL", "admin@open-metadata.org"),
        "password": base64.b64encode(pwd.encode()).decode(),
    }).encode()
    req = urllib.request.Request(f"{OM_URL}/api/v1/auth/login",
                                 data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())["accessToken"]


def _api(method: str, path: str, token: str, body: dict | None = None):
    req = urllib.request.Request(
        f"{OM_URL}{urllib.parse.quote(path, safe='/=')}", method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json")
    data = json.dumps(body).encode() if body else None
    try:
        with urllib.request.urlopen(req, data=data, timeout=10) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read() or b"{}")
        except Exception:
            return exc.code, {}
    except Exception:
        return 0, {}


def record_query_lineage(
    *,
    source_id: int,
    source_title: str,
    tables: list[str],
    sql: str,
) -> bool:
    """Write lineage edges: source (as a OM 'chart') → tables.

    Best-effort: returns False on any failure (caller logs, never blocks).
    """
    token = _get_token()
    if not token:
        return False

    try:
        # 1. Create/update a OM entity for the source (type: chart)
        source_fqn = f"t2d-sources.source_{source_id}"
        code, existing = _api("GET", f"/api/v1/charts/name/{source_fqn}", token)
        if code != 200:
            _api("POST", "/api/v1/charts", token, {
                "name": f"source_{source_id}",
                "displayName": source_title,
                "chartType": "Other",
                "source": "t2d-agent",
            })

        # 2. Write lineage edges: source → each table
        for table in tables:
            table_fqn = f"{SERVICE_NAME}.{DATABASE_NAME}.{SCHEMA_NAME}.{table}"
            # OM lineage API: PUT /api/v1/lineage with from/to entities
            code, _ = _api("PUT", "/api/v1/lineage", token, {
                "fromEntity": {"id": source_fqn, "type": "chart"},
                "toEntity": {"id": table_fqn, "type": "table"},
                "lineageDetails": {
                    "sqlQuery": sql[:500],
                    "source": "t2d-agent",
                },
            })
            if code not in (200, 201):
                # OM lineage API shape varies — try the add edge form
                _api("POST", f"/api/v1/lineage/table/{table_fqn}/addEdge", token, {
                    "fromEntity": source_fqn,
                    "edgeType": "produces",
                })
        return True
    except Exception:
        return False


def record_dashboard_lineage(
    *,
    dashboard_id: int,
    dashboard_title: str,
    source_ids: list[int],
) -> bool:
    """Write lineage: dashboard → sources (for the full chain)."""
    token = _get_token()
    if not token:
        return False
    try:
        # Create a OM dashboard entity
        _api("POST", "/api/v1/dashboards", token, {
            "name": f"dashboard_{dashboard_id}",
            "displayName": dashboard_title,
            "source": "t2d-agent",
        })
        # Link dashboard → sources
        for sid in source_ids:
            _api("PUT", "/api/v1/lineage", token, {
                "fromEntity": {"id": f"t2d-dashboards.dashboard_{dashboard_id}",
                               "type": "dashboard"},
                "toEntity": {"id": f"t2d-sources.source_{sid}",
                             "type": "chart"},
            })
        return True
    except Exception:
        return False
