#!/usr/bin/env python3
"""Seed 3 preset dashboards with REAL sources executed through the gateway.

Each source: gateway-validated SQL → executed against the business PG →
full result stored via the FileStore → FileRef + Source rows. The canvas
binds components to source ids. This exercises the same pipeline the agent
will drive in phase 3 (and gives Home/Pods real content on first boot).

Missing-fx caliber: SQL uses a LATERAL nearest-prior-rate join — the
reference pattern for the query agent (see config/semantics/join_rules.yaml
notes on orders_to_fx).
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cloud_adapters.dw.postgres_dw import PostgresDataWarehouse
from cloud_adapters.files.local_volume import LocalVolumeFileStore
from query_gateway import QueryGateway
from t2d_db.models import (
    AuditLog, Dashboard, DashboardVersion, FileRef, Source, Workspace,
)
from t2d_db.session import get_sessionmaker, utcnow
from dashboard_schema.canvas import Canvas

ALL_DATASETS = {
    "orders", "order_items", "refunds", "fulfillment_events",
    "dim_country", "dim_city", "dim_category", "dim_channel", "dim_product", "fx_rates",
}

# LATERAL nearest-prior fx join (missing-rate fallback, per caliber rules)
FX_JOIN = """
LEFT JOIN LATERAL (
  SELECT rate_to_usd FROM fx_rates
  WHERE fx_rates.currency = o.currency AND fx_rates.rate_date <= o.fx_date
  ORDER BY fx_rates.rate_date DESC LIMIT 1
) fx ON true
"""

LAST_7D = "o.created_at >= CURRENT_DATE - interval '7 days' AND o.created_at < CURRENT_DATE"

DASHBOARDS = [
    {
        "workspace": "latam-growth",
        "title": "拉美 GMV 总览",
        "sources": [
            {
                "title": "GMV 核心指标（近7天）",
                "sql": f"""
                    SELECT
                      ROUND(SUM(oi.line_amount / fx.rate_to_usd)::numeric, 2) AS gmv_usd,
                      COUNT(DISTINCT o.order_id) AS order_count,
                      ROUND((SUM(oi.line_amount / fx.rate_to_usd)
                             / NULLIF(COUNT(DISTINCT o.order_id), 0))::numeric, 2) AS avg_order_value,
                      COUNT(DISTINCT o.user_id) AS active_buyers
                    FROM orders o
                    JOIN order_items oi ON oi.order_id = o.order_id
                    {FX_JOIN}
                    WHERE o.status != 'cancelled' AND {LAST_7D}
                """,
                "caliber": ["排除已取消订单", "金额按订单日汇率折算 USD（缺失日就近回退）",
                            "滚动 7 天，排除今日", "明细扇出下按 order_id 去重计数"],
            },
            {
                "title": "GMV 日趋势（按国家）",
                "sql": f"""
                    SELECT
                      o.created_at::date AS day,
                      o.country_code,
                      ROUND(SUM(oi.line_amount / fx.rate_to_usd)::numeric, 2) AS gmv_usd
                    FROM orders o
                    JOIN order_items oi ON oi.order_id = o.order_id
                    {FX_JOIN}
                    WHERE o.status != 'cancelled' AND {LAST_7D}
                    GROUP BY 1, 2 ORDER BY 1, 2
                """,
                "caliber": ["排除已取消订单", "金额折算 USD", "滚动 7 天，排除今日"],
            },
            {
                "title": "国家 GMV 明细（近7天）",
                "sql": f"""
                    SELECT
                      c.country_name AS country,
                      o.country_code,
                      ROUND(SUM(oi.line_amount / fx.rate_to_usd)::numeric, 2) AS gmv_usd,
                      COUNT(DISTINCT o.order_id) AS order_count
                    FROM orders o
                    JOIN order_items oi ON oi.order_id = o.order_id
                    JOIN dim_country c ON c.country_code = o.country_code
                    {FX_JOIN}
                    WHERE o.status != 'cancelled' AND {LAST_7D}
                    GROUP BY 1, 2 ORDER BY gmv_usd DESC
                """,
                "caliber": ["排除已取消订单", "金额折算 USD", "滚动 7 天，排除今日"],
            },
        ],
        "canvas": {
            "filters": {"allowed": ["country", "date"]},
            "components": [
                {"id": "k1", "type": "metric_card", "title": "GMV (USD)", "span": 3,
                 "field": "gmv_usd", "display": {"unit": "currency", "precision": 0}},
                {"id": "k2", "type": "metric_card", "title": "订单量", "span": 3, "field": "order_count"},
                {"id": "k3", "type": "metric_card", "title": "客单价 (USD)", "span": 3,
                 "field": "avg_order_value", "display": {"unit": "currency", "precision": 2}},
                {"id": "k4", "type": "metric_card", "title": "下单用户数", "span": 3, "field": "active_buyers"},
                {"id": "t1", "type": "line_chart", "title": "GMV 日趋势（按国家）", "span": 8,
                 "x": {"field": "day"}, "series": [{"field": "gmv_usd", "name": "GMV", "split_by": "country_code"}]},
                {"id": "b1", "type": "bar_chart", "title": "国家 GMV 对比", "span": 4,
                 "x": {"field": "country"}, "series": [{"field": "gmv_usd", "name": "GMV"}]},
                {"id": "tb1", "type": "data_table", "title": "国家明细", "span": 12,
                 "columns": ["country", "gmv_usd", "order_count"]},
                {"id": "x1", "type": "text_block", "span": 12,
                 "content": "口径：排除已取消订单；金额按订单日汇率折算 USD（缺失日就近回退）；滚动 7 天，排除今日；计数按 order_id 去重。"},
            ],
            "bind": {"k1": 0, "k2": 0, "k3": 0, "k4": 0, "t1": 1, "b1": 2, "tb1": 2, "x1": None},
        },
    },
    {
        "workspace": "latam-growth",
        "title": "履约监控",
        "sources": [
            {
                "title": "履约核心指标（近7天送达）",
                "sql": """
                    SELECT
                      ROUND(AVG(EXTRACT(EPOCH FROM (fe.occurred_at - o.created_at)) / 3600.0)::numeric, 2) AS avg_duration_h,
                      ROUND((COUNT(DISTINCT CASE WHEN fe.occurred_at - o.created_at <= interval '48 hours'
                                 THEN o.order_id END)::numeric
                             / NULLIF(COUNT(DISTINCT o.order_id), 0) * 100), 1) AS on_time_pct,
                      ROUND(AVG(fe.distance_km)::numeric, 2) AS avg_distance_km
                    FROM fulfillment_events fe
                    JOIN orders o ON o.order_id = fe.order_id
                    WHERE fe.event_type = 'delivered'
                      AND o.status != 'cancelled'
                      AND fe.occurred_at >= CURRENT_DATE - interval '7 days'
                      AND fe.occurred_at < CURRENT_DATE
                """,
                "caliber": ["仅统计 delivered 事件", "排除已取消订单", "准时=48小时内送达",
                            "分母为零显示「—」"],
            },
            {
                "title": "各国履约时长（近7天）",
                "sql": """
                    SELECT
                      c.country_name AS country,
                      ROUND(AVG(EXTRACT(EPOCH FROM (fe.occurred_at - o.created_at)) / 3600.0)::numeric, 2) AS avg_duration_h,
                      ROUND((COUNT(DISTINCT CASE WHEN fe.occurred_at - o.created_at <= interval '48 hours'
                                 THEN o.order_id END)::numeric
                             / NULLIF(COUNT(DISTINCT o.order_id), 0) * 100), 1) AS on_time_pct
                    FROM fulfillment_events fe
                    JOIN orders o ON o.order_id = fe.order_id
                    JOIN dim_country c ON c.country_code = o.country_code
                    WHERE fe.event_type = 'delivered' AND o.status != 'cancelled'
                      AND fe.occurred_at >= CURRENT_DATE - interval '7 days'
                      AND fe.occurred_at < CURRENT_DATE
                    GROUP BY 1 ORDER BY avg_duration_h DESC
                """,
                "caliber": ["仅 delivered 事件", "排除已取消订单"],
            },
            {
                "title": "履约异常订单（近7天）",
                "sql": """
                    SELECT
                      c.country_name AS country,
                      COUNT(DISTINCT fe.order_id) AS exception_orders
                    FROM fulfillment_events fe
                    JOIN orders o ON o.order_id = fe.order_id
                    JOIN dim_country c ON c.country_code = o.country_code
                    WHERE fe.event_type = 'exception' AND o.status != 'cancelled'
                      AND fe.occurred_at >= CURRENT_DATE - interval '7 days'
                      AND fe.occurred_at < CURRENT_DATE
                    GROUP BY 1 ORDER BY exception_orders DESC
                """,
                "caliber": ["exception 事件按订单去重", "排除已取消订单"],
            },
        ],
        "canvas": {
            "filters": {"allowed": ["country", "date"]},
            "components": [
                {"id": "k1", "type": "metric_card", "title": "平均履约时长 (h)", "span": 4, "field": "avg_duration_h"},
                {"id": "k2", "type": "metric_card", "title": "准时送达率 %", "span": 4, "field": "on_time_pct"},
                {"id": "k3", "type": "metric_card", "title": "平均配送距离 (km)", "span": 4, "field": "avg_distance_km"},
                {"id": "b1", "type": "bar_chart", "title": "各国履约时长", "span": 6,
                 "x": {"field": "country"}, "series": [{"field": "avg_duration_h", "name": "小时"}]},
                {"id": "b2", "type": "bar_chart", "title": "各国准时率 %", "span": 6,
                 "x": {"field": "country"}, "series": [{"field": "on_time_pct", "name": "准时率"}]},
                {"id": "tb1", "type": "data_table", "title": "履约异常订单", "span": 12,
                 "columns": ["country", "exception_orders"]},
                {"id": "x1", "type": "text_block", "span": 12,
                 "content": "口径：仅统计 delivered/exception 事件；排除已取消订单；准时=下单后 48 小时内送达；比率分母为零显示「—」。"},
            ],
            "bind": {"k1": 0, "k2": 0, "k3": 0, "b1": 1, "b2": 1, "tb1": 2, "x1": None},
        },
    },
    {
        "workspace": "mx-focus",
        "title": "退款分析（墨西哥专项）",
        "sources": [
            {
                "title": "退款核心指标（近30天）",
                "sql": f"""
                    SELECT
                      ROUND(SUM(r.refund_amount / fx.rate_to_usd)::numeric, 2) AS refund_usd,
                      ROUND((COUNT(DISTINCT r.order_id)::numeric
                             / NULLIF(COUNT(DISTINCT o.order_id), 0) * 100), 2) AS refund_rate_pct
                    FROM refunds r
                    JOIN orders o ON o.order_id = r.order_id
                    {FX_JOIN}
                    WHERE o.country_code = 'MX'
                      AND o.created_at >= CURRENT_DATE - interval '30 days'
                      AND o.created_at < CURRENT_DATE
                """,
                "caliber": ["仅墨西哥", "金额按订单日汇率折算 USD", "退款率=退款订单数/订单量（取消单不计入分母）",
                            "滚动 30 天，排除今日"],
            },
            {
                "title": "退款原因分布（近30天）",
                "sql": f"""
                    SELECT
                      r.reason,
                      ROUND(SUM(r.refund_amount / fx.rate_to_usd)::numeric, 2) AS refund_usd,
                      COUNT(DISTINCT r.order_id) AS refund_orders
                    FROM refunds r
                    JOIN orders o ON o.order_id = r.order_id
                    {FX_JOIN}
                    WHERE o.country_code = 'MX'
                      AND o.created_at >= CURRENT_DATE - interval '30 days'
                      AND o.created_at < CURRENT_DATE
                    GROUP BY 1 ORDER BY refund_usd DESC
                """,
                "caliber": ["仅墨西哥", "金额折算 USD", "滚动 30 天，排除今日"],
            },
        ],
        "canvas": {
            "filters": {"allowed": ["date"]},
            "components": [
                {"id": "k1", "type": "metric_card", "title": "退款额 (USD)", "span": 6,
                 "field": "refund_usd", "display": {"unit": "currency", "precision": 0}},
                {"id": "k2", "type": "metric_card", "title": "退款率 %", "span": 6, "field": "refund_rate_pct"},
                {"id": "b1", "type": "bar_chart", "title": "退款原因分布", "span": 12,
                 "x": {"field": "reason"}, "series": [{"field": "refund_usd", "name": "退款额"}]},
                {"id": "x1", "type": "text_block", "span": 12,
                 "content": "口径：仅墨西哥市场；金额按订单日汇率折算 USD；退款率分母为未取消订单量；滚动 30 天，排除今日。"},
            ],
            "bind": {"k1": 0, "k2": 0, "b1": 1, "x1": None},
        },
    },
]


def main() -> None:
    warehouse = PostgresDataWarehouse()
    files = LocalVolumeFileStore()
    maker = get_sessionmaker()

    def audit_hook(identity: str, sql: str, meta: dict) -> None:
        with maker() as s:
            s.add(AuditLog(
                actor_user_id=None, action="seed.source.execute",
                object_type="source", detail={"identity": identity, "sql": sql, **meta},
            ))
            s.commit()

    gateway = QueryGateway(
        dsn_for={"draft": warehouse.dsn_for("draft"), "publisher": warehouse.dsn_for("publisher")},
        audit_hook=audit_hook,
    )

    with maker() as session:
        for spec in DASHBOARDS:
            ws = session.query(Workspace).filter_by(slug=spec["workspace"]).one()
            existing = (
                session.query(Dashboard).filter_by(workspace_id=ws.id, title=spec["title"]).first()
            )
            if existing:
                print(f"  跳过已存在的看板: {spec['title']}")
                continue

            source_ids: dict[str, int] = {}
            source_meta: dict[int, dict] = {}
            for idx, src in enumerate(spec["sources"]):
                result = gateway.execute(
                    identity="draft", sql=src["sql"],
                    allowed_objects=ALL_DATASETS, preview_rows=10000,
                )
                payload = json.dumps(
                    {"columns": result.columns, "rows": [list(r) for r in result.rows],
                     "row_count": result.row_count, "truncated": result.truncated},
                    ensure_ascii=False, default=str,
                ).encode()
                key = f"sources/preset-{spec['title']}-{idx}.json"
                meta = files.put(key, payload)
                file_ref = FileRef(
                    kind="source_result", storage_key=meta.storage_key,
                    mime="application/json", size_bytes=meta.size_bytes,
                    sha256=meta.sha256, workspace_id=ws.id,
                )
                session.add(file_ref)
                session.flush()
                source = Source(
                    workspace_id=ws.id, title=src["title"], sql_text=result.normalized_sql,
                    caliber_notes={"notes": src["caliber"]},
                    col_schema=result.columns, row_count=result.row_count,
                    result_file_id=file_ref.id, status="active",
                    created_by=1, semantic_refs={},
                )
                session.add(source)
                session.flush()
                # Commit per source: the audit_hook writes through its own
                # session during the NEXT gateway.execute — an open write
                # transaction here would hold the SQLite lock and deadlock it.
                session.commit()
                source_ids[str(idx)] = source.id
                source_meta[source.id] = {"row_count": result.row_count}
                print(f"  Source「{src['title']}」: {result.row_count} 行, {result.execution_ms}ms")

            # Build canvas with real source bindings.
            bind = spec["canvas"]["bind"]
            components = []
            for comp in spec["canvas"]["components"]:
                comp = dict(comp)
                src_idx = bind.get(comp["id"])
                if src_idx is not None:
                    comp["source_id"] = str(source_ids[str(src_idx)])
                components.append(comp)
            canvas = Canvas.model_validate({
                "schema_version": "1.0",
                "title": spec["title"],
                "filters": spec["canvas"]["filters"],
                "layout": {"grid_cols": 12, "order": [c["id"] for c in components]},
                "components": components,
            })
            dashboard = Dashboard(
                workspace_id=ws.id, title=spec["title"],
                status="published", created_by=1,
            )
            session.add(dashboard)
            session.flush()
            version = DashboardVersion(
                dashboard_id=dashboard.id, revision=1,
                canvas_json=canvas.model_dump(),
                source_snapshot={
                    sid: {"created_by": 1, "task_id": None, "semantic_version": "1"}
                    for sid in source_ids.values()
                },
                change_summary="预置看板（种子生成）", created_by=1,
            )
            session.add(version)
            session.flush()
            dashboard.current_version_id = version.id
            session.flush()
            session.commit()
            print(f"✅ 看板「{spec['title']}」已创建 (dashboard={dashboard.id}, version=1)")
        session.commit()

    with maker() as s:
        print(f"共 {s.query(Dashboard).count()} 个看板, {s.query(Source).count()} 个 Source")


if __name__ == "__main__":
    main()
