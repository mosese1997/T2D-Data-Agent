"""Human-readable diff summaries for patch previews."""

from __future__ import annotations

from .canvas import Canvas
from .patch import Patch

_TYPE_LABELS = {
    "metric_card": "指标卡",
    "line_chart": "折线图",
    "bar_chart": "柱状图",
    "data_table": "表格",
    "text_block": "说明文字",
    "filter": "筛选器",
}


def summarize_changes(before: Canvas, after: Canvas, patch: Patch) -> str:
    """One-paragraph change summary shown in the preview dialog."""
    lines: list[str] = []
    if before.title != after.title:
        lines.append(f"标题改为「{after.title}」")
    before_ids = {c.id for c in before.components}
    after_ids = {c.id for c in after.components}
    for cid in after_ids - before_ids:
        comp = after.component_by_id(cid)
        label = _TYPE_LABELS.get(comp.type.value, comp.type.value) if comp else "组件"
        lines.append(f"新增{label}「{comp.title or cid}」" if comp else f"新增组件 {cid}")
    for cid in before_ids - after_ids:
        comp = before.component_by_id(cid)
        label = _TYPE_LABELS.get(comp.type.value, comp.type.value) if comp else "组件"
        lines.append(f"移除{label}「{comp.title or cid}」")
    for cid in before_ids & after_ids:
        b = before.component_by_id(cid)
        a = after.component_by_id(cid)
        if b and a and b.model_dump(exclude={"display"}) != a.model_dump(exclude={"display"}):
            lines.append(f"修改「{a.title or cid}」")
    if before.layout.order != after.layout.order:
        lines.append("调整布局顺序")
    if before.filters.defaults != after.filters.defaults:
        lines.append("调整默认筛选")
    if not lines:
        lines.append("无可见变更")
    return "；".join(lines) + "。"
