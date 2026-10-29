"""Dashboard tools: propose_dashboard_patch, validate_dashboard_patch.

propose writes a candidate patch row bound to the dashboard's CURRENT
revision; apply happens in the API (atomic, revalidates base_revision).
"""

from __future__ import annotations

from agent_adapter import Tool, ToolContext, ToolError
from dashboard_schema.patch import Patch
from t2d_db.models import Dashboard, DashboardPatch, DashboardVersion, Source


def build_dashboard_tools(ctx: ToolContext, deps) -> list[Tool]:
    async def propose_dashboard_patch(c: ToolContext, args: dict) -> dict:
        dashboard_id = args.get("dashboard_id")
        operations = args.get("operations", [])
        change_summary = args.get("change_summary", "")
        if not operations:
            raise ToolError("bad_arguments", "operations 不能为空", retryable=True)

        with deps.sessionmaker() as s:
            dashboard = s.get(Dashboard, int(dashboard_id)) if dashboard_id else None
            if dashboard is None or dashboard.workspace_id != c.workspace_id:
                raise ToolError("not_found", f"看板不存在或无权访问: {dashboard_id}")
            current = (
                s.get(DashboardVersion, dashboard.current_version_id)
                if dashboard.current_version_id else None
            )
            base_revision = current.revision if current else 0
            base_canvas = current.canvas_json if current else {
                "schema_version": "1.0", "title": dashboard.title,
                "filters": {"allowed": [], "defaults": {}},
                "layout": {"grid_cols": 12, "order": []}, "components": [],
            }

            # Structural validation before persisting the candidate.
            patch = Patch.model_validate({
                "base_revision": base_revision,
                "operations": operations,
                "change_summary": change_summary,
            })
            from dashboard_schema import apply_patch, summarize_changes
            from dashboard_schema.canvas import Canvas

            base = Canvas.model_validate(base_canvas)
            try:
                after = apply_patch(base, patch)
            except ValueError as exc:
                raise ToolError("invalid_patch", f"Patch 结构无效: {exc}", retryable=True)

            # Field/permission validation against real sources of this workspace.
            sources_meta = {
                str(row.id): {"workspace_id": row.workspace_id, "col_schema": row.col_schema}
                for row in s.query(Source).filter_by(workspace_id=c.workspace_id).all()
            }
            from dashboard_schema import validate_canvas

            errors = validate_canvas(after, sources=sources_meta, workspace_id=c.workspace_id)
            if errors:
                return {
                    "status": "invalid",
                    "errors": errors,
                    "_summary": f"Patch 校验失败: {errors[0]['code']}",
                }

            diff = summarize_changes(base, after, patch)
            row = DashboardPatch(
                dashboard_id=dashboard.id, base_revision=base_revision,
                patch_json=patch.model_dump(), diff_summary=diff,
                status="validated", proposed_by=c.user_id, task_id=c.task_id,
            )
            s.add(row)
            s.commit()
            return {
                "patch_id": row.id, "status": "validated",
                "base_revision": base_revision,
                "diff_summary": diff,
                "preview_canvas": after.model_dump(),
                "_summary": f"候选变更已生成: {diff}",
            }

    async def validate_dashboard_patch(c: ToolContext, args: dict) -> dict:
        patch_id = args.get("patch_id")
        with deps.sessionmaker() as s:
            row = s.get(DashboardPatch, int(patch_id)) if patch_id else None
            if row is None:
                raise ToolError("not_found", f"patch 不存在: {patch_id}")
            dashboard = s.get(Dashboard, row.dashboard_id)
            if dashboard is None or dashboard.workspace_id != c.workspace_id:
                raise ToolError("permission_denied", "无权查看该看板的变更")
            current = (
                s.get(DashboardVersion, dashboard.current_version_id)
                if dashboard.current_version_id else None
            )
            current_revision = current.revision if current else 0
            conflict = row.base_revision != current_revision
            return {
                "valid": not conflict and row.status == "validated",
                "checks": {
                    "structure": True,
                    "base_revision": {"patch": row.base_revision,
                                      "current": current_revision,
                                      "conflict": conflict},
                    "status": row.status,
                },
                "_summary": "冲突，需重新生成" if conflict else "校验通过",
            }

    return [
        Tool(
            name="propose_dashboard_patch",
            description="生成看板候选变更（组件增删改/布局/标题/筛选器），返回预览与 diff。",
            parameters={
                "type": "object",
                "properties": {
                    "dashboard_id": {"type": "integer"},
                    "operations": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "op": {"type": "string",
                                       "enum": ["add_component", "update_component",
                                                "remove_component", "set_layout",
                                                "set_title", "set_filters"]},
                                "target": {"type": "string", "description": "组件 id（组件操作必填）"},
                                "value": {"type": "object", "description": "操作内容"},
                            },
                            "required": ["op", "value"],
                        },
                    },
                    "change_summary": {"type": "string"},
                },
                "required": ["dashboard_id", "operations"],
            },
            handler=propose_dashboard_patch,
        ),
        Tool(
            name="validate_dashboard_patch",
            description="校验候选变更（结构/字段/base_revision 冲突）。",
            parameters={
                "type": "object",
                "properties": {"patch_id": {"type": "integer"}},
                "required": ["patch_id"],
            },
            handler=validate_dashboard_patch,
        ),
    ]
