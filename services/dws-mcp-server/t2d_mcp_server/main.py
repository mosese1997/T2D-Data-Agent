"""t2d DWS MCP server — the data tools over MCP, governance built in.

Design (evolution plan E1):
- The 1.0 tool HANDLERS are reused verbatim: each MCP tool function below
  calls the same build_tools_for() handler with the same query-gateway
  governance. The MCP layer is a thin protocol adapter.
- Identity: X-T2D-* headers → context_from_headers() → server-verified
  ToolContext (see context.py). The model sees only the typed tool
  signatures — no identity fields, same invariant as 1.0.
- Signatures are explicit typed functions (the SDK derives JSON schemas
  from them); they mirror the 1.0 tool schemas.

Run: python -m t2d_mcp_server.main  (streamable-http on :9100)
"""

from __future__ import annotations

import os

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.context import Context

from agent_adapter import ToolContext, ToolError
from t2d_worker.deps import build_deps
from t2d_worker.tools import build_tools_for

from .context import context_from_headers

PORT = int(os.environ.get("T2D_MCP_PORT", "9100"))

server = MCPServer(name="t2d-dws")
deps = build_deps()

# The 1.0 toolset — handlers are the single source of behavior; the MCP
# functions below only adapt signatures + identity resolution.
_query_tools = {t.name: t for t in build_tools_for(
    "query",
    ToolContext(task_id=0, user_id=0, workspace_id=0, role="analyst", datasets=[]),
    deps,
)}


def _jsonable(value):
    """DB values (Decimal/datetime) → JSON-safe (same as the runner's)."""
    import json
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


async def _call(tool_name: str, ctx: Context, args: dict) -> dict:
    """Shared dispatch: verify identity from headers → run the 1.0 handler.

    ToolError from EITHER identity verification or the handler itself is
    returned as a structured payload — the SDK must never wrap it into a
    generic "Error executing tool" (the model needs the error code to
    repair its SQL).
    """
    tool = _query_tools[tool_name]
    try:
        t2d_ctx: ToolContext = context_from_headers(ctx.headers or {})
        result = await tool.handler(t2d_ctx, args)
    except ToolError as exc:
        return _jsonable(exc.as_payload())
    payload = {k: v for k, v in result.items() if k != "_summary"}
    return _jsonable(payload)


@server.tool()
async def search_semantics(query: str, ctx: Context,
                          top_k: int = 5, kind: str = "all") -> dict:
    """按自然语言检索相关指标、术语与维度。先调用它确定 metric_key。"""
    return await _call("search_semantics", ctx,
                       {"query": query, "top_k": top_k, "kind": kind})


@server.tool()
async def get_semantic_definition(keys: list[str], ctx: Context) -> dict:
    """获取指标的权威定义（表达式/口径/维度/关联规则/版本）。"""
    return await _call("get_semantic_definition", ctx, {"keys": keys})


@server.tool()
async def get_authorized_schema(ctx: Context, datasets: list[str] | None = None) -> dict:
    """获取当前业务空间授权数据集的表结构（列名/类型/注释）。"""
    return await _call("get_authorized_schema", ctx,
                       {"datasets": datasets} if datasets else {})


@server.tool()
async def validate_query(sql: str, ctx: Context) -> dict:
    """校验 SQL（单语句/只读/授权对象/禁用函数）。"""
    return await _call("validate_query", ctx, {"sql": sql})


@server.tool()
async def execute_query(sql: str, source_title: str, ctx: Context,
                        caliber_notes: list[str] | None = None,
                        semantic_refs: list[str] | None = None) -> dict:
    """执行授权范围内的只读查询并保存为 Source（内置完整校验与修复错误返回）。"""
    args: dict = {"sql": sql, "source_title": source_title}
    if caliber_notes:
        args["caliber_notes"] = caliber_notes
    if semantic_refs:
        args["semantic_refs"] = semantic_refs
    return await _call("execute_query", ctx, args)


@server.tool()
async def get_result_metadata(source_id: int, ctx: Context) -> dict:
    """读取已保存 Source 的元数据（SQL/列结构/行数/口径）。"""
    return await _call("get_result_metadata", ctx, {"source_id": source_id})


def main() -> None:
    print(f"[t2d-mcp-server] {len(_query_tools)} query tools live on :{PORT}",
          flush=True)
    server.run(transport="streamable-http", host="0.0.0.0", port=PORT)


if __name__ == "__main__":
    main()
