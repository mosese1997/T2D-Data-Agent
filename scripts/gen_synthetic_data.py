#!/usr/bin/env python3
"""Synthetic business data generator — reproducible (fixed seed + anchor date).

Covers the order/GMV/fulfillment domain (task book §8): 10 countries, 60
cities, 8 top / 24 sub categories, 5 channels, 200 products, 180 days of
orders with weekend peaks and a growth trend, refunds, fulfillment event
streams, and fx rates with deliberately missing days (to exercise the
"nearest prior rate" caliber rule).

Output: CSV files under --out, imported by import_synthetic_data.py (COPY).
"""

from __future__ import annotations

import argparse
import csv
import os
from datetime import date, datetime, timedelta

import numpy as np

COUNTRIES = [
    # code, name, currency, business_timezone, order weight
    ("MX", "Mexico", "MXN", "America/Mexico_City", 0.22),
    ("CO", "Colombia", "COP", "America/Bogota", 0.20),
    ("BR", "Brazil", "BRL", "America/Sao_Paulo", 0.18),
    ("AR", "Argentina", "ARS", "America/Argentina/Buenos_Aires", 0.10),
    ("CL", "Chile", "CLP", "America/Santiago", 0.08),
    ("PE", "Peru", "PEN", "America/Lima", 0.07),
    ("UY", "Uruguay", "UYU", "America/Montevideo", 0.05),
    ("EC", "Ecuador", "USD", "America/Guayaquil", 0.04),
    ("BO", "Bolivia", "BOB", "America/La_Paz", 0.03),
    ("PA", "Panama", "USD", "America/Panama", 0.03),
]

TOP_CATEGORIES = ["餐饮", "杂货", "药房", "电子", "服饰", "家居", "美妆", "宠物"]
SUBCATEGORIES = {
    "餐饮": ["正餐", "快餐", "甜点饮品"],
    "杂货": ["生鲜", "日用品", "饮料"],
    "药房": ["处方药", "保健品", "个护"],
    "电子": ["手机配件", "电脑配件", "智能家居"],
    "服饰": ["男装", "女装", "运动"],
    "家居": ["厨房", "收纳", "床品"],
    "美妆": ["护肤", "彩妆", "香水"],
    "宠物": ["宠物食品", "宠物用品", "宠物医疗"],
}

CHANNELS = ["app", "web", "marketplace", "pos", "phone"]

REFUND_REASONS = ["商品损坏", "送错商品", "未按时送达", "质量问题", "顾客改变主意", "少件/漏送"]

CITY_NAMES = {
    "MX": ["墨西哥城", "瓜达拉哈拉", "蒙特雷", "坎昆", "普埃布拉", "蒂华纳"],
    "CO": ["波哥大", "麦德林", "卡利", "巴兰基亚", "卡塔赫纳", "佩雷拉"],
    "BR": ["圣保罗", "里约热内卢", "巴西利亚", "萨尔瓦多", "累西腓", "阿雷格里港"],
    "AR": ["布宜诺斯艾利斯", "科尔多瓦", "罗萨里奥", "门多萨", "拉普拉塔", "图库曼"],
    "CL": ["圣地亚哥", "瓦尔帕莱索", "康塞普西翁", "安托法加斯塔", "比尼亚德尔马", "特木科"],
    "PE": ["利马", "阿雷基帕", "特鲁希略", "奇克拉约", "库斯科", "皮乌拉"],
    "UY": ["蒙得维的亚", "萨尔托", "派桑杜", "埃斯特角城", "罗恰", "杜布拉斯诺"],
    "EC": ["基多", "瓜亚基尔", "昆卡", "马查拉", "安巴托", "曼塔"],
    "BO": ["拉巴斯", "圣克鲁斯", "科恰班巴", "苏克雷", "奥鲁罗", "塔里哈"],
    "PA": ["巴拿马城", "圣地亚哥", "戴维", "科隆", "奇特雷", "佩诺诺梅"],
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--orders", type=int, default=300_000)
    parser.add_argument("--days", type=int, default=180)
    parser.add_argument("--anchor-date", type=str, default=None,
                        help="数据窗口的“今日”（默认今天）；固定它即可完全复现")
    parser.add_argument("--out", type=str, default="data/synthetic")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rng = np.random.default_rng(args.seed)
    anchor = date.fromisoformat(args.anchor_date) if args.anchor_date else date.today()
    # Window ends yesterday: today is always incomplete (exclude-today caliber).
    end = anchor - timedelta(days=1)
    start = end - timedelta(days=args.days - 1)
    dates = [start + timedelta(days=i) for i in range(args.days)]
    out = args.out
    os.makedirs(out, exist_ok=True)

    def write(name: str, header: list[str], rows) -> None:
        path = os.path.join(out, f"{name}.csv")
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(header)
            w.writerows(rows)
        print(f"  {name}.csv: {sum(1 for _ in open(path)) - 1:,} rows")

    # ── dims ────────────────────────────────────────────────────────
    print("生成维表...")
    write("dim_country", ["country_code", "country_name", "currency", "business_timezone"],
          [(c[0], c[1], c[2], c[3]) for c in COUNTRIES])

    cities = []
    city_id = 1
    for code, names in CITY_NAMES.items():
        for name in names:
            cities.append((city_id, name, code))
            city_id += 1
    write("dim_city", ["city_id", "city_name", "country_code"], cities)

    categories = []
    for top, subs in SUBCATEGORIES.items():
        for sub in subs:
            categories.append((f"{top}-{sub}", sub, top))
    write("dim_category", ["category_id", "category_name", "parent_category"], categories)

    write("dim_channel", ["channel_id", "channel_name"],
          [(i + 1, name) for i, name in enumerate(CHANNELS)])

    cat_ids = [c[0] for c in categories]
    products = []
    for pid in range(1, 201):
        cat = cat_ids[int(rng.integers(len(cat_ids)))]
        price = float(np.round(rng.lognormal(3.2, 0.7), 2))  # ~$2.5-$120
        products.append((pid, f"商品-{pid:03d}", cat, max(1.0, price)))
    write("dim_product", ["product_id", "product_name", "category_id", "price"], products)

    # ── fx rates (2 deliberately missing currency-days) ─────────────
    print("生成汇率（含 2 个缺失日，用于测试就近回退规则）...")
    fx_rows = []
    base_rates = {"MXN": 18.5, "COP": 3900.0, "BRL": 5.2, "ARS": 950.0, "CLP": 940.0,
                  "PEN": 3.75, "UYU": 40.0, "USD": 1.0, "BOB": 6.9}
    # Iterate UNIQUE currencies (USD is shared by EC and PA).
    for currency in sorted({c[2] for c in COUNTRIES}):
        base = base_rates[currency]
        drift = rng.normal(0, 0.004, size=args.days)
        walk = np.cumprod(1 + drift)
        for i, d in enumerate(dates):
            fx_rows.append((currency, d.isoformat(), round(base * walk[i], 8)))
    # Remove 2 (currency, date) pairs — orders on those days test the fallback.
    missing = [
        ("COP", dates[args.days // 3].isoformat()),
        ("MXN", dates[2 * args.days // 3].isoformat()),
    ]
    fx_rows = [r for r in fx_rows if (r[0], r[1]) not in missing]
    write("fx_rates", ["currency", "rate_date", "rate_to_usd"], fx_rows)
    print(f"  删除的汇率日: {missing}")

    # ── orders ──────────────────────────────────────────────────────
    print(f"生成订单（{args.orders:,} 单 / {args.days} 天）...")
    country_codes = np.array([c[0] for c in COUNTRIES])
    country_weights = np.array([c[4] for c in COUNTRIES])
    country_weights = country_weights / country_weights.sum()

    # Daily volume: growth trend × weekend peak.
    trend = np.linspace(0.85, 1.15, args.days)
    weekday = np.array([d.weekday() for d in dates])
    weekend = np.where(weekday >= 5, 1.3, 1.0)
    daily_weights = trend * weekend
    daily_weights /= daily_weights.sum()
    daily_counts = rng.multinomial(args.orders, daily_weights)

    order_country = np.concatenate([
        rng.choice(len(COUNTRIES), size=n, p=country_weights)
        for n in daily_counts
    ])
    # Shuffle so rows aren't grouped by day (also mixes ids vs time).
    rng.shuffle(order_country)

    order_day_idx = np.concatenate([np.full(n, i) for i, n in enumerate(daily_counts)])
    rng.shuffle(order_day_idx)
    order_dates = np.array(dates)[order_day_idx]

    seconds_in_day = rng.integers(0, 86400, size=args.orders)
    created = np.array([
        datetime(d.year, d.month, d.day) + timedelta(seconds=int(s))
        for d, s in zip(order_dates, seconds_in_day)
    ])

    status = np.where(rng.random(args.orders) < 0.03, "cancelled", "completed")
    user_ids = rng.integers(1, 60_001, size=args.orders)  # 60k buyers
    channel_ids = rng.choice(np.arange(1, 6), size=args.orders,
                             p=np.array([0.45, 0.20, 0.15, 0.12, 0.08]))

    # City per order: within the order's country.
    city_by_country = {c[0]: [ct for ct in cities if ct[2] == c[0]] for c in COUNTRIES}
    city_ids = np.empty(args.orders, dtype=int)
    for ci in range(len(COUNTRIES)):
        mask = order_country == ci
        options = np.array([ct[0] for ct in city_by_country[country_codes[ci]]])
        city_ids[mask] = rng.choice(options, size=mask.sum())

    orders_rows = []
    for i in range(args.orders):
        code = country_codes[order_country[i]]
        currency = next(c[2] for c in COUNTRIES if c[0] == code)
        orders_rows.append((
            i + 1, int(user_ids[i]), code, int(city_ids[i]), int(channel_ids[i]),
            created[i].isoformat(sep=" "), status[i], currency,
            order_dates[i].isoformat(),
        ))
    write("orders", ["order_id", "user_id", "country_code", "city_id", "channel_id",
                     "created_at", "status", "currency", "fx_date"], orders_rows)

    # ── order items (avg 2.2 per order) ─────────────────────────────
    print("生成订单明细...")
    n_items = rng.choice(np.arange(1, 6), size=args.orders,
                         p=np.array([0.30, 0.28, 0.22, 0.12, 0.08]))
    total_items = int(n_items.sum())
    item_order = np.repeat(np.arange(1, args.orders + 1), n_items)
    item_product = rng.integers(1, 201, size=total_items)
    product_price = {p[0]: p[3] for p in products}
    # 本地币定价：商品基准价是美元量级，按订单国币种因子放大，
    # 否则 COP/ARS 国家折回美元后 GMV 会被缩小几千倍（演示失真）。
    currency_factor = {"MXN": 18.5, "COP": 3900.0, "BRL": 5.2, "ARS": 950.0,
                       "CLP": 940.0, "PEN": 3.75, "UYU": 40.0, "USD": 1.0, "BOB": 6.9}
    order_country = {r[0]: r[2] for r in orders_rows}  # order_id -> country_code
    item_qty = rng.integers(1, 5, size=total_items)
    items_rows = []
    order_totals: dict[int, float] = {}
    item_id = 1
    for oid, pid, qty in zip(item_order, item_product, item_qty):
        factor = currency_factor[
            next(c[2] for c in COUNTRIES if c[0] == order_country[int(oid)])]
        price = round(product_price[int(pid)] * factor * float(rng.normal(1.0, 0.05)), 2)
        amount = round(price * int(qty), 2)
        items_rows.append((item_id, int(oid), int(pid), int(qty), price, amount))
        order_totals[int(oid)] = round(order_totals.get(int(oid), 0.0) + amount, 2)
        item_id += 1
    write("order_items", ["item_id", "order_id", "product_id", "quantity",
                          "unit_price", "line_amount"], items_rows)

    # ── refunds (3% of completed orders, partial amounts) ───────────
    print("生成退款...")
    completed_idx = np.where(status == "completed")[0]
    refunded = completed_idx[rng.random(len(completed_idx)) < 0.03]
    refunds_rows = []
    for r, rid in enumerate(refunded, start=1):
        order = orders_rows[int(rid)]
        total = order_totals.get(order[0], 100.0)
        refunds_rows.append((
            r, order[0],
            (created[int(rid)] + timedelta(days=int(rng.integers(1, 15)))).isoformat(sep=" "),
            round(float(rng.uniform(0.2, 1.0)) * total, 2),
            REFUND_REASONS[int(rng.integers(len(REFUND_REASONS)))],
        ))
    write("refunds", ["refund_id", "order_id", "refunded_at", "refund_amount", "reason"], refunds_rows)

    # ── fulfillment events (completed orders; recent ones in transit) ─
    print("生成履约事件流...")
    fe_rows = []
    event_id = 1
    for idx in completed_idx:
        order = orders_rows[int(idx)]
        oid, t0 = order[0], created[int(idx)]
        age_days = (end - order_dates[int(idx)]).days
        packed_at = t0 + timedelta(hours=float(rng.uniform(2, 8)))
        fe_rows.append((event_id, oid, "created", t0.isoformat(sep=" "), None)); event_id += 1
        fe_rows.append((event_id, oid, "packed", packed_at.isoformat(sep=" "), None)); event_id += 1
        if age_days < 1:
            continue  # too recent: still packing
        shipped_at = packed_at + timedelta(hours=float(rng.uniform(0.5, 4)))
        fe_rows.append((event_id, oid, "shipped", shipped_at.isoformat(sep=" "), None)); event_id += 1
        if rng.random() < 0.02:
            exc_at = shipped_at + timedelta(hours=float(rng.uniform(0.5, 20)))
            fe_rows.append((event_id, oid, "exception", exc_at.isoformat(sep=" "), None)); event_id += 1
        if age_days < 2:
            continue  # in transit
        # 92% within 48h (on_time_rate), rest up to 96h.
        hours = float(rng.uniform(0.5, 48) if rng.random() < 0.92 else rng.uniform(48, 96))
        delivered_at = shipped_at + timedelta(hours=hours)
        fe_rows.append((event_id, oid, "delivered", delivered_at.isoformat(sep=" "),
                        round(float(rng.uniform(3, 40)), 2))); event_id += 1
    write("fulfillment_events", ["event_id", "order_id", "event_type", "occurred_at", "distance_km"], fe_rows)

    print(f"\n✅ 生成完成: {out}/ （anchor={anchor} 窗口 {start} ~ {end}，seed={args.seed}）")


if __name__ == "__main__":
    main()
