#!/usr/bin/env python3
"""Phase 2 acceptance: foundation & data (assertion-style).

Checks (task book §17 阶段2 验收 — 授权查询、检索、文件访问分别验证):
  1. Login + /me + workspace roles (analyst_a / viewer_b).
  2. Authorized query: analyst context on latam-growth datasets succeeds;
     the SAME query through mx-focus's narrower grant set is rejected with
     object_not_authorized (+ audit rows for both).
  3. Retrieval: 10 standard phrasings, top-3 hit rate >= 9.
  4. File access: preset source file downloads via /api/files with sha256
     match; cross-workspace access denied (403).
  5. Business data: orders = 300,000.

Exit 0 only when every required check passes.
"""

from __future__ import annotations

import hashlib
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
os.environ.setdefault("STATE_DB_URL", "sqlite:///var/state.db")

RESULTS: list[tuple[str, bool, str, bool]] = []


def check(name: str, ok: bool, detail: str = "", *, required: bool = True) -> bool:
    RESULTS.append((name, bool(ok), detail, required))
    mark = "✅" if ok else ("❌" if required else "⚠️ ")
    print(f"  {mark} {name} {detail}")
    return bool(ok)


def main() -> int:
    print("═══ 阶段 2 验收 verify_phase2 ═══")
    from fastapi.testclient import TestClient

    from t2d_api.main import app

    client = TestClient(app)
    all_ok = True

    # ── 1. auth ────────────────────────────────────────────────────
    print("\n[1] 登录与身份")
    r = client.post("/api/auth/login", json={"username": "analyst_a", "password": "analyst-demo-2026"})
    ok = check("analyst_a login", r.status_code == 200)
    analyst_token = r.json().get("token") if r.status_code == 200 else ""
    headers_a = {"Authorization": f"Bearer {analyst_token}"}

    r = client.get("/api/auth/me", headers=headers_a)
    ok &= check("analyst_a /me", r.status_code == 200 and r.json().get("username") == "analyst_a")

    r = client.post("/api/auth/login", json={"username": "analyst_a", "password": "wrong"})
    ok &= check("wrong password rejected", r.status_code == 401)

    r = client.post("/api/auth/login", json={"username": "viewer_b", "password": "viewer-demo-2026"})
    viewer_token = r.json().get("token") if r.status_code == 200 else ""
    headers_v = {"Authorization": f"Bearer {viewer_token}"}
    ok &= check("viewer_b login", r.status_code == 200)

    r = client.get("/api/workspaces", headers=headers_a)
    workspaces = {w["slug"]: w for w in r.json()} if r.status_code == 200 else {}
    ok &= check(
        "analyst_a workspaces+roles",
        workspaces.get("latam-growth", {}).get("role") == "analyst"
        and workspaces.get("mx-focus") is None,  # analyst_a NOT in mx-focus
        str({k: v.get("role") for k, v in workspaces.items()}),
    )
    r = client.get("/api/workspaces", headers=headers_v)
    v_ws = {w["slug"]: w.get("role") for w in r.json()} if r.status_code == 200 else {}
    ok &= check("viewer_b role=viewer", v_ws.get("latam-growth") == "viewer", str(v_ws))
    all_ok &= ok

    # ── 2. authorized query via gateway ────────────────────────────
    print("\n[2] 授权查询（网关层）")
    from cloud_adapters.dw.postgres_dw import PostgresDataWarehouse
    from query_gateway import QueryGateway
    from query_gateway.gateway import QueryRejected
    from t2d_db.models import AuditLog, Workspace, WorkspaceDataset
    from t2d_db.session import get_sessionmaker

    maker = get_sessionmaker()
    warehouse = PostgresDataWarehouse()
    audit_rows: list[dict] = []
    gateway = QueryGateway(
        dsn_for={"draft": warehouse.dsn_for("draft"), "publisher": warehouse.dsn_for("publisher")},
        audit_hook=lambda identity, sql, meta: audit_rows.append({"identity": identity, **meta}),
    )
    with maker() as s:
        latam = s.query(Workspace).filter_by(slug="latam-growth").one()
        mx = s.query(Workspace).filter_by(slug="mx-focus").one()
        latam_datasets = {
            r.dataset_name for r in s.query(WorkspaceDataset).filter_by(workspace_id=latam.id)
        }
        mx_datasets = {
            r.dataset_name for r in s.query(WorkspaceDataset).filter_by(workspace_id=mx.id)
        }
    assert "refunds" in latam_datasets and "refunds" not in mx_datasets

    refund_sql = """
        SELECT COUNT(*) AS n FROM refunds r JOIN orders o ON o.order_id = r.order_id
        WHERE o.created_at >= CURRENT_DATE - interval '7 days'
    """
    result = gateway.execute(identity="draft", sql=refund_sql, allowed_objects=latam_datasets)
    ok = check("analyst (latam-growth) refunds query OK", result.row_count >= 1,
               f"rows={result.row_count}")
    try:
        gateway.execute(identity="draft", sql=refund_sql, allowed_objects=mx_datasets)
        ok &= check("mx-focus grant rejects refunds", False, "本应被拒")
    except QueryRejected as exc:
        ok &= check("mx-focus grant rejects refunds", exc.code == "object_not_authorized", exc.code)
    ok &= check("audit rows written", len(audit_rows) >= 2, f"{len(audit_rows)} rows")
    all_ok &= ok

    # ── 3. retrieval ───────────────────────────────────────────────
    print("\n[3] 语义检索（10 标准问法）")
    from semantic import SemanticRetriever, load_semantics

    registry = load_semantics(os.path.join(ROOT, "config", "semantics"))
    retriever = SemanticRetriever(registry)
    cases = [
        ("上周各国家GMV趋势", "gmv"), ("退款率是多少", "refund_rate"),
        ("配送时长", "fulfillment_duration"), ("销量", "item_count"),
        ("客单价", "avg_order_value"), ("订单取消的多吗", "cancel_rate"),
        ("履约距离", "fulfillment_distance"), ("活跃买家有多少", "active_buyers"),
        ("准时率", "on_time_rate"), ("退款金额", "refund_amount"),
    ]
    hits_count = 0
    for query, expected in cases:
        keys = [h.key for h in retriever.search(query, top_k=3)]
        term_refs = {t.term for t in registry.terms.values() if t.ref_metric == expected}
        if set(keys) & ({expected} | term_refs):
            hits_count += 1
    ok = check("top-3 hit rate >= 9/10", hits_count >= 9, f"{hits_count}/10")
    all_ok &= ok

    # ── 4. file access ─────────────────────────────────────────────
    print("\n[4] 文件访问（鉴权代理 + sha256）")
    from t2d_db.models import FileRef, Source

    with maker() as s:
        latam_source = (
            s.query(Source).filter_by(workspace_id=latam.id).order_by(Source.id).first()
        )
        mx_source = (
            s.query(Source).filter_by(workspace_id=mx.id).order_by(Source.id).first()
        )
        latam_file_id = latam_source.result_file_id
        mx_file_id = mx_source.result_file_id
        expected_sha = s.get(FileRef, latam_file_id).sha256

    r = client.get(f"/api/files/{latam_file_id}", headers=headers_a)
    ok = check("analyst downloads workspace file", r.status_code == 200)
    ok &= check("sha256 matches", hashlib.sha256(r.content).hexdigest() == expected_sha)

    r = client.get(f"/api/files/{mx_file_id}", headers=headers_a)
    ok &= check("cross-workspace file denied", r.status_code == 403, f"status={r.status_code}")

    r = client.get(f"/api/files/{latam_file_id}")  # no token
    ok &= check("anonymous denied", r.status_code == 401, f"status={r.status_code}")
    all_ok &= ok

    # ── 5. business data ───────────────────────────────────────────
    print("\n[5] 业务数据")
    import psycopg

    with psycopg.connect(warehouse.dsn_for("draft")) as conn:
        orders = conn.execute("SELECT count(*) FROM orders").fetchone()[0]
        items = conn.execute("SELECT count(*) FROM order_items").fetchone()[0]
        missing_fx = conn.execute(
            "SELECT count(*) FROM orders o LEFT JOIN fx_rates fx "
            "ON fx.currency = o.currency AND fx.rate_date = o.fx_date WHERE fx.rate_to_usd IS NULL"
        ).fetchone()[0]
    ok = check("orders = 300,000", orders == 300_000, f"{orders:,}")
    ok &= check("order_items loaded", items > 600_000, f"{items:,}")
    ok &= check("missing-fx orders exist (caliber test data)", missing_fx > 0, f"{missing_fx:,}")
    all_ok &= ok

    # ── result ─────────────────────────────────────────────────────
    print("\n═══ 结果 ═══")
    required_failed = [name for name, ok_, _, req in RESULTS if not ok_ and req]
    for name, ok_, detail, req in RESULTS:
        print(f"  {'✅' if ok_ else ('❌' if req else '⚠️ ')} {name}")
    passed = sum(1 for r_ in RESULTS if r_[1])
    print(f"\n通过 {passed}/{len(RESULTS)}")
    if required_failed:
        print(f"❌ 阶段 2 验收未通过：{required_failed}")
        return 1
    print("✅ 阶段 2 验收全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
