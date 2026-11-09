#!/usr/bin/env python3
"""E2: Sync the semantic layer YAML → OpenMetadata Glossary.

One-way sync (YAML stays the agent's source of truth — evolution plan D2):
- Creates/updates a Glossary named 't2d-business'
- Each metric → a GlossaryTerm with description + synonyms as description suffix
- Each business term → a GlossaryTerm
- Idempotent: existing terms are updated, not duplicated

Usage:
  python scripts/sync_semantics_to_om.py [--dry-run]
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

from semantic import load_semantics  # noqa: E402

OM_URL = os.environ.get("OM_URL", "http://127.0.0.1:8585")
OM_TOKEN = os.environ.get("OM_TOKEN", "")
GLOSSARY_NAME = os.environ.get("OM_GLOSSARY_NAME", "t2d-business")


def _get_token() -> str:
    """Login or use env token."""
    if OM_TOKEN:
        return OM_TOKEN
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
    req = urllib.request.Request(f"{OM_URL}{urllib.parse.quote(path, safe='/=')}", method=method)
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


def ensure_glossary(token: str) -> str:
    """Create the glossary if missing; return its ID."""
    code, existing = _api("GET", f"/api/v1/glossaries/name/{GLOSSARY_NAME}", token)
    if code == 200 and existing.get("id"):
        return existing["id"]
    code, created = _api("POST", "/api/v1/glossaries", token, {
        "name": GLOSSARY_NAME,
        "displayName": "t2d 业务词汇表",
        "description": "t2d 语义层同步（YAML 为源，OM 为企业元数据中心）",
    })
    if code == 200 and created.get("id"):
        return created["id"]
    # 409 = already exists (race) — re-fetch
    code, existing = _api("GET", f"/api/v1/glossaries/name/{GLOSSARY_NAME}", token)
    return existing.get("id", "")


def upsert_term(token: str, glossary_id: str, name: str, display: str,
                description: str) -> str:
    """Create or update a glossary term; return the term's fqn."""
    # Check existing
    code, existing = _api(
        "GET", f"/api/v1/glossaryTerms/name/{GLOSSARY_NAME}.{name}", token)
    if code == 200 and existing.get("id"):
        # Update description if changed
        if existing.get("description") != description:
            _api("PATCH", f"/api/v1/glossaryTerms/{existing['id']}", token, [])
            # OM PATCH needs JSON-Patch format; simplest: PUT the full body
            _api("PUT", f"/api/v1/glossaryTerms/{existing['id']}", token, {
                "name": name, "displayName": display,
                "description": description, "glossary": GLOSSARY_NAME,
            })
        return f"{GLOSSARY_NAME}.{name}"
    # Create
    code, created = _api("POST", "/api/v1/glossaryTerms", token, {
        "name": name, "displayName": display,
        "description": description, "glossary": GLOSSARY_NAME,
    })
    if code == 200 and created.get("id"):
        return created.get("fullyQualifiedName", f"{GLOSSARY_NAME}.{name}")
    # 409 = exists — re-fetch
    return f"{GLOSSARY_NAME}.{name}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    registry = load_semantics(os.path.join(ROOT, "config", "semantics"))
    token = _get_token()
    print(f"OM: {OM_URL} | glossary: {GLOSSARY_NAME} | dry-run: {args.dry_run}")

    if args.dry_run:
        for m in registry.metrics.values():
            print(f"  metric: {m.metric_key} ({m.name})")
        for t in registry.terms.values():
            print(f"  term: {t.term}")
        return 0

    gid = ensure_glossary(token)
    print(f"glossary: {GLOSSARY_NAME} (id={gid[:8]}...)")

    synced = 0
    for m in registry.active_metrics():
        desc = m.description
        if m.synonyms:
            desc += f"\n\n同义词: {', '.join(m.synonyms)}"
        if m.exclusions:
            desc += f"\n排除条件: {'; '.join(m.exclusions)}"
        fqn = upsert_term(token, gid, m.metric_key, m.name, desc)
        synced += 1
        print(f"  ✅ metric: {m.metric_key} → {fqn}")

    for t in registry.terms.values():
        desc = t.definition
        if t.aliases:
            desc += f"\n\n别名: {', '.join(t.aliases)}"
        fqn = upsert_term(token, gid, t.term, t.term, desc)
        synced += 1
        print(f"  ✅ term: {t.term} → {fqn}")

    print(f"\n✅ 同步完成: {synced} 个术语 → OM Glossary '{GLOSSARY_NAME}'")
    return 0


if __name__ == "__main__":
    sys.exit(main())
