"""Task runner: deterministic orchestration with the model at decision points.

Pipeline (build_dashboard / modify_dashboard):
  intent (main agent, search_semantics) → [clarify → waiting_for_user]
  query (query sub-agent, definition/schema/validate/execute → Source)
  design (main agent, propose_dashboard_patch) → waiting_for_apply

The runner owns state transitions, checkpoints and cancellation; the model
owns intent parsing, SQL generation and component design. Sub-agents return
structured results — never chat transcripts (task book §9).

Crash safety: checkpoints let a re-claimed task skip completed phases
(query_executed → straight to design; patch_proposed → re-emit preview).
Apply itself is a single API transaction — never re-applied here.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from agent_adapter import AgentEvent, AgentSession, Budget, CancelToken
from agent_adapter.events import to_sse
from agent_adapter.toolloop.runtime import attach_context
from t2d_db import queue
from t2d_db.models import (
    AgentRun, Dashboard, DashboardVersion, Message, Task, TaskCheckpoint, ToolCall,
)
from t2d_db.session import get_sessionmaker, utcnow

from .deps import WorkerDeps, build_runtime
from .tools import build_tools_for
from .tools.context import context_for_task

PROMPTS_DIR = Path(__file__).resolve().parent / "agents" / "prompts"
MODEL = os.environ.get("MODEL_NAME", "t2d/deepseek-v4.1-flash-1017")
BRAND = os.environ.get("APP_BRAND", "t2d")

TERMINAL = {"succeeded", "failed", "cancelled", "interrupted"}


def _prompt(name: str) -> str:
    return (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8").replace("{brand}", BRAND)


def _tools_mode() -> str:
    """inline | mcp — from agent_config.yaml (E1 dual-track)."""
    import yaml
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    config_path = os.environ.get(
        "AGENT_CONFIG_PATH", str(root / "config" / "agent" / "agent_config.yaml"))
    try:
        with open(config_path, encoding="utf-8") as f:
            return (yaml.safe_load(f) or {}).get("agent", {}).get("tools", "inline")
    except OSError:
        return "inline"


def _lang_note(locale: str) -> str:
    """Language instruction for user-facing agents (answers, titles,
    caliber notes, change summaries follow the UI language)."""
    if locale == "en":
        return ("\n【语言要求】用户界面语言为 English。所有面向用户的文字——最终回答、"
                "Source 标题、口径说明、组件标题、变更摘要——必须用 English 输出。"
                "内部 JSON 字段名保持不变。")
    return ""  # zh 是默认，提示词本身即中文


def _jsonable(value):
    """Make DB results (dates, decimals, …) safe for JSON columns."""
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


class TaskRunner:
    def __init__(self, deps: WorkerDeps, runtime=None):
        self.deps = deps
        self.runtime = runtime or build_runtime()
        self.maker = get_sessionmaker()

    # ── event / trace / state plumbing ─────────────────────────────
    def _emit(self, task_id: int, event_type: str, data: dict, *, phase: str | None = None) -> None:
        with self.maker() as s:
            queue.emit_event(s, task_id, event_type, phase=phase, data=_jsonable(data))
            s.commit()

    def _sink_for(self, task_id: int, agent_name: str, *, show_messages: bool = True):
        """SSE event sink for one agent run.

        show_messages=False for PROCESS agents (intent, query): their final
        output is internal (intent JSON / source list) and must NOT appear
        as a chat bubble — only user-facing agents (answer/design/analysis)
        get their message streamed to the chat.
        """
        def sink(event: AgentEvent) -> None:
            if event.type == "message" and not show_messages:
                return  # process output stays in the trace, not the chat
            mapped = to_sse(event.type, event.data)
            if mapped is None:
                return
            sse_name, payload_json = mapped
            self._emit(task_id, sse_name, json.loads(payload_json), phase=agent_name)
        return sink

    def _trace_for(self, task_id: int, agent_name: str):
        seq = {"n": 0}

        def trace(tool_name, args, output, latency_ms, status) -> None:
            seq["n"] += 1
            with self.maker() as s:
                s.add(ToolCall(
                    task_id=task_id, seq=seq["n"], agent_name=agent_name,
                    tool_name=tool_name, input_json=_jsonable(args),
                    output_json=_jsonable(output) if output is not None else None,
                    status=status, latency_ms=latency_ms,
                ))
                s.commit()
        return trace

    def _set_status(self, task_id: int, status: str, *, result=None, error=None) -> None:
        with self.maker() as s:
            task = s.get(Task, task_id)
            task.status = status
            if result is not None:
                task.result = result
            if error is not None:
                task.error = error
            if status in TERMINAL:
                task.finished_at = utcnow()
                task.lease_expires_at = None
            s.commit()
        self._emit(task_id, "task.status_changed", {"status": status})
        # Terminal SSE events close the stream client-side.
        if status == "succeeded":
            self._emit(task_id, "task.completed", {"result": result or {}})
        elif status == "failed":
            self._emit(task_id, "task.failed", {"error": error or {}})
        elif status == "cancelled":
            self._emit(task_id, "task.cancelled", {})

    def _checkpoint(self, task_id: int, step: str, state: dict) -> None:
        state = _jsonable(state)
        with self.maker() as s:
            task = s.get(Task, task_id)
            task.checkpoint = {"step": step, "state": state}
            s.add(TaskCheckpoint(task_id=task_id, step=step, state_json=state))
            s.commit()

    def _cancel_requested(self, task_id: int) -> bool:
        with self.maker() as s:
            return bool(s.get(Task, task_id).cancel_requested)

    def _load_task_brief(self, task_id: int) -> dict:
        with self.maker() as s:
            task = s.get(Task, task_id)
            return {
                "payload": dict(task.payload or {}),
                "checkpoint": dict(task.checkpoint or {}),
                "conversation_id": task.conversation_id,
                "dashboard_id": task.dashboard_id,
            }

    # ── agent phase driver ─────────────────────────────────────────
    async def _run_agent(self, task_id: int, ctx, cancel, *, agent_name, prompt,
                         messages, tools, expect_structured=False, budget=None,
                         show_messages=True):
        with self.maker() as s:
            run_row = AgentRun(task_id=task_id, agent_name=agent_name,
                               runtime=self.runtime.name, model=MODEL,
                               status="running", started_at=utcnow())
            s.add(run_row)
            s.commit()
            run_id = run_row.id

        session = attach_context(
            AgentSession(
                agent_name=agent_name,
                system_prompt=prompt,
                messages=messages,
                tools=tools,
                event_sink=self._sink_for(task_id, agent_name, show_messages=show_messages),
                cancel_token=cancel,
                budget=budget or Budget(max_steps=24, max_tool_calls=16),
                expect_structured=expect_structured,
            ),
            ctx,
        )
        session.trace_hook = self._trace_for(task_id, agent_name)
        result = await self.runtime.run(session, model=MODEL)
        with self.maker() as s:
            row = s.get(AgentRun, run_id)
            row.status = result.status if result.status in ("succeeded", "failed", "cancelled") else "failed"
            row.finished_at = utcnow()
            row.token_usage = result.token_usage
            s.commit()
        return result

    # ── main entry ─────────────────────────────────────────────────
    async def run_task(self, task_id: int) -> None:
        if self._load_task_type(task_id) == "refresh":
            await self.run_refresh_task(task_id)
            return
        await self.run_build_task(task_id)

    def _load_task_type(self, task_id: int) -> str:
        with self.maker() as s:
            return s.get(Task, task_id).type

    async def run_refresh_task(self, task_id: int) -> None:
        """Deterministic refresh: re-execute every bound source's SQL with
        the publisher identity; swap result files in place. No LLM."""
        from t2d_db.models import DashboardVersion, FileRef, Source

        brief = self._load_task_brief(task_id)
        dashboard_id = brief["payload"].get("dashboard_id") or brief["dashboard_id"]
        ctx = context_for_task(task_id)
        self._emit(task_id, "phase.started", {"phase": "refresh"}, phase="refresh")
        try:
            with self.maker() as s:
                dashboard = s.get(Dashboard, dashboard_id)
                if dashboard is None or dashboard.workspace_id != ctx.workspace_id:
                    self._set_status(task_id, "failed", error={
                        "code": "not_found", "message": "看板不存在或无权刷新"})
                    return
                version = (s.get(DashboardVersion, dashboard.current_version_id)
                           if dashboard.current_version_id else None)
                if version is None:
                    self._set_status(task_id, "failed", error={
                        "code": "no_version", "message": "看板没有版本可刷新"})
                    return
                source_ids = sorted({
                    int(c["source_id"]) for c in version.canvas_json.get("components", [])
                    if c.get("source_id")
                })
            refreshed = 0
            for sid in source_ids:
                if self._cancel_requested(task_id):
                    self._set_status(task_id, "cancelled")
                    return
                with self.maker() as s:
                    source = s.get(Source, sid)
                    if source is None or source.workspace_id != ctx.workspace_id:
                        continue
                    sql_text = source.sql_text
                result = self.deps.gateway.execute(
                    identity="publisher", sql=sql_text,
                    allowed_objects=set(ctx.datasets),
                    cancel_check=lambda: self._cancel_requested(task_id),
                )
                payload = json.dumps(
                    {"columns": result.columns,
                     "rows": [list(r) for r in result.rows],
                     "row_count": result.row_count, "truncated": result.truncated},
                    ensure_ascii=False, default=str,
                ).encode()
                meta = self.deps.files.put(
                    f"sources/refresh-{sid}-{int(utcnow().timestamp())}.json", payload)
                with self.maker() as s:
                    source = s.get(Source, sid)
                    ref = FileRef(
                        kind="source_result", storage_key=meta.storage_key,
                        mime="application/json", size_bytes=meta.size_bytes,
                        sha256=meta.sha256, workspace_id=ctx.workspace_id,
                        created_by=ctx.user_id, task_id=task_id,
                    )
                    s.add(ref)
                    s.flush()
                    source.result_file_id = ref.id
                    source.row_count = result.row_count
                    source.col_schema = result.columns
                    source.status = "active"
                    s.commit()
                refreshed += 1
                self._emit(task_id, "tool.completed", {
                    "tool": "refresh_source", "agent": "runner",
                    "summary": f"Source {sid} 刷新：{result.row_count} 行",
                }, phase="refresh")
            self._emit(task_id, "phase.completed",
                       {"phase": "refresh", "summary": f"已刷新 {refreshed} 个 Source"},
                       phase="refresh")
            self._set_status(task_id, "succeeded",
                             result={"dashboard_id": dashboard_id,
                                     "refreshed_sources": refreshed})
        except Exception as exc:  # noqa: BLE001
            self._set_status(task_id, "failed", error={
                "code": "refresh_error", "message": f"{type(exc).__name__}: {exc}"})

    async def run_build_task(self, task_id: int) -> None:
        brief = self._load_task_brief(task_id)
        payload = brief["payload"]
        checkpoint = brief["checkpoint"]
        ctx = context_for_task(task_id)
        cancel = CancelToken()
        user_text = payload.get("content", "")
        lang_note = _lang_note(payload.get("locale", "zh"))
        dashboard_id = brief["dashboard_id"]
        mcp_session = None
        if _tools_mode() == "mcp":
            from agent_adapter.mcp_client import McpToolSession
            mcp_session = McpToolSession(
                os.environ.get("T2D_MCP_URL", "http://127.0.0.1:9100/mcp"), ctx)
            try:
                await mcp_session._connect()
            except Exception as exc:
                print(f"[worker] ⚠️ MCP server 不可达（{exc}）——回退 inline 工具", flush=True)
                mcp_session = None

        try:
            if self._cancel_requested(task_id):
                self._set_status(task_id, "cancelled")
                return

            # ── phase 1: intent ─────────────────────────────────────
            intent = None
            # waiting_clarification 不在此列：用户回答后必须重跑意图段，
            # 复用旧的 clarify 意图会把空 time_spec 带进查询段（task 36 教训）。
            if checkpoint.get("step") in ("query_executed", "patch_proposed"):
                intent = checkpoint.get("state", {}).get("intent")
            # 对话 harness：注入本会话上一个任务的结果状态，让"为什么失败"
            # 这类指代性问题有据可答；澄清轮数防止无限追问。
            ctx_note = self._conversation_task_context(brief["conversation_id"], task_id)
            clarify_rounds = int(payload.get("_clarify_rounds", 0))

            if intent is None:
                self._emit(task_id, "phase.started", {"phase": "intent_parse"}, phase="intent_parse")
                messages = self._conversation_tail(brief["conversation_id"])
                if clarify_rounds:
                    ctx_note += (f"\n（已澄清 {clarify_rounds} 轮。如仍有歧义，"
                                 "请选择最合理的解释并明确说明假设，不要继续追问。）")
                # Prefetch semantic hits here — the intent agent doesn't need
                # a tool round-trip for what the runner can look up directly
                # (cuts one LLM call per task).
                hits = self.deps.retriever.search(user_text, top_k=8)
                hits_text = json.dumps(
                    [{"kind": h.kind, "key": h.key, "name": h.name, "score": h.score}
                     for h in hits], ensure_ascii=False)
                messages.append({"role": "user", "content":
                                 f"{user_text}\n\n（语义检索结果，按相关度排序）\n{hits_text}"
                                 + (f"\n\n（会话上下文）\n{ctx_note}" if ctx_note else "")})
                if payload.get("answer"):
                    messages.append({"role": "user", "content": f"（用户补充）{payload['answer']}"})
                result = await self._run_agent(
                    task_id, ctx, cancel,
                    agent_name="main", prompt=_prompt("main_intent"), messages=messages,
                    tools=await self._tools_for("main", ctx, mcp_session),
                    expect_structured=True,
                    budget=Budget(max_steps=8, max_tool_calls=4),
                    show_messages=False,  # 意图 JSON 是过程输出，不进聊天
                )
                if result.status == "cancelled":
                    self._set_status(task_id, "cancelled")
                    return
                if result.status != "succeeded" or not result.structured:
                    self._set_status(task_id, "failed", error={
                        "code": "intent_failed",
                        "message": (result.error or {}).get("message") or "意图解析失败",
                    })
                    return
                intent = result.structured
                if intent.get("clarify") or intent.get("mode") == "clarify":
                    self._checkpoint(task_id, "waiting_clarification", {"intent": intent})
                    self._emit(task_id, "clarification.requested",
                               {"question": intent.get("clarify") or "请补充您的需求"},
                               phase="intent_parse")
                    with self.maker() as s:
                        row = s.get(Task, task_id)
                        p = dict(row.payload or {})
                        p["_clarify_rounds"] = clarify_rounds + 1
                        row.payload = p
                        s.commit()
                    self._set_status(task_id, "waiting_for_user")
                    return
                self._checkpoint(task_id, "intent_parsed", {"intent": intent})
                self._emit(task_id, "phase.completed",
                           {"phase": "intent_parse", "summary": "意图已明确"},
                           phase="intent_parse")

            if self._cancel_requested(task_id):
                self._set_status(task_id, "cancelled")
                return

            # Simple modifications (title/legend/layout/text, task book §9)
            # go straight to the design phase — no query sub-agent.
            simple_modify = intent.get("mode") == "simple_modify"
            is_analysis = intent.get("mode") == "analysis"
            is_answer = intent.get("mode") == "answer"

            # 意图防线：进查询段前必须有可用时间口径（mode=clarify 或
            # time_spec 为空时转澄清，绝不把残缺意图交给查询 Agent——task 36 教训）。
            if not simple_modify and not (is_answer and not intent.get("metric_keys")):
                if intent.get("mode") == "clarify" or not intent.get("time_spec"):
                    question = intent.get("clarify") or (
                        "请补充时间范围（如：最近7天 / 最近30天 / 上周 / 过去N天）"
                        "以及想看的指标。")
                    self._checkpoint(task_id, "waiting_clarification", {"intent": intent})
                    self._emit(task_id, "clarification.requested",
                               {"question": question}, phase="intent_parse")
                    self._set_status(task_id, "waiting_for_user")
                    return

            # ── phase 2: query sub-agent ────────────────────────────
            sources_info = None
            if checkpoint.get("step") in ("query_executed", "patch_proposed"):
                sources_info = checkpoint.get("state", {}).get("sources")
            if sources_info is None and not simple_modify and not (is_answer and not intent.get("metric_keys")):
                self._emit(task_id, "phase.started", {"phase": "sql_generate"}, phase="sql_generate")
                analysis_clause = (
                    "\n\n这是对比分析任务：请生成**两个** Source——"
                    "当期（time_spec 指定窗口）与上期（紧邻的上一可比窗口，如 last_natural_week 的上期是再上一个完整自然周）"
                    "的按维度分组明细，列结构必须相同；purpose 分别标 current_breakdown 与 previous_breakdown。"
                    if is_analysis else ""
                )
                # Prefetch definitions + schema (no LLM needed for lookups —
                # the query agent goes straight to SQL generation).
                preloaded = self._prefetch_query_context(ctx, intent)
                query_messages = [{
                    "role": "user",
                    "content": "分析意图 JSON：\n" + json.dumps(intent, ensure_ascii=False)
                                + f"\n\n用户原话：{user_text}"
                                + (f"\n关联看板 dashboard_id={dashboard_id}" if dashboard_id else "")
                                + analysis_clause
                                + "\n\n（已预置上下文，直接生成 SQL 调用 execute_query 即可，不需要再调 get_semantic_definition / get_authorized_schema）\n"
                                + preloaded,
                }]
                qresult = await self._run_agent(
                    task_id, ctx, cancel,
                    agent_name="query", prompt=_prompt("query") + lang_note, messages=query_messages,
                    tools=await self._tools_for("query", ctx, mcp_session,
                                          cancel_check=lambda: self._cancel_requested(task_id)),
                    expect_structured=True,
                    budget=Budget(max_steps=24, max_tool_calls=14),
                    show_messages=False,  # Source 列表是过程输出，不进聊天
                )
                if qresult.status == "cancelled":
                    self._set_status(task_id, "cancelled")
                    return
                exec_result = qresult.tool_results.get("execute_query")
                if qresult.status != "succeeded" or not exec_result or "source_id" not in exec_result:
                    message = (qresult.structured or {}).get("error") \
                              or (qresult.error or {}).get("message") \
                              or "查询生成失败"
                    self._set_status(task_id, "failed", error={
                        "code": "query_failed", "message": message})
                    return
                # Sources list from the structured output, VALIDATED against
                # the DB (existence + workspace) — never trust model echo.
                sources_info = self._validated_sources(
                    task_id, ctx, qresult.structured or {}, exec_result)
                self._checkpoint(task_id, "query_executed",
                                 {"intent": intent, "sources": sources_info})
                total_rows = sum(s["row_count"] for s in sources_info)
                self._emit(task_id, "phase.completed",
                           {"phase": "sql_generate",
                            "summary": f"查询成功，{len(sources_info)} 个 Source / {total_rows} 行"},
                           phase="sql_generate")
            elif simple_modify or (is_answer and not intent.get("metric_keys")):
                sources_info = []
                self._checkpoint(task_id, "query_executed",
                                 {"intent": intent, "sources": sources_info})

            # ── answer mode: reply in chat — no dashboard (user asks, we answer)
            if is_answer:
                sources_info = sources_info or []
                answer_context = self._answer_context(sources_info)
                self._emit(task_id, "phase.started", {"phase": "answer"}, phase="answer")
                answer_messages = [{
                    "role": "user",
                    "content": f"用户问题：{user_text}\n\n查询结果（可能为空=没有查到数据或闲聊）：\n"
                                + json.dumps(answer_context, ensure_ascii=False, default=str)
                                + (f"\n\n（会话上下文——回答指代性问题如\"为什么失败\"时据此说明）\n{ctx_note}"
                                   if ctx_note else ""),
                }]
                arsult = await self._run_agent(
                    task_id, ctx, cancel,
                    agent_name="main", prompt=_prompt("main_answer") + lang_note,
                    messages=answer_messages, tools=[],
                    budget=Budget(max_steps=4, max_tool_calls=0),
                )
                if arsult.status == "cancelled":
                    self._set_status(task_id, "cancelled")
                    return
                answer = (arsult.content or "").strip() or "抱歉，没能生成回答。"
                self._emit(task_id, "phase.completed",
                           {"phase": "answer", "summary": "回答已生成"},
                           phase="answer")
                # agent.message 已由 toolloop 经 sink 发出，不再重发（避免双条）
                self._set_status(task_id, "succeeded", result={
                    "answer": answer,
                    "sources": [s["source_id"] for s in sources_info],
                    "mode": "answer",
                })
                return

            if self._cancel_requested(task_id):
                self._set_status(task_id, "cancelled")
                return

            # ── analysis mode: sandbox contribution run → done ──────
            if is_analysis:
                self._emit(task_id, "phase.started", {"phase": "analysis"}, phase="analysis")
                analysis_messages = [{
                    "role": "user",
                    "content":
                        f"用户问题：{user_text}\n"
                        f"Source 列表：\n" + json.dumps(sources_info, ensure_ascii=False, default=str),
                }]
                aresult = await self._run_agent(
                    task_id, ctx, cancel,
                    agent_name="analysis", prompt=_prompt("analysis") + lang_note,
                    messages=analysis_messages,
                    tools=await self._tools_for("analysis", ctx, mcp_session,
                                          cancel_check=lambda: self._cancel_requested(task_id)),
                    budget=Budget(max_steps=16, max_tool_calls=10),
                )
                if aresult.status == "cancelled":
                    self._set_status(task_id, "cancelled")
                    return
                run_result = aresult.tool_results.get("run_analysis")
                if aresult.status != "succeeded" or not run_result \
                        or "analysis_id" not in run_result:
                    self._set_status(task_id, "failed", error={
                        "code": "analysis_failed",
                        "message": (aresult.error or {}).get("message") or "分析执行失败",
                    })
                    return
                self._emit(task_id, "phase.completed",
                           {"phase": "analysis",
                            "summary": run_result.get("_summary", "分析完成")},
                           phase="analysis")
                # agent.message 已由 toolloop 经 sink 发出，不再重发（避免双条）
                self._set_status(task_id, "succeeded", result={
                    "analysis_id": run_result["analysis_id"],
                    "analysis_type": run_result.get("analysis_type"),
                    "summary": run_result.get("_summary"),
                    "sources": [s["source_id"] for s in sources_info],
                    "conclusion": aresult.content,
                })
                return

            # ── phase 3: component design → candidate patch ────────
            patch_info = None
            if checkpoint.get("step") == "patch_proposed":
                patch_info = checkpoint.get("state", {}).get("patch")
            if patch_info is None:
                dashboard_id = dashboard_id or self._ensure_dashboard(task_id, ctx, user_text)
                self._emit(task_id, "phase.started", {"phase": "patch_propose"}, phase="patch_propose")
                existing = self._canvas_summary(dashboard_id)
                design_messages = [{
                    "role": "user",
                    "content":
                        f"用户需求：{user_text}\n"
                        f"看板 dashboard_id：{dashboard_id}\n"
                        f"看板现有组件（新组件 id 必须避开这些）：\n"
                        + json.dumps(existing, ensure_ascii=False, default=str)
                        + f"\n\nSource 列表：\n" + json.dumps(sources_info, ensure_ascii=False, default=str),
                }]
                dresult = await self._run_agent(
                    task_id, ctx, cancel,
                    agent_name="main", prompt=_prompt("main_design") + lang_note,
                    messages=design_messages,
                    tools=await self._tools_for("main", ctx, mcp_session),
                    budget=Budget(max_steps=8, max_tool_calls=4),
                )
                if dresult.status == "cancelled":
                    self._set_status(task_id, "cancelled")
                    return
                # The DB is the truth: the model may call propose more than
                # once — use the validated patch row for THIS task, not the
                # last tool echo.
                patch_info = self._validated_patch(task_id, dashboard_id)
                if patch_info is None:
                    patch_result = dresult.tool_results.get("propose_dashboard_patch") or {}
                    # 设计 Agent 输出的是解释/澄清文字而非补丁 → 转澄清，
                    # 不判失败（task 35 教训：合理的反问不是错误）。
                    text = (dresult.content or "").strip()
                    if dresult.status == "succeeded" and len(text) >= 10:
                        self._emit(task_id, "agent.message", {"content": text})
                        self._checkpoint(task_id, "waiting_clarification",
                                         {"intent": intent, "sources": sources_info})
                        self._emit(task_id, "clarification.requested",
                                   {"question": text[:200]}, phase="patch_propose")
                        self._set_status(task_id, "waiting_for_user")
                        return
                    self._set_status(task_id, "failed", error={
                        "code": "patch_failed",
                        "message": patch_result.get("_summary") or "候选变更生成失败",
                    })
                    return
                self._checkpoint(task_id, "patch_proposed",
                                 {"intent": intent, "sources": sources_info, "patch": patch_info})

            # ── hand off to the user (Apply happens in the API) ─────
            self._emit(task_id, "phase.completed",
                       {"phase": "patch_propose", "summary": patch_info.get("diff_summary", "候选变更已生成")[:80]},
                       phase="patch_propose")
            self._emit(task_id, "patch.proposed", {
                "patch_id": patch_info["patch_id"],
                "diff_summary": patch_info["diff_summary"],
                "preview_canvas": patch_info.get("preview_canvas"),
            }, phase="patch_propose")
            self._set_status(task_id, "waiting_for_apply",
                             result={"patch_id": patch_info["patch_id"],
                                     "dashboard_id": dashboard_id})
        except Exception as exc:  # noqa: BLE001 — the runner must never crash the worker
            self._set_status(task_id, "failed", error={
                "code": "runner_error", "message": f"{type(exc).__name__}: {exc}"})
        finally:
            if mcp_session is not None:
                try:
                    await mcp_session.close()
                except Exception:
                    pass

    # ── helpers ────────────────────────────────────────────────────
    def _conversation_task_context(self, conversation_id: int | None,
                                   current_task_id: int) -> str:
        """Previous task outcome in this conversation — lets the agent answer
        referential questions ('为什么失败') with real facts."""
        if not conversation_id:
            return ""
        with self.maker() as s:
            prev = (
                s.query(Task)
                .filter(Task.conversation_id == conversation_id,
                        Task.id != current_task_id)
                .order_by(Task.id.desc())
                .first()
            )
            if prev is None:
                return ""
            if prev.status == "failed" and prev.error:
                return (f"上一个任务（#{prev.id}）失败：{prev.error.get('message', '')[:150]}")
            return f"上一个任务（#{prev.id}）状态：{prev.status}"

    async def _tools_for(self, agent_name: str, ctx, mcp_session,
                         cancel_check=None):
        """Inline tools (1.0) or MCP-wrapped tools (E1 dual-track)."""
        if mcp_session is not None:
            return await mcp_session.load_tools()
        return build_tools_for(agent_name, ctx, self.deps, cancel_check=cancel_check)

    def _canvas_summary(self, dashboard_id: int) -> list[dict]:
        """Existing component ids/titles/types — the design agent needs them
        to avoid id collisions (task 34: 'c1 already exists')."""
        with self.maker() as s:
            dashboard = s.get(Dashboard, dashboard_id)
            version = (s.get(DashboardVersion, dashboard.current_version_id)
                       if dashboard and dashboard.current_version_id else None)
            if version is None:
                return []
            return [
                {"id": c.get("id"), "type": c.get("type"), "title": c.get("title", "")}
                for c in (version.canvas_json or {}).get("components", [])
            ]

    def _prefetch_query_context(self, ctx, intent: dict) -> str:
        """Definitions + authorized schema, looked up by the runner (no LLM).
        Saves 2-3 tool round-trips per query task."""
        parts: list[str] = []
        keys = [k for k in (intent.get("metric_keys") or []) if k]
        if keys:
            definitions = []
            for key in keys:
                metric = self.deps.registry.metric(key)
                if metric:
                    definitions.append({
                        "metric_key": metric.metric_key, "name": metric.name,
                        "description": metric.description,
                        "expression": metric.expression,
                        "base_dataset": metric.base_dataset, "grain": metric.grain,
                        "time_field": metric.time_field,
                        "exclusions": metric.exclusions,
                        "currency_policy": metric.currency_policy,
                        "available_dimensions": metric.available_dimensions,
                        "allowed_joins": metric.allowed_joins,
                    })
            parts.append("指标定义：\n" + json.dumps(
                definitions, ensure_ascii=False, indent=1))
        try:
            schema = self.deps.warehouse.authorized_schema(sorted(ctx.datasets))
            # Merge semantic-layer column docs (value domains, zh→en maps).
            yaml_datasets = self.deps.registry.bundle.datasets
            for name, meta in schema.items():
                doc = yaml_datasets.get(name, {}).get("columns", {})
                for column in meta["columns"]:
                    if column["name"] in doc:
                        column["comment"] = doc[column["name"]]
            parts.append("授权表结构：\n" + json.dumps(
                schema, ensure_ascii=False, indent=1))
        except Exception:
            parts.append("（表结构预取失败——需要时调用 get_authorized_schema）")
        return "\n\n".join(parts)

    def _answer_context(self, sources_info: list[dict]) -> list[dict]:
        """Real rows + caliber notes for the answer agent (from the DB)."""
        from t2d_db.models import FileRef, Source

        context = []
        for entry in sources_info:
            with self.maker() as s:
                source = s.get(Source, int(entry["source_id"]))
                if source is None:
                    continue
                ref = s.get(FileRef, source.result_file_id) if source.result_file_id else None
                payload = None
                if ref is not None:
                    try:
                        payload = json.loads(self.deps.files.get(ref.storage_key))
                    except Exception:
                        payload = None
                context.append({
                    "title": source.title,
                    "columns": [c.get("name") for c in (payload or {}).get("columns", [])],
                    "rows": (payload or {}).get("rows", [])[:10],
                    "row_count": (payload or {}).get("row_count", source.row_count),
                    "caliber_notes": (source.caliber_notes or {}).get("notes", []),
                })
        return context

    def _validated_patch(self, task_id: int, dashboard_id: int) -> dict | None:
        """Latest validated patch row for this task, with a recomputed preview."""
        from dashboard_schema import apply_patch
        from dashboard_schema.canvas import Canvas
        from dashboard_schema.patch import Patch

        from t2d_db.models import DashboardPatch

        with self.maker() as s:
            row = (
                s.query(DashboardPatch)
                .filter_by(task_id=task_id, status="validated")
                .order_by(DashboardPatch.id.desc())
                .first()
            )
            if row is None:
                return None
            dashboard = s.get(Dashboard, dashboard_id)
            current = (
                s.get(DashboardVersion, dashboard.current_version_id)
                if dashboard and dashboard.current_version_id else None
            )
            base_canvas = current.canvas_json if current else {
                "schema_version": "1.0", "title": dashboard.title if dashboard else "",
                "filters": {"allowed": [], "defaults": {}},
                "layout": {"grid_cols": 12, "order": []}, "components": [],
            }
            diff = row.diff_summary or ""
            patch_id, patch_json = row.id, row.patch_json
        try:
            after = apply_patch(Canvas.model_validate(base_canvas),
                                Patch.model_validate(patch_json))
            preview = after.model_dump()
        except Exception:
            preview = None
        return {"patch_id": patch_id, "diff_summary": diff, "preview_canvas": preview}

    def _validated_sources(self, task_id: int, ctx, structured: dict,
                           last_exec: dict) -> list[dict]:
        """Sources list from the query agent's structured output, validated
        against the DB. Falls back to the last execute_query result."""
        from t2d_db.models import Source

        candidates = structured.get("sources") or []
        validated = []
        with self.maker() as s:
            for entry in candidates:
                source_id = entry.get("source_id")
                row = s.get(Source, int(source_id)) if source_id else None
                if row is None or row.workspace_id != ctx.workspace_id:
                    continue  # drop fabricated / foreign source ids
                validated.append({
                    "source_id": row.id,
                    "purpose": entry.get("purpose") or "breakdown",
                    "title": row.title,
                    "columns": row.col_schema,
                    "row_count": row.row_count,
                })
        if not validated and last_exec.get("source_id"):
            validated.append({
                "source_id": last_exec["source_id"],
                "purpose": "breakdown",
                "title": last_exec.get("source_title", "查询结果"),
                "columns": last_exec.get("columns", []),
                "row_count": last_exec.get("row_count", 0),
            })
        return validated

    def _conversation_tail(self, conversation_id: int | None, limit: int = 6) -> list[dict]:
        if not conversation_id:
            return []
        with self.maker() as s:
            rows = (
                s.query(Message)
                .filter(Message.conversation_id == conversation_id)
                .order_by(Message.seq.desc())
                .limit(limit)
                .all()
            )
        return [{"role": r.role, "content": r.content} for r in reversed(rows)]

    def _ensure_dashboard(self, task_id: int, ctx, user_text: str) -> int:
        with self.maker() as s:
            dashboard = Dashboard(
                workspace_id=ctx.workspace_id,
                title=(user_text[:24] or "新建看板"),
                status="draft", created_by=ctx.user_id,
            )
            s.add(dashboard)
            s.commit()
            return dashboard.id
