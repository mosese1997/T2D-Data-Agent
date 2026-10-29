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
from agent_adapter.toolloop import ToolLoopRuntime
from agent_adapter.toolloop.runtime import attach_context
from t2d_db import queue
from t2d_db.models import AgentRun, Dashboard, Message, Task, TaskCheckpoint, ToolCall
from t2d_db.session import get_sessionmaker, utcnow

from .deps import WorkerDeps
from .tools import build_tools_for
from .tools.context import context_for_task

PROMPTS_DIR = Path(__file__).resolve().parent / "agents" / "prompts"
MODEL = os.environ.get("MODEL_NAME", "t2d/deepseek-v4.1-flash-1017")
BRAND = os.environ.get("APP_BRAND", "t2d")

TERMINAL = {"succeeded", "failed", "cancelled", "interrupted"}


def _prompt(name: str) -> str:
    return (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8").replace("{brand}", BRAND)


def _jsonable(value):
    """Make DB results (dates, decimals, …) safe for JSON columns."""
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


class TaskRunner:
    def __init__(self, deps: WorkerDeps, runtime: ToolLoopRuntime | None = None):
        self.deps = deps
        self.runtime = runtime or ToolLoopRuntime()
        self.maker = get_sessionmaker()

    # ── event / trace / state plumbing ─────────────────────────────
    def _emit(self, task_id: int, event_type: str, data: dict, *, phase: str | None = None) -> None:
        with self.maker() as s:
            queue.emit_event(s, task_id, event_type, phase=phase, data=_jsonable(data))
            s.commit()

    def _sink_for(self, task_id: int, agent_name: str):
        def sink(event: AgentEvent) -> None:
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
                         messages, tools, expect_structured=False, budget=None):
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
                event_sink=self._sink_for(task_id, agent_name),
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
        brief = self._load_task_brief(task_id)
        payload = brief["payload"]
        checkpoint = brief["checkpoint"]
        ctx = context_for_task(task_id)
        cancel = CancelToken()
        user_text = payload.get("content", "")
        dashboard_id = brief["dashboard_id"]

        try:
            if self._cancel_requested(task_id):
                self._set_status(task_id, "cancelled")
                return

            # ── phase 1: intent ─────────────────────────────────────
            intent = None
            if checkpoint.get("step") in ("waiting_clarification", "query_executed", "patch_proposed"):
                intent = checkpoint.get("state", {}).get("intent")
            if intent is None:
                self._emit(task_id, "phase.started", {"phase": "intent_parse"}, phase="intent_parse")
                messages = self._conversation_tail(brief["conversation_id"])
                messages.append({"role": "user", "content": user_text})
                if payload.get("answer"):
                    messages.append({"role": "user", "content": f"（用户补充）{payload['answer']}"})
                result = await self._run_agent(
                    task_id, ctx, cancel,
                    agent_name="main", prompt=_prompt("main_intent"), messages=messages,
                    tools=build_tools_for("main", ctx, self.deps),
                    expect_structured=True,
                    budget=Budget(max_steps=8, max_tool_calls=4),
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
                if intent.get("clarify"):
                    self._checkpoint(task_id, "waiting_clarification", {"intent": intent})
                    self._emit(task_id, "clarification.requested",
                               {"question": intent["clarify"]}, phase="intent_parse")
                    self._set_status(task_id, "waiting_for_user")
                    return
                self._checkpoint(task_id, "intent_parsed", {"intent": intent})

            if self._cancel_requested(task_id):
                self._set_status(task_id, "cancelled")
                return

            # ── phase 2: query sub-agent ────────────────────────────
            sources_info = None
            if checkpoint.get("step") in ("query_executed", "patch_proposed"):
                sources_info = checkpoint.get("state", {}).get("sources")
            if sources_info is None:
                self._emit(task_id, "phase.started", {"phase": "sql_generate"}, phase="sql_generate")
                query_messages = [{
                    "role": "user",
                    "content": "分析意图 JSON：\n" + json.dumps(intent, ensure_ascii=False)
                                + f"\n\n用户原话：{user_text}"
                                + (f"\n关联看板 dashboard_id={dashboard_id}" if dashboard_id else ""),
                }]
                qresult = await self._run_agent(
                    task_id, ctx, cancel,
                    agent_name="query", prompt=_prompt("query"), messages=query_messages,
                    tools=build_tools_for("query", ctx, self.deps,
                                          cancel_check=lambda: self._cancel_requested(task_id)),
                    expect_structured=True,
                    budget=Budget(max_steps=24, max_tool_calls=14),
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

            if self._cancel_requested(task_id):
                self._set_status(task_id, "cancelled")
                return

            # ── phase 3: component design → candidate patch ────────
            patch_info = None
            if checkpoint.get("step") == "patch_proposed":
                patch_info = checkpoint.get("state", {}).get("patch")
            if patch_info is None:
                dashboard_id = dashboard_id or self._ensure_dashboard(task_id, ctx, user_text)
                self._emit(task_id, "phase.started", {"phase": "patch_propose"}, phase="patch_propose")
                design_messages = [{
                    "role": "user",
                    "content":
                        f"用户需求：{user_text}\n"
                        f"看板 dashboard_id：{dashboard_id}\n"
                        f"Source 列表：\n" + json.dumps(sources_info, ensure_ascii=False, default=str),
                }]
                dresult = await self._run_agent(
                    task_id, ctx, cancel,
                    agent_name="main", prompt=_prompt("main_design"),
                    messages=design_messages,
                    tools=build_tools_for("main", ctx, self.deps),
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
                    self._set_status(task_id, "failed", error={
                        "code": "patch_failed",
                        "message": patch_result.get("_summary") or "候选变更生成失败",
                    })
                    return
                self._checkpoint(task_id, "patch_proposed",
                                 {"intent": intent, "sources": sources_info, "patch": patch_info})

            # ── hand off to the user (Apply happens in the API) ─────
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

    # ── helpers ────────────────────────────────────────────────────
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
