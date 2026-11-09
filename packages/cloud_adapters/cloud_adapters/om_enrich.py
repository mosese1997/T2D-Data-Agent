"""E2: OpenMetadata schema enrichment — best-effort, never a hard dependency.

Merges OM metadata (column descriptions, tags, ownership) into the
get_authorized_schema response. If OM is unreachable or a table isn't
ingested yet, the schema passes through unchanged — the semantic YAML and
the live DB remain the primary sources (evolution plan D2).
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
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read())["accessToken"]


def _get_table(token: str, table_name: str) -> dict | None:
    """Fetch a table's OM metadata (columns with descriptions, tags, owner)."""
    fqn = f"{SERVICE_NAME}.{DATABASE_NAME}.{SCHEMA_NAME}.{table_name}"
    path = f"/api/v1/tables/name/{fqn}?fields=columns,tags,owner"
    req = urllib.request.Request(
        f"{OM_URL}{urllib.parse.quote(path, safe='/=')}")
    req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read())
    except Exception:
        return None


def enrich_schema(schema: dict) -> None:
    """Merge OM metadata into the schema dict (mutates in place).

    schema: {dataset_name: {columns: [{name, type, comment}], row_estimate}}
    """
    token = _get_token()
    if not token:
        return

    for dataset_name, meta in schema.items():
        om_table = _get_table(token, dataset_name)
        if not om_table:
            continue
        om_cols = {c["name"]: c for c in om_table.get("columns", [])}
        for col in meta.get("columns", []):
            om_col = om_cols.get(col["name"])
            if not om_col:
                continue
            # OM column description fills gaps (YAML comment takes priority)
            if om_col.get("description") and not col.get("comment"):
                col["comment"] = om_col["description"]
            # OM tags → append to comment for the model to see
            tags = [t.get("tagFQN", "") for t in (om_col.get("tags") or [])
                    if t.get("tagFQN")]
            if tags:
                suffix = f" [tags: {', '.join(tags)}]"
                if suffix not in (col.get("comment") or ""):
                    col["comment"] = (col.get("comment") or "") + suffix
        # OM owner → dataset-level annotation
        owner = om_table.get("owner")
        if owner and owner.get("name"):
            meta["owner"] = owner["name"]
