"""Canvas validation: structure, fields, permissions.

validate_canvas checks a canvas against the sources it may reference:
- every data component's source_id must exist in `sources` (id -> metadata
  with workspace_id, col_schema, owner_id);
- the source must belong to the same workspace as the dashboard;
- referenced fields (field / x.field / series[].field / columns) must exist
  in the source's col_schema;
- filter components may only reference filters.allowed keys.

`sources` maps source_id -> {"workspace_id": int, "col_schema": [...],
"created_by": int}. The caller (API/worker) builds it from the DB —
permission data never comes from the canvas JSON itself.
"""

from __future__ import annotations

from typing import Any

from .canvas import Canvas, ComponentType


class ValidationError(Exception):
    def __init__(self, errors: list[dict[str, str]]):
        super().__init__("; ".join(e["message"] for e in errors))
        self.errors = errors


def _fields_of(component) -> list[str]:
    fields: list[str] = []
    if component.field:
        fields.append(component.field)
    if component.x and component.x.get("field"):
        fields.append(component.x["field"])
    for series in component.series:
        fields.append(series.field)
        if series.split_by:
            fields.append(series.split_by)
    if component.columns:
        fields.extend(component.columns)
    return fields


def validate_canvas(
    canvas: Canvas,
    *,
    sources: dict[str, dict[str, Any]],
    workspace_id: int,
    schema_version_supported: str = "1.0",
) -> list[dict[str, str]]:
    """Return a list of errors ([] = valid). Raises nothing."""
    errors: list[dict[str, str]] = []

    if canvas.schema_version != schema_version_supported:
        errors.append({
            "code": "unsupported_schema",
            "message": f"schema_version {canvas.schema_version} 不受支持"
                       f"（当前支持 {schema_version_supported}）",
        })

    seen_ids: set[str] = set()
    for comp in canvas.components:
        if comp.id in seen_ids:
            errors.append({"code": "duplicate_id", "message": f"组件 id 重复: {comp.id}"})
        seen_ids.add(comp.id)

        if comp.type == ComponentType.FILTER:
            if comp.filter_key and comp.filter_key not in canvas.filters.allowed:
                errors.append({
                    "code": "filter_not_allowed",
                    "message": f"筛选器键 {comp.filter_key} 不在允许列表",
                })
            continue

        if comp.type == ComponentType.TEXT_BLOCK:
            continue

        # Data components need a valid, same-workspace source.
        if not comp.source_id:
            errors.append({
                "code": "missing_source",
                "message": f"组件 {comp.id} 缺少 source_id",
            })
            continue
        source = sources.get(comp.source_id)
        if source is None:
            errors.append({
                "code": "unknown_source",
                "message": f"组件 {comp.id} 引用不存在的 source: {comp.source_id}",
            })
            continue
        if source.get("workspace_id") != workspace_id:
            errors.append({
                "code": "source_workspace_mismatch",
                "message": f"组件 {comp.id} 的 source 不属于当前业务空间",
            })
            continue
        col_names = {c["name"] for c in source.get("col_schema", [])}
        for field in _fields_of(comp):
            if field not in col_names:
                errors.append({
                    "code": "unknown_field",
                    "message": f"组件 {comp.id} 引用 source 中不存在的字段: {field}",
                })

    order_ids = set(canvas.layout.order)
    missing = seen_ids - order_ids
    if missing:
        errors.append({
            "code": "layout_incomplete",
            "message": f"组件未纳入布局: {sorted(missing)}",
        })
    return errors
