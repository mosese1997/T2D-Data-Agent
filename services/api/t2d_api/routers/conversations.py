"""Conversation endpoints: chat surface next to the canvas.

POST /messages enqueues an agent task (idempotent per message uuid) and
returns the task_id — the client then subscribes to /tasks/{id}/events.
"""

from __future__ import annotations

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
from t2d_db.models import Conversation, Message
from t2d_db.session import utcnow

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


class CreateRequest(BaseModel):
    workspace_id: int
    dashboard_id: int | None = None
    title: str | None = None


class MessageRequest(BaseModel):
    content: str


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

    task = queue.enqueue(
        type="modify_dashboard" if conversation.dashboard_id else "build_dashboard",
        workspace_id=conversation.workspace_id,
        user_id=user.id,
        payload={"content": content, "message_id": message.id},
        idempotency_key=message_idem,
        conversation_id=conversation_id,
        dashboard_id=conversation.dashboard_id,
        session=db,
    )
    message.task_id = task.id
    db.commit()
    return {"task_id": task.id, "message_seq": message.seq}
