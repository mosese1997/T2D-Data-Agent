"""run_analysis tool: sandbox-backed analysis with verifiable results.

Security (task book §15): no credentials in the sandbox; inputs are the
task's authorized source result sets only; deny-all egress; resource
capped; destroy in finally. Contribution analysis uses a deterministic
template — the model can't quietly slant the math; custom code is allowed
for stat analyses but its result must come back via the result contract.
"""

from __future__ import annotations

import json
import time

from agent_adapter import Tool, ToolContext, ToolError

from ..sandbox import SandboxError, contribution_template, run_isolated


def build_analysis_tools(ctx: ToolContext, deps, *, cancel_check=None) -> list[Tool]:
    async def run_analysis(c: ToolContext, args: dict) -> dict:
        analysis_type = args.get("analysis_type", "contribution")
        inputs = args.get("inputs") or []
        if len(inputs) < 1:
            raise ToolError("bad_arguments", "inputs 不能为空", retryable=True)

        # Load authorized source results (workspace-checked).
        from t2d_db.models import FileRef, Source

        loaded: dict[str, dict] = {}
        evidence: list[dict] = []
        for entry in inputs:
            source_id = entry.get("source_id")
            with deps.sessionmaker() as s:
                source = s.get(Source, int(source_id)) if source_id else None
                if source is None or source.workspace_id != c.workspace_id:
                    raise ToolError("permission_denied",
                                    f"source 不存在或无权访问: {source_id}")
                ref = s.get(FileRef, source.result_file_id) if source.result_file_id else None
                if ref is None:
                    raise ToolError("bad_input", f"source {source_id} 没有结果文件")
                payload = json.loads(deps.files.get(ref.storage_key))
            role = entry.get("role", "input")
            loaded[role] = {
                "rows": payload.get("rows", []),
                "columns": payload.get("columns", []),
                "source_id": source.id, "title": source.title,
            }
            evidence.append({"source_id": source.id, "role": role,
                             "note": entry.get("note", "")})

        inferred: dict = {}
        if analysis_type == "contribution":
            if "current" not in loaded or "previous" not in loaded:
                raise ToolError("bad_arguments",
                                "贡献分解需要 current 与 previous 两个输入",
                                hint="让查询 Agent 生成当期与上期两个 Source")
            key_field = args.get("key_field")
            value_field = args.get("value_field")
            if not key_field or not value_field:
                # Infer from column types: first text column = dimension,
                # first numeric = measure. Echoed in the result for transparency.
                numeric_types = {1700, 20, 21, 23, 26, 700, 701}
                columns = loaded["current"]["columns"]
                key_field = key_field or next(
                    (c["name"] for c in columns
                     if int(c.get("type") or 0) not in numeric_types), None)
                value_field = value_field or next(
                    (c["name"] for c in columns
                     if int(c.get("type") or 0) in numeric_types), None)
                inferred = {"inferred_key_field": key_field,
                            "inferred_value_field": value_field}
            if not key_field or not value_field:
                raise ToolError(
                    "bad_arguments",
                    "无法确定维度列/数值列，请显式传 key_field 与 value_field",
                    hint="从 Source 的 columns 中选择，如 country 与 gmv",
                    retryable=True,
                )
            input_files = {}
            for role in ("current", "previous"):
                input_files[f"{role}.json"] = json.dumps({
                    "rows": loaded[role]["rows"],
                    "columns": loaded[role]["columns"],
                    "key_field": key_field, "value_field": value_field,
                }, ensure_ascii=False, default=str)
            code = contribution_template()
        elif analysis_type == "custom":
            code = args.get("code") or ""
            if not code.strip():
                raise ToolError("bad_arguments", "custom 分析必须提供 code")
            if "t2d_result.json" not in code:
                raise ToolError("bad_arguments",
                                "custom 代码必须把结果 dict 写入 /tmp/t2d_result.json")
            input_files = {
                f"{name}.json": json.dumps(loaded[name], ensure_ascii=False, default=str)
                for name in loaded
            }
        else:
            raise ToolError("bad_arguments", f"未知分析类型: {analysis_type}")

        if cancel_check and cancel_check():
            raise ToolError("cancelled", "任务已取消")

        try:
            sandbox_result = await run_isolated(
                code, input_files=input_files,
                timeout_s=int(args.get("timeout_s", 120)),
            )
        except SandboxError as exc:
            raise ToolError("sandbox_error", f"沙箱执行失败: {exc}")

        if not sandbox_result.ok:
            raise ToolError(
                "analysis_failed",
                f"分析脚本失败: {sandbox_result.stderr[-200:] or sandbox_result.stdout[-200:]}",
                retryable=True,
            )

        # Persist the analysis report (verifiable artifact).
        from t2d_db.models import FileRef as FR

        report = json.dumps({
            "analysis_type": analysis_type,
            "result": sandbox_result.result,
            "evidence": evidence,
            "duration_ms": sandbox_result.duration_ms,
            "sandbox_profile": {"cpu": "1", "memory": "1Gi", "network": "deny-all"},
        }, ensure_ascii=False, default=str).encode()
        key = f"analysis/task-{c.task_id}-{int(time.time() * 1000)}.json"
        meta = deps.files.put(key, report, mime="application/json")
        with deps.sessionmaker() as s:
            file_ref = FR(
                kind="analysis_report", storage_key=meta.storage_key,
                mime="application/json", size_bytes=meta.size_bytes,
                sha256=meta.sha256, workspace_id=c.workspace_id,
                created_by=c.user_id, task_id=c.task_id,
            )
            s.add(file_ref)
            s.commit()
            analysis_id = file_ref.id

        summary_bits = []
        result = sandbox_result.result or {}
        if inferred:
            result = {**result, **inferred}
        if analysis_type == "contribution":
            summary_bits.append(
                f"总量 {result.get('total_previous')} → {result.get('total_current')}"
                f"（{result.get('total_delta_pct')}%）")
            top = (result.get("contributions") or [{}])[0]
            summary_bits.append(f"最大贡献维度: {top.get('dimension')}")
        return {
            "analysis_id": analysis_id,
            "analysis_type": analysis_type,
            "result": result,
            "artifacts": [{"file_id": analysis_id, "name": "analysis_report.json"}],
            "evidence": evidence,
            "duration_ms": sandbox_result.duration_ms,
            "_summary": "；".join(summary_bits) or "分析完成",
        }

    return [
        Tool(
            name="run_analysis",
            description="在隔离沙箱中执行分析计算（贡献分解/自定义统计），返回可验证结果与报告文件。",
            parameters={
                "type": "object",
                "properties": {
                    "analysis_type": {"type": "string",
                                      "enum": ["contribution", "custom"]},
                    "inputs": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "source_id": {"type": "integer"},
                                "role": {"type": "string",
                                         "enum": ["current", "previous", "input"],
                                         "description": "贡献分解须有 current 与 previous"},
                                "note": {"type": "string"},
                            },
                            "required": ["source_id"],
                        },
                    },
                    "key_field": {"type": "string",
                                  "description": "贡献分解的维度列名"},
                    "value_field": {"type": "string",
                                    "description": "贡献分解的数值列名"},
                    "code": {"type": "string",
                             "description": "custom 分析的 Python 代码（结果写 /tmp/t2d_result.json）"},
                    "timeout_s": {"type": "integer"},
                },
                "required": ["analysis_type", "inputs"],
            },
            handler=run_analysis,
        ),
    ]
