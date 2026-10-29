"""Caliber (口径) rules — the special cases the task book calls out (§8).

These do NOT silently patch SQL. They produce:
- canonical time-range SQL fragments (complete natural weeks vs rolling
  7 days, business timezone, excluding today), and
- human-readable caliber notes attached to sources, so every number on a
  dashboard carries its 口径.
"""

from __future__ import annotations

from datetime import date, timedelta

# Business timezone per dataset lives in datasets.yaml; the demo warehouse
# stores timestamps in UTC and the semantic layer declares the business tz
# used for day bucketing.
DEFAULT_BUSINESS_TZ = "America/Bogota"


class ComparisonError(Exception):
    """Raised when a comparison cannot be computed honestly (e.g. zero
    denominator) — callers must surface "—" instead of a fabricated number."""


def time_range_sql(
    *,
    time_field: str,
    period: str,
    anchor: date | None = None,
    business_tz: str = DEFAULT_BUSINESS_TZ,
    exclude_today: bool = True,
) -> tuple[str, list[str]]:
    """Return (sql_fragment, notes) for a named period.

    period: last_natural_week | last_7_days | last_30_days | month_to_date
    Complete natural weeks start Monday; rolling windows are exact.
    """
    anchor = anchor or date.today()
    notes: list[str] = []

    if period == "last_natural_week":
        # Most recent COMPLETE natural week (Monday start), excluding today's
        # partial data.
        days_since_monday = anchor.weekday()
        this_monday = anchor - timedelta(days=days_since_monday)
        last_sunday = this_monday - timedelta(days=1)
        last_monday = last_sunday - timedelta(days=6)
        sql = (
            f"({time_field} >= '{last_monday.isoformat()}'::timestamp "
            f"AND {time_field} < '{(last_sunday + timedelta(days=1)).isoformat()}'::timestamp)"
        )
        notes.append(f"完整自然周（周一起始）: {last_monday} ~ {last_sunday}")
    elif period == "last_7_days":
        end = anchor if not exclude_today else anchor - timedelta(days=1)
        start = end - timedelta(days=6)
        sql = (
            f"({time_field} >= '{start.isoformat()}'::timestamp "
            f"AND {time_field} < '{(end + timedelta(days=1)).isoformat()}'::timestamp)"
        )
        notes.append(f"滚动 7 天: {start} ~ {end}")
    elif period == "last_30_days":
        end = anchor if not exclude_today else anchor - timedelta(days=1)
        start = end - timedelta(days=29)
        sql = (
            f"({time_field} >= '{start.isoformat()}'::timestamp "
            f"AND {time_field} < '{(end + timedelta(days=1)).isoformat()}'::timestamp)"
        )
        notes.append(f"滚动 30 天: {start} ~ {end}")
    elif period == "month_to_date":
        first = anchor.replace(day=1)
        end = anchor if not exclude_today else anchor - timedelta(days=1)
        sql = (
            f"({time_field} >= '{first.isoformat()}'::timestamp "
            f"AND {time_field} < '{(end + timedelta(days=1)).isoformat()}'::timestamp)"
        )
        notes.append(f"本月至今: {first} ~ {end}")
    else:
        raise ValueError(f"未知时间口径: {period}")

    if exclude_today:
        notes.append("排除今日（数据不完整）")
    notes.append(f"业务时区 {business_tz}（日期边界按此时区计算）")
    return sql, notes


def caliber_notes_for(metric, *, period: str, comparison: str | None = None) -> list[str]:
    """Assemble the caliber notes shown next to a metric."""
    notes: list[str] = []
    if metric.exclusions:
        notes.append("排除条件: " + "；".join(metric.exclusions))
    if metric.currency_policy == "usd_fixed":
        notes.append("金额按订单日汇率折算为 USD")
    elif metric.currency_policy == "local":
        notes.append("金额为当地币种，跨国家汇总前需按订单日汇率折算")
    if metric.grain == "item":
        notes.append("注意：订单-明细关联会产生行扇出，计数类指标须按订单键去重")
    if comparison in ("wow", "dod"):
        notes.append(f"对比口径: {'环比上周' if comparison == 'wow' else '环比前一日'}；"
                     "分母为零时显示「—」，不显示无穷大")
    return notes


def dedup_count_sql(dataset_key: str, grain: str) -> str:
    """COUNT that survives order→item fan-out."""
    if grain == "item":
        return f"COUNT(DISTINCT {dataset_key})"
    return f"COUNT({dataset_key})"
