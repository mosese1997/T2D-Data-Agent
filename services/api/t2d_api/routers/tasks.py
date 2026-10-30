"""Task endpoints: snapshot, SSE stream (Last-Event-ID resume), cancel, answer.

SSE contract (task book §11): every event carries the per-task seq as id:;
reconnecting with Last-Event-ID replays seq > last. Only real phases and
tool summaries are streamed — never model hidden reasoning (that lives in
tool_calls/agent_runs for the admin Trace page).
"""

from __future__ import annotations

import asyncio
import json
import time

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..deps import CurrentUser, DbDep, get_workspace_role
from t2d_db import queue
from t2d_db.models import Message, RunEvent, Task
from t2d_db.session import get_sessionmaker

router = APIRouter(prefix="/api/tasks", tags=["tasks"])

TERMINAL = {"succeeded", "failed", "cancelled", "interrupted"}


def _task_or_404(db, task_id: int, user) -> Task:
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task.user_id != user.id:
        # Workspace members may observe; outsiders get 404 (no existence leak).
        try:
            get_workspace_role(db, user, task.workspace_id)
        except HTTPException:
            raise HTTPException(status_code=404, detail="任务不存在")
    return task


@router.get("/{task_id}")
def snapshot(task_id: int, user: CurrentUser, db: DbDep):
    task = _task_or_404(db, task_id, user)
    events = (
        db.query(RunEvent)
        .filter(RunEvent.task_id == task_id)
        .order_by(RunEvent.seq.desc())
        .limit(20)
        .all()
    )
    return {
        "id": task.id,
        "type": task.type,
        "status": task.status,
        "result": task.result,
        "error": task.error,
        "dashboard_id": task.dashboard_id,
        "created_at": task.created_at.isoformat(),
        "events": [
            {"seq": e.seq, "event": e.event_type, "phase": e.phase, "data": e.data}
            for e in reversed(events)
        ],
    }


@router.get("/{task_id}/events")
async def stream_events(task_id: int, user: CurrentUser, db: DbDep, request: Request):
    _task_or_404(db, task_id, user)
    last_id = request.headers.get("Last-Event-ID") or request.query_params.get("last_event_id")
    cursor = int(last_id) if (last_id or "").isdigit() else 0

    async def generate():
        nonlocal cursor
        maker = get_sessionmaker()
        heartbeat_counter = 0
        deadline = time.monotonic() + 3600  # 1h 硬上限：防连接泄漏
        while True:
            if time.monotonic() > deadline:
                yield ": max-duration-reached\n\n"
                return
            with maker() as s:
                events = (
                    s.query(RunEvent)
                    .filter(RunEvent.task_id == task_id, RunEvent.seq > cursor)
                    .order_by(RunEvent.seq)
                    .all()
                )
                status = s.get(Task, task_id).status
            for event in events:
                cursor = event.seq
                data = json.dumps(event.data, ensure_ascii=False, default=str)
                yield f"id: {event.seq}\nevent: {event.event_type}\ndata: {data}\n\n"
            if status in TERMINAL:
                # Give the terminal event a beat to flush, then close.
                yield ": stream-complete\n\n"
                return
            heartbeat_counter += 1
            if heartbeat_counter % 15 == 0:
                yield ": heartbeat\n\n"
            await asyncio.sleep(1.0)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no",
                 "Connection": "keep-alive"},
    )


@router.post("/{task_id}/cancel")
def cancel(task_id: int, user: CurrentUser, db: DbDep):
    task = _task_or_404(db, task_id, user)
    if task.status in TERMINAL:
        raise HTTPException(status_code=409, detail=f"任务已结束（{task.status}）")
    queue.request_cancel(task_id)
    return {"ok": True, "status": task.status}


class AnswerRequest(BaseModel):
    content: str


@router.post("/{task_id}/answer")
def answer(task_id: int, body: AnswerRequest, user: CurrentUser, db: DbDep):
    """Answer a clarification: appends the reply and requeues the task."""
    task = _task_or_404(db, task_id, user)
    if task.status != "waiting_for_user":
        raise HTTPException(status_code=409, detail=f"任务不在等待用户输入状态（{task.status}）")
    content = body.content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="回复不能为空")

    if task.conversation_id:
        last_seq = (
            db.query(Message.seq)
            .filter(Message.conversation_id == task.conversation_id)
            .order_by(Message.seq.desc())
            .limit(1)
            .scalar()
        ) or 0
        db.add(Message(conversation_id=task.conversation_id, seq=last_seq + 1,
                       role="user", content=content, task_id=task.id))

    payload = dict(task.payload or {})
    payload["answer"] = content
    task.payload = payload
    task.status = "queued"
    task.cancel_requested = False
    task.lease_owner = None
    task.lease_expires_at = None
    db.commit()
    return {"ok": True, "status": "queued"}
