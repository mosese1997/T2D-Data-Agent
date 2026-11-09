"""Query tools: validate_query, execute_query, get_result_metadata.

execute_query is the money path: gateway-validated SQL → business PG →
full result to FileStore (sha256) → FileRef + Source rows. The returned
source_id is what dashboard components bind to.
"""

from __future__ import annotations

import json
import time

from agent_adapter import Tool, ToolContext, ToolError
from query_gateway.gateway import QueryCancelled, QueryRejected
from t2d_db.models import FileRef, Source
from t2d_db.session import utcnow


def build_query_tools(ctx: ToolContext, deps, *, cancel_check=None) -> list[Tool]:
    async def validate_query(c: ToolContext, args: dict) -> dict:
        sql = args.get("sql", "")
        from query_gateway import validate_sql

        result = validate_sql(sql, allowed_objects=set(c.datasets))
        payload = {
            "valid": result.valid,
            "errors": result.errors,
            "warnings": result.warnings,
            "objects_referenced": result.objects_referenced,
            "_summary": "校验通过" if result.valid else f"校验失败: {result.errors[0]['code']}",
        }
        if result.normalized_sql:
            payload["normalized_sql"] = result.normalized_sql
        return payload

    async def execute_query(c: ToolContext, args: dict) -> dict:
        sql = args.get("sql", "")
        title = args.get("source_title") or "未命名查询"
        params = args.get("params") or {}
        if not sql.strip():
            raise ToolError("bad_arguments", "sql 不能为空", retryable=True)
        try:
            result = deps.gateway.execute(
                identity="draft", sql=sql,
                allowed_objects=set(c.datasets),
                params=params or None,
                cancel_check=cancel_check,
            )
        except QueryRejected as exc:
            raise ToolError(exc.code, exc.message, retryable=True,
                            hint="根据错误修正 SQL；对象不在授权范围时改用 get_authorized_schema 查看可用表")
        except QueryCancelled:
            raise ToolError("cancelled", "查询已随任务取消")

        # Persist: file → file_ref → source (short session per phase-2 lesson).
        payload = json.dumps(
            {"columns": result.columns, "rows": [list(r) for r in result.rows],
             "row_count": result.row_count, "truncated": result.truncated},
            ensure_ascii=False, default=str,
        ).encode()
        key = f"sources/task-{c.task_id}-{int(time.time() * 1000)}.json"
        meta = deps.files.put(key, payload)
        with deps.sessionmaker() as s:
            file_ref = FileRef(
                kind="source_result", storage_key=meta.storage_key,
                mime="application/json", size_bytes=meta.size_bytes,
                sha256=meta.sha256, workspace_id=c.workspace_id,
                created_by=c.user_id,
                task_id=c.task_id if c.task_id else None,
            )
            s.add(file_ref)
            s.flush()
            source = Source(
                workspace_id=c.workspace_id, title=title,
                sql_text=result.normalized_sql, params_json=params,
                col_schema=result.columns, row_count=result.row_count,
                result_file_id=file_ref.id, status="active",
                created_by=c.user_id,
                task_id=c.task_id if c.task_id else None,
                caliber_notes={"notes": args.get("caliber_notes", [])},
                semantic_refs={"refs": args.get("semantic_refs", []),
                               "semantic_version": deps.registry.version},
            )
            s.add(source)
            s.commit()
            source_id = source.id
        return {
            "source_id": source_id,
            "columns": result.columns,
            "preview_rows": [list(r) for r in result.rows[:10]],
            "row_count": result.row_count,
            "truncated": result.truncated,
            "execution_ms": result.execution_ms,
            "tables": result.objects_referenced,
            "_summary": (f"查询了 {('、'.join(result.objects_referenced))}"
                         f"（{result.row_count} 行）"
                         if result.objects_referenced
                         else f"执行成功，{result.row_count} 行"),
        }

    async def get_result_metadata(c: ToolContext, args: dict) -> dict:
        source_id = args.get("source_id")
        with deps.sessionmaker() as s:
            source = s.get(Source, int(source_id))
            if source is None or source.workspace_id != c.workspace_id:
                raise ToolError("not_found", f"source 不存在或无权访问: {source_id}")
            return {
                "source": {
                    "id": source.id, "title": source.title,
                    "sql": source.sql_text, "params": source.params_json,
                    "col_schema": source.col_schema, "row_count": source.row_count,
                    "caliber_notes": source.caliber_notes,
                    "semantic_refs": source.semantic_refs,
                    "created_at": source.created_at.isoformat(),
                },
                "freshness": source.created_at.isoformat(),
                "_summary": f"source {source.id}: {source.row_count} 行",
            }

    return [
        Tool(
            name="validate_query",
            description="校验 SQL（单条 SELECT/授权对象/禁用函数），执行前先校验。",
            parameters={
                "type": "object",
                "properties": {"sql": {"type": "string"}},
                "required": ["sql"],
            },
            handler=validate_query,
        ),
        Tool(
            name="execute_query",
            description="执行授权范围内的只读查询并保存为 Source。须先通过 validate_query。",
            parameters={
                "type": "object",
                "properties": {
                    "sql": {"type": "string"},
                    "source_title": {"type": "string", "description": "Source 标题（给用户看）"},
                    "caliber_notes": {"type": "array", "items": {"type": "string"},
                                      "description": "口径说明（排除条件/时区/汇率规则等）"},
                    "semantic_refs": {"type": "array", "items": {"type": "string"},
                                      "description": "使用的 metric_key 列表"},
                    "params": {"type": "object", "description": "查询参数（可选）"},
                },
                "required": ["sql", "source_title"],
            },
            handler=execute_query,
        ),
        Tool(
            name="get_result_metadata",
            description="读取已保存 Source 的元数据（SQL/列结构/行数/口径）。",
            parameters={
                "type": "object",
                "properties": {"source_id": {"type": "integer"}},
                "required": ["source_id"],
            },
            handler=get_result_metadata,
        ),
    ]
