"""Conversation endpoints: chat surface next to the canvas.

POST /messages enqueues an agent task (idempotent per message uuid) and
returns the task_id — the client then subscribes to /tasks/{id}/events.
"""

from __future__ import annotations

import os
import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..deps import (
    CurrentUser,
    DbDep,
    get_workspace_role,
    require_role,
    workspace_or_404,
)
from t2d_db import queue
from t2d_db.models import Conversation, Message, Task
from t2d_db.session import utcnow

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


class CreateRequest(BaseModel):
    workspace_id: int
    dashboard_id: int | None = None
    title: str | None = None


class MessageRequest(BaseModel):
    content: str
    locale: str = "zh"  # zh | en — Agent 面向用户的文字跟随该语言


def _conversation_or_404(db, conversation_id: int) -> Conversation:
    conversation = db.get(Conversation, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    return conversation


@router.post("")
def create(body: CreateRequest, user: CurrentUser, db: DbDep):
    workspace_or_404(db, body.workspace_id)
    role = get_workspace_role(db, user, body.workspace_id)
    require_role(role, "analyst")
    conversation = Conversation(
        workspace_id=body.workspace_id, user_id=user.id,
        dashboard_id=body.dashboard_id, title=body.title,
    )
    db.add(conversation)
    db.commit()
    return {"id": conversation.id, "dashboard_id": conversation.dashboard_id}


@router.get("/{conversation_id}/messages")
def list_messages(conversation_id: int, user: CurrentUser, db: DbDep):
    conversation = _conversation_or_404(db, conversation_id)
    get_workspace_role(db, user, conversation.workspace_id)
    rows = (
        db.query(Message)
        .filter(Message.conversation_id == conversation_id)
        .order_by(Message.seq)
        .all()
    )
    return [
        {"seq": r.seq, "role": r.role, "content": r.content,
         "task_id": r.task_id, "created_at": r.created_at.isoformat()}
        for r in rows
    ]


@router.post("/{conversation_id}/messages")
def send_message(conversation_id: int, body: MessageRequest, user: CurrentUser, db: DbDep):
    conversation = _conversation_or_404(db, conversation_id)
    if conversation.user_id != user.id:
        raise HTTPException(status_code=403, detail="只能在自己的会话中发送消息")
    role = get_workspace_role(db, user, conversation.workspace_id)
    require_role(role, "analyst")

    content = body.content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="消息不能为空")

    last_seq = (
        db.query(Message.seq)
        .filter(Message.conversation_id == conversation_id)
        .order_by(Message.seq.desc())
        .limit(1)
        .scalar()
    ) or 0
    message_idem = str(uuid.uuid4())
    message = Message(conversation_id=conversation_id, seq=last_seq + 1,
                      role="user", content=content)
    db.add(message)
    db.flush()

    locale = body.locale if body.locale in ("zh", "en") else "zh"
    task_type = "modify_dashboard" if conversation.dashboard_id else "build_dashboard"
    task_payload = {"content": content, "message_id": message.id, "locale": locale}

    # E3 dual-track: sqlite queue (1.0) or Temporal workflow (2.0)
    import yaml as _yaml
    from pathlib import Path as _Path
    _cfg_path = os.environ.get("AGENT_CONFIG_PATH",
        str(_Path(__file__).resolve().parents[3] / "config" / "agent" / "agent_config.yaml"))
    try:
        with open(_cfg_path) as _f:
            _queue_mode = (_yaml.safe_load(_f) or {}).get("agent", {}).get("queue", "sqlite")
    except OSError:
        _queue_mode = "sqlite"

    if _queue_mode == "temporal":
        # Create the task row (for SSE/snapshot) then start the Temporal workflow
        task = Task(
            idempotency_key=message_idem,
            type=task_type, status="queued",
            workspace_id=conversation.workspace_id,
            user_id=user.id,
            conversation_id=conversation_id,
            dashboard_id=conversation.dashboard_id,
            payload=task_payload,
        )
        db.add(task)
        db.flush()
        message.task_id = task.id
        db.commit()
        # Start the Temporal workflow (async, non-blocking)
        import threading
        def _start_wf():
            import asyncio
            from t2d_worker.temporal_worker import start_task_workflow
            try:
                asyncio.run(start_task_workflow(
                    task_id=task.id, task_type=task_type, payload=task_payload))
            except Exception as exc:
                # Workflow start failure → mark task failed
                from t2d_db.session import get_sessionmaker
                from t2d_db.models import Task as T
                with get_sessionmaker()() as s2:
                    t2 = s2.get(T, task.id)
                    if t2 and t2.status == "queued":
                        t2.status = "failed"
                        t2.error = {"code": "temporal_start_failed",
                                    "message": str(exc)[:200]}
                        s2.commit()
        threading.Thread(target=_start_wf, daemon=True).start()
    else:
        # 1.0 path: SQLite queue
        task = queue.enqueue(
            type=task_type,
            workspace_id=conversation.workspace_id,
            user_id=user.id,
            payload=task_payload,
            idempotency_key=message_idem,
            conversation_id=conversation_id,
            dashboard_id=conversation.dashboard_id,
            session=db,
        )
        message.task_id = task.id
        db.commit()
    return {"task_id": task.id, "message_seq": message.seq}
