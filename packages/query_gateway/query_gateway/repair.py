"""Finite repair loop (task book §10: at most 2 repairs, never silent).

Error classification → structured feedback the query sub-agent can act on.
The loop itself lives in the sub-agent; this module turns execution errors
into repair prompts with the relevant schema fragment attached.
"""

from __future__ import annotations

from .gateway import QueryCancelled, QueryRejected

MAX_REPAIRS = 2

# error code -> (category, repair hint)
_CATEGORIES = {
    "parse_error": ("syntax", "检查 SQL 语法，只生成一条 SELECT 语句"),
    "multi_statement": ("syntax", "只允许一条语句，请拆分或合并逻辑"),
    "not_select": ("syntax", "只允许 SELECT 查询"),
    "mutating_statement": ("syntax", "禁止任何数据修改语句"),
    "object_not_authorized": ("schema", "改用授权数据集内的表；用 get_authorized_schema 查看可用对象"),
    "system_object": ("permission", "禁止访问系统目录"),
    "forbidden_function": ("permission", "移除禁用函数，改用标准 SQL 表达式"),
    "unknown_column": ("schema", "用 get_authorized_schema 核对列名"),
    "datatype_mismatch": ("type", "检查比较与聚合的类型转换"),
    "timeout": ("performance", "缩小时间范围或减少扫描量，必要时先建汇总再查询"),
    "result_too_large": ("performance", "增加聚合粒度或收紧过滤条件"),
}


def classify(error: Exception) -> tuple[str, str]:
    """Return (category, repair_hint) for an execution/validation error."""
    if isinstance(error, QueryCancelled):
        return ("cancelled", "任务已取消")
    if isinstance(error, QueryRejected):
        entry = _CATEGORIES.get(error.code)
        if entry:
            return entry
        return ("unknown", error.message)
    # psycopg errors: look at pg codes for common cases.
    message = str(error)
    lowered = message.lower()
    if "does not exist" in lowered and "column" in lowered:
        return _CATEGORIES["unknown_column"]
    if "does not exist" in lowered:
        return _CATEGORIES["object_not_authorized"]
    if "canceling statement due to statement timeout" in lowered:
        return _CATEGORIES["timeout"]
    if "datatype mismatch" in lowered or "invalid input syntax" in lowered:
        return _CATEGORIES["datatype_mismatch"]
    return ("unknown", message[:200])


def build_repair_prompt(
    *,
    sql: str,
    category: str,
    hint: str,
    schema_fragment: str,
    attempt: int,
) -> str:
    return (
        f"上一次查询失败（第 {attempt}/{MAX_REPAIRS} 次修复）。\n"
        f"失败类别: {category}\n原因与建议: {hint}\n"
        f"相关表结构:\n{schema_fragment}\n"
        f"失败的 SQL:\n{sql}\n"
        f"请修正后重新给出完整 SQL。若无法修复，请明确说明原因，不要猜测。"
    )
