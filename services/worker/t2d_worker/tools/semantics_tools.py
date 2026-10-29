"""Semantic tools: search_semantics, get_semantic_definition, get_authorized_schema.

All three bind to the ToolContext's workspace dataset whitelist — the model
never sees datasets the workspace isn't granted.
"""

from __future__ import annotations

from agent_adapter import Tool, ToolContext, ToolError


def build_semantics_tools(ctx: ToolContext, deps) -> list[Tool]:
    async def search_semantics(c: ToolContext, args: dict) -> dict:
        query = args.get("query", "").strip()
        if not query:
            raise ToolError("bad_arguments", "query 不能为空", retryable=True)
        top_k = min(int(args.get("top_k", 5)), 10)
        kind = args.get("kind", "all")
        hits = deps.retriever.search(query, top_k=top_k, kind=kind)
        return {
            "results": [
                {"kind": h.kind, "key": h.key, "name": h.name,
                 "score": h.score, "snippet": h.snippet}
                for h in hits
            ],
            "semantic_version": deps.registry.version,
            "_summary": f"命中 {len(hits)} 个语义对象",
        }

    async def get_semantic_definition(c: ToolContext, args: dict) -> dict:
        keys = args.get("keys", [])
        if not keys:
            raise ToolError("bad_arguments", "keys 不能为空", retryable=True)
        definitions = []
        for key in keys:
            metric = deps.registry.metric(key)
            if metric is None:
                continue  # unknown keys are silently absent — model sees the gap
            definitions.append({
                "metric_key": metric.metric_key, "name": metric.name,
                "description": metric.description, "expression": metric.expression,
                "base_dataset": metric.base_dataset, "grain": metric.grain,
                "time_field": metric.time_field, "exclusions": metric.exclusions,
                "currency_policy": metric.currency_policy,
                "fx_date_rule": metric.fx_date_rule,
                "available_dimensions": metric.available_dimensions,
                "allowed_joins": metric.allowed_joins,
                "version": metric.version, "status": metric.status,
            })
        if not definitions:
            raise ToolError("not_found", f"未找到指标: {keys}", retryable=True,
                            hint="用 search_semantics 先检索正确的 metric_key")
        return {"definitions": definitions,
                "_summary": f"返回 {len(definitions)} 个指标定义"}

    async def get_authorized_schema(c: ToolContext, args: dict) -> dict:
        requested = args.get("datasets") or sorted(c.datasets)
        # Hard intersection with the workspace grant — never trust the model's list.
        visible = [d for d in requested if d in c.datasets]
        if not visible:
            raise ToolError("permission_denied", "当前业务空间没有可用的授权数据集")
        schema = deps.warehouse.authorized_schema(visible)
        # Merge the semantic layer's column documentation (value domains,
        # mappings — e.g. dim_country stores ENGLISH names) over the raw DB
        # comments: the model needs value hints, not just column names.
        yaml_datasets = deps.registry.bundle.datasets
        for name, meta in schema.items():
            doc = yaml_datasets.get(name, {}).get("columns", {})
            for column in meta["columns"]:
                if column["name"] in doc:
                    column["comment"] = doc[column["name"]]
        return {"datasets": schema, "demo_mode": c.demo_mode,
                "_summary": f"返回 {len(schema)} 个数据集结构"}

    return [
        Tool(
            name="search_semantics",
            description="按自然语言检索相关指标、术语与维度。先调用它确定 metric_key。",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "用户的分析问题或关键词"},
                    "top_k": {"type": "integer", "description": "返回条数，默认 5，最大 10"},
                    "kind": {"type": "string", "enum": ["metric", "term", "all"],
                             "description": "限定检索对象类型，默认 all"},
                },
                "required": ["query"],
            },
            handler=search_semantics,
        ),
        Tool(
            name="get_semantic_definition",
            description="获取指标的权威定义（表达式/口径/维度/关联规则/版本）。",
            parameters={
                "type": "object",
                "properties": {
                    "keys": {"type": "array", "items": {"type": "string"},
                             "description": "metric_key 列表"},
                },
                "required": ["keys"],
            },
            handler=get_semantic_definition,
        ),
        Tool(
            name="get_authorized_schema",
            description="获取当前业务空间授权数据集的表结构（列名/类型/注释）。",
            parameters={
                "type": "object",
                "properties": {
                    "datasets": {"type": "array", "items": {"type": "string"},
                                 "description": "数据集名列表；缺省返回全部授权集"},
                },
                "required": [],
            },
            handler=get_authorized_schema,
        ),
    ]
