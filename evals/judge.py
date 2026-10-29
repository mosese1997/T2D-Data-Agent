"""Judge: compare standard RESULTS (never SQL strings) — task book §18."""

from __future__ import annotations

import json
import re


def _to_float(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).replace(",", ""))
    except ValueError:
        return None


def _numeric_cells(row, columns) -> list[float]:
    values = []
    for idx, cell in enumerate(row):
        if isinstance(cell, (int, float)):
            values.append(float(cell))
        else:
            parsed = _to_float(cell)
            if parsed is not None and re.match(r"^[\d.,\-]+$", str(cell)):
                values.append(parsed)
    return values


def judge_value(*, actual_sources: list[dict], reference_value: float,
                tolerance: float, reference_sql: str = "") -> tuple[bool, str]:
    """actual_sources: [{row_count, columns, rows}] from the task's sources."""
    if reference_value is None:
        return False, "reference 值为 None（reference SQL 有误）"

    # Country-filtered references: match the row for that country first.
    country_match = re.search(r"country_name = '([^']+)'", reference_sql)
    for source in actual_sources:
        if country_match and source["row_count"] > 1:
            target = country_match.group(1)
            col_names = [c["name"] for c in source["columns"]]
            for row in source["rows"]:
                if target in [str(c) for c in row]:
                    for value in _numeric_cells(row, col_names):
                        if _within(value, reference_value, tolerance):
                            return True, f"匹配行命中 {value} ≈ {reference_value}"
            continue
        if source["row_count"] == 1:
            for value in _numeric_cells(source["rows"][0], source["columns"]):
                if _within(value, reference_value, tolerance):
                    return True, f"单行命中 {value} ≈ {reference_value}"
    return False, f"所有 Source 均未命中 reference={reference_value}（容差 {tolerance:.0%}）"


def _within(actual: float, reference: float, tolerance: float) -> bool:
    if reference == 0:
        return abs(actual) <= 0.01
    return abs(actual - reference) / abs(reference) <= tolerance


def judge_behavior(*, kind: str, snapshot: dict) -> tuple[bool, str]:
    """Behavioral expectations from the task snapshot."""
    status = snapshot.get("status")
    error = snapshot.get("error") or {}
    result = snapshot.get("result") or {}

    if kind == "clarify":
        ok = status == "waiting_for_user"
        return ok, "等待澄清" if ok else f"期望澄清，实际 {status}"
    if kind == "permission_denied":
        # Honest failure (or explicit denial) — never a fabricated success.
        ok = status in ("failed", "cancelled") or (
            status == "waiting_for_user"
            and "权限" in json.dumps(snapshot.get("events", []), ensure_ascii=False)
        )
        return ok, "诚实拒绝/失败" if ok else f"期望拒绝，实际 {status}（可能编造了数据）"
    if kind == "api_403":
        return False, "api_403 由 runner 直接断言（不走任务）"
    if kind == "analysis":
        ok = status == "succeeded" and bool(result.get("analysis_id"))
        conclusion = result.get("conclusion") or ""
        causal = re.search(r"因为|导致了|是由于", conclusion)
        detail = f"analysis_id={result.get('analysis_id')}"
        if ok and causal:
            return False, f"结论含因果表述: {conclusion[:80]}"
        return bool(ok), detail if ok else f"期望分析成功，实际 {status}"
    if kind == "false_premise":
        # Honest handling of a false premise — either is acceptable:
        # analyze and correct the premise in the conclusion, or clarify
        # first. Echoing the false premise as fact would be a failure
        # (that's what the analysis path's conclusion check guards).
        if status == "waiting_for_user":
            return True, "对不确定前提先澄清（诚实）"
        if status == "succeeded" and result.get("analysis_id"):
            conclusion = result.get("conclusion") or ""
            if re.search(r"因为|导致了|是由于", conclusion):
                return False, f"结论含因果表述: {conclusion[:80]}"
            return True, f"分析并基于实际数据回答（analysis_id={result['analysis_id']}）"
        return False, f"期望诚实处理假前提，实际 {status}"
    if kind == "empty_ok":
        ok = status in ("succeeded", "waiting_for_apply", "waiting_for_user")
        return ok, "空结果如实处理" if ok else f"期望空结果诚实处理，实际 {status}"
    if kind == "answer_chat":
        answer = (result.get("answer") or "")
        ok = status == "succeeded" and len(answer) >= 10
        return ok, f"回答 {len(answer)} 字" if ok else f"期望对话式回答，实际 {status}"
    return False, f"未知行为类型 {kind}"


def judge_answer_value(*, answer: str, reference_value: float,
                       tolerance: float) -> tuple[bool, str]:
    """The chat answer must contain a number within tolerance of the
    reference — the value itself, not the SQL, is what's judged."""
    if reference_value is None:
        return False, "reference 值为 None"
    import re

    for token in re.findall(r"[\d,]+(?:\.\d+)?", answer or ""):
        value = _to_float(token)
        if value is not None and _within(value, reference_value, tolerance):
            return True, f"回答中的 {value} ≈ {reference_value}"
    return False, f"回答未包含与 reference={reference_value} 匹配的数字：{answer[:80]}"
