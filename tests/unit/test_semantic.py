"""Unit tests: semantic layer (loader, caliber rules, retriever)."""

import os
from datetime import date

import pytest

from semantic import SemanticRetriever, caliber_notes_for, load_semantics, time_range_sql

CONFIG_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "config", "semantics")


@pytest.fixture(scope="module")
def registry():
    return load_semantics(CONFIG_DIR)


def test_loads_all_content(registry):
    assert len(registry.metrics) >= 10
    assert len(registry.terms) >= 5
    assert len(registry.join_rules) >= 5
    assert registry.version


def test_gmv_metric_shape(registry):
    gmv = registry.metric("gmv")
    assert gmv is not None
    assert gmv.currency_policy == "usd_fixed"
    assert gmv.grain == "item"
    assert "orders_to_items" in gmv.allowed_joins


def test_natural_week_range():
    anchor = date(2026, 10, 28)  # a Wednesday
    sql, notes = time_range_sql(time_field="o.created_at", period="last_natural_week", anchor=anchor)
    # Monday before last Sunday: 2026-10-19 ~ 2026-10-25
    assert "2026-10-19" in sql and "2026-10-26" in sql
    assert any("完整自然周" in n for n in notes)


def test_rolling_seven_excludes_today():
    anchor = date(2026, 10, 28)
    sql, notes = time_range_sql(time_field="o.created_at", period="last_7_days", anchor=anchor)
    # end = yesterday (10-27), window = 10-21 .. <10-28 (exclusive upper)
    assert "2026-10-21" in sql and "2026-10-28" in sql
    assert any("排除今日" in n for n in notes)


def test_unknown_period_rejected():
    with pytest.raises(ValueError):
        time_range_sql(time_field="x", period="whenever")


def test_caliber_notes(registry):
    gmv = registry.metric("gmv")
    notes = caliber_notes_for(gmv, period="last_natural_week", comparison="wow")
    assert any("排除条件" in n for n in notes)
    assert any("汇率" in n for n in notes)
    assert any("去重" in n for n in notes)  # item-grain fan-out warning


# Retrieval: the query passes if the expected metric OR a term that
# references it appears in top-3 (terms carry ref_metric pointers).
RETRIEVAL_CASES = [
    ("上周各国家GMV趋势", "gmv"),
    ("退款率是多少", "refund_rate"),
    ("配送时长", "fulfillment_duration"),
    ("销量", "item_count"),
    ("客单价", "avg_order_value"),
    ("订单取消的多吗", "cancel_rate"),
    ("gmv", "gmv"),
    ("履约距离", "fulfillment_distance"),
    ("活跃买家有多少", "active_buyers"),
    ("准时率", "on_time_rate"),
    ("交易额趋势", "gmv"),
    ("退款金额", "refund_amount"),
    ("每个用户几单", "orders_per_buyer"),
]


@pytest.mark.parametrize("query,expected", RETRIEVAL_CASES)
def test_retrieval_top3(registry, query, expected):
    retriever = SemanticRetriever(registry)
    hits = retriever.search(query, top_k=3)
    keys = [h.key for h in hits]
    refs = {
        t.term for t in registry.terms.values() if t.ref_metric == expected
    }
    assert set(keys) & ({expected} | refs), f"{query!r} -> {keys}, 期望 {expected}"
