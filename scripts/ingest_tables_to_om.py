#!/usr/bin/env pythons
"""E2: Ingest business PG table metadata into OpenMetadata.

Creates databaseService + databaseSchemas + tables with column metadata
via the OM REST API (no ingestion image needed — direct API calls).

This makes OM the enterprise metadata hub for table structure; the agent's
get_authorized_schema can then optionally read from OM for richer metadata
(column descriptions, tags, ownership).

Usage: python scripts/ingest_tables_to_om.py [--tables orders,order_items]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("STATE_DB_URL", "sqlite:///var/state.db")

OM_URL = os.environ.get("OM_URL", "http://127.0.0.1:8585")
SERVICE_NAME = os.environ.get("OM_SERVICE_NAME", "t2d-biz-pg")
DATABASE_NAME = "t2d_biz"
SCHEMA_NAME = "public"


def _get_token() -> str:
    import base64
    pwd = os.environ.get("OM_PASSWORD", "OpenMetadata-demo-2026")
    body = json.dumps({
        "email": os.environ.get("OM_EMAIL", "admin@open-metadata.org"),
        "password": base64.b64encode(pwd.encode()).decode(),
    }).encode()
    req = urllib.request.Request(f"{OM_URL}/api/v1/auth/login",
                                 data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())["accessToken"]


def _api(method: str, path: str, token: str, body: dict | None = None):
    req = urllib.request.Request(
        f"{OM_URL}{urllib.parse.quote(path, safe='/=')}", method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json")
    data = json.dumps(body).encode() if body else None
    try:
        with urllib.request.urlopen(req, data=data, timeout=15) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read() or b"{}")
        except Exception:
            return exc.code, {}


def ensure_service(token: str) -> str:
    """Create the databaseService if missing; return its ID."""
    code, existing = _api("GET", f"/api/v1/services/databaseServices/name/{SERVICE_NAME}", token)
    if code == 200 and existing.get("id"):
        return existing["id"]
    code, created = _api("POST", "/api/v1/services/databaseServices", token, {
        "name": SERVICE_NAME,
        "serviceType": "Postgres",
        "connection": {"config": {
            "type": "Postgres",
            "username": "t2d",
            "hostPort": os.environ.get("DEMO_PG_HOST", "localhost") + ":5432",
            "database": DATABASE_NAME,
        }},
    })
    if code == 200 and created.get("id"):
        return created["id"]
    code, existing = _api("GET", f"/api/v1/services/databaseServices/name/{SERVICE_NAME}", token)
    return existing.get("id", "")


def ensure_database(token: str, service_id: str) -> str:
    """Create the database if missing; return its ID."""
    code, existing = _api("GET", f"/api/v1/databases/{SERVICE_NAME}.{DATABASE_NAME}", token)
    if code == 200 and existing.get("id"):
        return existing["id"]
    code, created = _api("POST", "/api/v1/databases", token, {
        "name": DATABASE_NAME,
        "service": SERVICE_NAME,
    })
    if code == 200 and created.get("id"):
        return created["id"]
    code, existing = _api("GET", f"/api/v1/databases/{SERVICE_NAME}.{DATABASE_NAME}", token)
    return existing.get("id", "")


def ensure_schema(token: str, database_id: str) -> str:
    code, existing = _api("GET", f"/api/v1/databaseSchemas/{SERVICE_NAME}.{DATABASE_NAME}.{SCHEMA_NAME}", token)
    if code == 200 and existing.get("id"):
        return existing["id"]
    code, created = _api("POST", "/api/v1/databaseSchemas", token, {
        "name": SCHEMA_NAME,
        "database": f"{SERVICE_NAME}.{DATABASE_NAME}",
    })
    if code == 200 and created.get("id"):
        return created["id"]
    code, existing = _api("GET", f"/api/v1/databaseSchemas/{SERVICE_NAME}.{DATABASE_NAME}.{SCHEMA_NAME}", token)
    return existing.get("id", "")


def get_table_columns(table_name: str) -> list[dict]:
    """Read column metadata from the business PG."""
    import psycopg
    dsn = (f"host={os.environ.get('DEMO_PG_HOST', 'localhost')} "
           f"port={os.environ.get('DEMO_PG_PORT', '5434')} "
           f"dbname={DATABASE_NAME} "
           f"user={os.environ.get('DEMO_PG_USER', 't2d')} "
           f"password={os.environ.get('DEMO_PG_PASSWORD', 't2d-demo-only')}")
    with psycopg.connect(dsn) as conn:
        rows = conn.execute("""
            SELECT column_name, data_type,
                   col_description(
                     (quote_ident('public') || '.' || quote_ident(%s))::regclass::oid,
                     ordinal_position)
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = %s
            ORDER BY ordinal_position
        """, (table_name, table_name)).fetchall()
    # OM 接受的类型名与 PG 原生类型不同——映射到 OM 兼容名
    type_map = {
        "bigint": "BIGINT",
        "integer": "INT",
        "character varying": "VARCHAR",
        "numeric": "NUMERIC",
        "timestamp without time zone": "TIMESTAMP",
        "date": "DATE",
    }
    cols = []
    for r in rows:
        col = {"name": r[0], "dataType": type_map.get(r[1], r[1].upper())}
        if col["dataType"] == "VARCHAR":
            col["dataLength"] = 255  # OM 要求 VARCHAR 必须有 dataLength
        cols.append(col)
    return cols


def upsert_table(token: str, schema_id: str, table_name: str) -> bool:
    """Create or update a table with column metadata."""
    columns = get_table_columns(table_name)
    fqn = f"{SERVICE_NAME}.{DATABASE_NAME}.{SCHEMA_NAME}.{table_name}"

    # Check existing
    code, existing = _api("GET", f"/api/v1/tables/name/{fqn}", token)
    if code == 200 and existing.get("id"):
        # Update columns
        _api("PUT", f"/api/v1/tables/{existing['id']}", token, {
            "name": table_name,
            "displayName": table_name,
            "databaseSchema": f"{SERVICE_NAME}.{DATABASE_NAME}.{SCHEMA_NAME}",
            "columns": columns,
        })
        return True

    # Create
    schema_fqn = f"{SERVICE_NAME}.{DATABASE_NAME}.{SCHEMA_NAME}"
    code, created = _api("POST", "/api/v1/tables", token, {
        "name": table_name,
        "displayName": table_name,
        "databaseSchema": f"{SERVICE_NAME}.{DATABASE_NAME}.{SCHEMA_NAME}",
        "columns": columns,
    })
    if code in (200, 201):
        return True
    if code == 409:
        return True  # already exists
    print(f"  ⚠️ table {table_name}: HTTP {code} {json.dumps(created)[:100]}")
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tables", default="", help="逗号分隔的表名；缺省全部业务表")
    args = parser.parse_args()

    all_tables = ["dim_country", "dim_city", "dim_category", "dim_channel",
                  "dim_product", "fx_rates", "orders", "order_items",
                  "refunds", "fulfillment_events"]
    tables = args.tables.split(",") if args.tables else all_tables

    token = _get_token()
    print(f"OM: {OM_URL} | service: {SERVICE_NAME} | tables: {len(tables)}")

    service_id = ensure_service(token)
    print(f"service: {SERVICE_NAME} (id={service_id[:8]}...)")
    database_id = ensure_database(token, service_id)
    schema_id = ensure_schema(token, database_id)
    print(f"database: {DATABASE_NAME} | schema: {SCHEMA_NAME}")

    ok = 0
    for table in tables:
        if upsert_table(token, schema_id, table):
            ok += 1
            print(f"  ✅ table: {table}")
        else:
            print(f"  ❌ table: {table}")

    print(f"\n✅ 摄取完成: {ok}/{len(tables)} 表 → OM")
    return 0 if ok == len(tables) else 1


if __name__ == "__main__":
    sys.exit(main())
