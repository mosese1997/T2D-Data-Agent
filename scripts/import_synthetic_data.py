#!/usr/bin/env python3
"""Import synthetic CSVs into the business Postgres via fast COPY.

Applies schema_business.sql first (idempotent), then streams every CSV with
psycopg's COPY (never through the ORM), then creates indexes and ANALYZEs.
"""

from __future__ import annotations

import argparse
import os

import psycopg

TABLES = [
    # (csv name, table name, columns)
    ("dim_country", "dim_country", ["country_code", "country_name", "currency", "business_timezone"]),
    ("dim_city", "dim_city", ["city_id", "city_name", "country_code"]),
    ("dim_category", "dim_category", ["category_id", "category_name", "parent_category"]),
    ("dim_channel", "dim_channel", ["channel_id", "channel_name"]),
    ("dim_product", "dim_product", ["product_id", "product_name", "category_id", "price"]),
    ("fx_rates", "fx_rates", ["currency", "rate_date", "rate_to_usd"]),
    ("orders", "orders", ["order_id", "user_id", "country_code", "city_id", "channel_id",
                          "created_at", "status", "currency", "fx_date"]),
    ("order_items", "order_items", ["item_id", "order_id", "product_id", "quantity",
                                    "unit_price", "line_amount"]),
    ("refunds", "refunds", ["refund_id", "order_id", "refunded_at", "refund_amount", "reason"]),
    ("fulfillment_events", "fulfillment_events", ["event_id", "order_id", "event_type",
                                                  "occurred_at", "distance_km"]),
]


def dsn_from_env() -> str:
    return (
        f"host={os.environ.get('DEMO_PG_HOST', 'localhost')} "
        f"port={os.environ.get('DEMO_PG_PORT', '5434')} "
        f"dbname={os.environ.get('DEMO_PG_DATABASE', 't2d_biz')} "
        f"user={os.environ.get('DEMO_PG_USER', 't2d')} "
        f"password={os.environ.get('DEMO_PG_PASSWORD', 't2d-demo-only')}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", default="data/synthetic")
    parser.add_argument("--schema", default=os.path.join(os.path.dirname(__file__), "schema_business.sql"))
    parser.add_argument("--recreate", action="store_true",
                        help="先 DROP 全部业务表再重建（演示数据可随时重灌）")
    args = parser.parse_args()

    dsn = dsn_from_env()
    with psycopg.connect(dsn) as conn:
        if args.recreate:
            print("重建业务表...")
            conn.execute("""
                DROP TABLE IF EXISTS fulfillment_events, refunds, order_items, orders,
                    fx_rates, dim_product, dim_channel, dim_category, dim_city, dim_country CASCADE
            """)
        print("应用 schema...")
        with open(args.schema, encoding="utf-8") as f:
            conn.execute(f.read())

        for csv_name, table, columns in TABLES:
            path = os.path.join(args.dir, f"{csv_name}.csv")
            if not os.path.exists(path):
                raise SystemExit(f"缺少 {path}（先跑 gen_synthetic_data.py）")
            print(f"  导入 {table} ...", end=" ", flush=True)
            with open(path, encoding="utf-8") as f:
                with conn.cursor() as cur:
                    col_list = ", ".join(columns)
                    # psycopg3 streaming COPY: chunked writes, never whole-file.
                    with cur.copy(
                        f"COPY {table} ({col_list}) FROM STDIN WITH (FORMAT csv, HEADER true)"
                    ) as cp:
                        while True:
                            chunk = f.read(1024 * 1024)
                            if not chunk:
                                break
                            cp.write(chunk)
            count = conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            print(f"{count:,} rows")

        conn.execute("ANALYZE")
    print("✅ 导入完成")


if __name__ == "__main__":
    main()
