"""E3: Temporal workflow definitions — the runner's state machine as workflows.

Mapping (evolution plan E3):
- Task = Workflow (Workflow ID = task idempotency key)
- intent / query / design / analysis phases = Activities
- waiting_for_user = Signal wait (user answers → signal → resume)
- waiting_for_apply = Signal wait (user applies → signal → complete)
- cancel = Cancel workflow (Temporal native)
- crash recovery = event-sourced replay (activities never re-execute —
  verified in E0 probe)

The Activities call the SAME logic as the inline runner (the runner's
phase functions are extracted as reusable async functions). Events still
write to run_events for SSE — the frontend is completely unchanged.

This module defines the workflows; t2d_worker/temporal_worker.py runs them.
"""

from __future__ import annotations

import json
from datetime import timedelta

from temporalio import activity, workflow
from temporalio.worker import UnsandboxedWorkflowRunner


@activity.defn
async def run_intent_phase(task_id: int, payload: dict) -> dict:
    """Intent phase: parse user intent → structured JSON or clarify."""
    from .runner import TaskRunner
    from .deps import build_deps

    runner = TaskRunner(build_deps())
    result = await runner._run_intent_phase(task_id, payload)
    return result


@activity.defn
async def run_query_phase(task_id: int, intent: dict, user_text: str) -> dict:
    """Query phase: generate + execute SQL → sources list."""
    from .runner import TaskRunner
    from .deps import build_deps

    runner = TaskRunner(build_deps())
    result = await runner._run_query_phase(task_id, intent, user_text)
    return result


@activity.defn
async def run_design_phase(task_id: int, intent: dict, sources: list,
                          user_text: str, dashboard_id: int) -> dict:
    """Design phase: propose dashboard patch."""
    from .runner import TaskRunner
    from .deps import build_deps

    runner = TaskRunner(build_deps())
    result = await runner._run_design_phase(task_id, intent, sources,
                                            user_text, dashboard_id)
    return result


@activity.defn
async def run_analysis_phase(task_id: int, intent: dict, sources: list,
                             user_text: str) -> dict:
    """Analysis phase: sandbox contribution decomposition."""
    from .runner import TaskRunner
    from .deps import build_deps

    runner = TaskRunner(build_deps())
    result = await runner._run_analysis_phase(task_id, intent, sources, user_text)
    return result


@activity.defn
async def run_answer_phase(task_id: int, user_text: str, sources: list,
                           ctx_note: str) -> dict:
    """Answer phase: conversational reply from query results."""
    from .runner import TaskRunner
    from .deps import build_deps

    runner = TaskRunner(build_deps())
    result = await runner._run_answer_phase(task_id, user_text, sources, ctx_note)
    return result


@activity.defn
async def finalize_task(task_id: int, status: str, result: dict) -> None:
    """Update the task row's final status (called by the workflow at the end)."""
    from .runner import TaskRunner
    from .deps import build_deps
    runner = TaskRunner(build_deps())
    runner._set_status(task_id, status, result=result)


@workflow.defn
class BuildDashboardWorkflow:
    """Maps the runner's build/modify task state machine.

    Phases: intent → [clarify signal] → query → design/analysis → [apply signal]
    """

    def __init__(self) -> None:
        self._user_answer: str | None = None
        self._applied: bool = False

    @workflow.run
    async def run(self, payload: dict) -> dict:
        task_id = payload["task_id"]
        user_text = payload.get("content", "")
        dashboard_id = payload.get("dashboard_id")

        # Phase 1: Intent (activity returns {intent, clarify, status})
        intent_result = await workflow.execute_activity(
            run_intent_phase, args=[task_id, payload],
            start_to_close_timeout=timedelta(seconds=120))
        if intent_result.get("status") == "clarify":
            # Signal wait: waiting_for_user
            await workflow.wait_condition(lambda: self._user_answer is not None)
            payload["answer"] = self._user_answer
            intent_result = await workflow.execute_activity(
                run_intent_phase, args=[task_id, payload],
                start_to_close_timeout=timedelta(seconds=120))
            if intent_result.get("status") == "clarify":
                return {"status": "clarify_exhausted",
                        "question": intent_result.get("clarify")}
        if intent_result.get("status") == "failed":
            return {"status": "failed", "error": intent_result.get("error")}
        intent = intent_result.get("intent", {})
        mode = intent.get("mode", "")

        # Phase 2: Query (returns {sources, status})
        query_result = await workflow.execute_activity(
            run_query_phase, args=[task_id, intent, user_text],
            start_to_close_timeout=timedelta(seconds=300))
        if query_result.get("status") == "failed":
            return {"status": "failed", "error": query_result.get("error")}
        sources = query_result.get("sources", [])

        # Phase 3: route by intent mode
        if mode == "analysis":
            result = await workflow.execute_activity(
                run_analysis_phase, args=[task_id, intent, sources, user_text],
                start_to_close_timeout=timedelta(seconds=300))
            await workflow.execute_activity(
                finalize_task, args=[task_id, "succeeded", result],
                start_to_close_timeout=timedelta(seconds=30))
            return {"status": "succeeded", "result": result}
        elif mode == "answer":
            result = await workflow.execute_activity(
                run_answer_phase, args=[task_id, user_text, sources, ""],
                start_to_close_timeout=timedelta(seconds=120))
            await workflow.execute_activity(
                finalize_task, args=[task_id, "succeeded", result],
                start_to_close_timeout=timedelta(seconds=30))
            return {"status": "succeeded", "result": result}
        else:
            # Build/modify: design → waiting_for_apply
            result = await workflow.execute_activity(
                run_design_phase,
                args=[task_id, intent, sources, user_text, dashboard_id or 0],
                start_to_close_timeout=timedelta(seconds=120))
            if result.get("status") == "clarify":
                await workflow.wait_condition(lambda: self._user_answer is not None)
                return {"status": "clarify", "question": result.get("clarify_text")}
            if result.get("status") == "failed":
                return {"status": "failed", "error": result.get("error")}
            # Signal wait: waiting_for_apply
            await workflow.wait_condition(lambda: self._applied)
            # Finalize: update the task row
            await workflow.execute_activity(
                finalize_task, args=[task_id, "succeeded",
                                     {"patch_id": result.get("patch", {}).get("patch_id"),
                                      "dashboard_id": result.get("dashboard_id")}],
                start_to_close_timeout=timedelta(seconds=30))
            return {"status": "succeeded", "result": result}

    @workflow.signal
    def user_answer(self, answer: str) -> None:
        self._user_answer = answer

    @workflow.signal
    def applied(self) -> None:
        self._applied = True


@workflow.defn
class RefreshWorkflow:
    """Refresh task: re-execute bound sources (deterministic, no LLM)."""

    @workflow.run
    async def run(self, payload: dict) -> dict:
        task_id = payload["task_id"]
        dashboard_id = payload["dashboard_id"]
        from .runner import TaskRunner
        from .deps import build_deps
        runner = TaskRunner(build_deps())
        result = await runner._run_refresh(task_id, dashboard_id)
        return result
