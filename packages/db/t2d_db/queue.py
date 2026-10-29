"""Persistent task queue primitives over the state DB (SQLite/MySQL alike).

Design (task book §11):
- Atomic claim: a single self-contained UPDATE ... WHERE id=(SELECT ...) —
  identical semantics on SQLite and MySQL (no SKIP LOCKED needed at demo
  scale; a MySQL dialect branch can add it later).
- Lease + heartbeat: the worker renews lease_expires_at every
  TASK_HEARTBEAT_SECONDS; a reaper returns expired running tasks to queued
  (resuming from checkpoint) or marks them interrupted when attempts are
  exhausted.
- Cancel: cooperative — the API sets cancel_requested; the runner checks it
  at step boundaries and tool entry points; dead tasks are finalized by the
  reaper.
- Idempotency: UNIQUE(idempotency_key) — duplicate submissions return the
  original task id.
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from .models import RunEvent, Task
from .session import get_sessionmaker, utcnow

LEASE_SECONDS = int(os.environ.get("TASK_LEASE_SECONDS", "30"))
HEARTBEAT_SECONDS = int(os.environ.get("TASK_HEARTBEAT_SECONDS", "10"))


@dataclass
class ClaimResult:
    task_id: int | None
    claimed: bool


def enqueue(
    *,
    type: str,
    workspace_id: int,
    user_id: int,
    payload: dict,
    idempotency_key: str | None = None,
    conversation_id: int | None = None,
    dashboard_id: int | None = None,
    priority: int = 100,
    session=None,
) -> Task:
    """Create a queued task; returns the existing one on idempotent replay."""
    key = idempotency_key or f"{type}:{uuid.uuid4()}"
    own_session = session is None
    if own_session:
        session = get_sessionmaker()()
    try:
        existing = session.query(Task).filter_by(idempotency_key=key).first()
        if existing:
            return existing
        task = Task(
            idempotency_key=key,
            type=type,
            status="queued",
            priority=priority,
            workspace_id=workspace_id,
            user_id=user_id,
            conversation_id=conversation_id,
            dashboard_id=dashboard_id,
            payload=payload,
        )
        session.add(task)
        # Flush to get the id and let IntegrityError surface here.
        session.flush()
        emit_event(session, task.id, "task.created", data={"task_id": task.id, "type": type})
        if own_session:
            session.commit()
        return task
    except IntegrityError:
        # Concurrent duplicate submission — return the winner's row.
        session.rollback()
        return session.query(Task).filter_by(idempotency_key=key).one()
    finally:
        if own_session:
            session.close()


def claim_next(worker_id: str, *, task_types: list[str] | None = None) -> ClaimResult:
    """Claim the oldest queued, non-cancelled task (optimistic, dialect-identical).

    Two-step claim: pick a candidate id, then UPDATE guarded by
    status='queued'. Exactly one racing worker gets rowcount==1; losers
    retry with the next candidate. At demo scale (single worker process,
    a few slots) this is contention-free and behaves identically on
    SQLite and MySQL.
    """
    maker = get_sessionmaker()
    with maker() as session:
        for _ in range(5):  # bounded retries against races
            q = (
                select(Task.id)
                .where(Task.status == "queued", Task.cancel_requested.is_(False))
                .order_by(Task.priority, Task.created_at, Task.id)
                .limit(1)
            )
            if task_types:
                q = q.where(Task.type.in_(task_types))
            candidate = session.execute(q).scalar()
            if candidate is None:
                return ClaimResult(task_id=None, claimed=False)
            stmt = (
                update(Task)
                .where(Task.id == candidate, Task.status == "queued")
                .values(
                    status="running",
                    lease_owner=worker_id,
                    lease_expires_at=utcnow() + timedelta(seconds=LEASE_SECONDS),
                    heartbeat_at=utcnow(),
                    attempt_count=Task.attempt_count + 1,
                    started_at=func.coalesce(Task.started_at, utcnow()),
                )
            )
            result = session.execute(stmt)
            session.commit()
            if result.rowcount == 1:
                return ClaimResult(task_id=candidate, claimed=True)
        return ClaimResult(task_id=None, claimed=False)


def heartbeat(task_id: int, worker_id: str) -> None:
    """Renew the lease — called from the worker's heartbeat thread."""
    maker = get_sessionmaker()
    with maker() as session:
        session.execute(
            update(Task)
            .where(Task.id == task_id, Task.lease_owner == worker_id)
            .values(
                lease_expires_at=utcnow() + timedelta(seconds=LEASE_SECONDS),
                heartbeat_at=utcnow(),
            )
        )
        session.commit()


def request_cancel(task_id: int) -> None:
    """Cooperative cancel: flag it; the runner notices at the next boundary."""
    maker = get_sessionmaker()
    with maker() as session:
        session.execute(update(Task).where(Task.id == task_id).values(cancel_requested=True))
        session.commit()


def reap_expired() -> list[int]:
    """Finalize expired leases: requeue (resume from checkpoint) or interrupt.

    Returns the ids of tasks whose status changed.
    """
    maker = get_sessionmaker()
    now = utcnow()
    changed: list[int] = []
    with maker() as session:
        expired = (
            session.query(Task)
            .filter(Task.status == "running", Task.lease_expires_at < now)
            .all()
        )
        for task in expired:
            if task.cancel_requested:
                task.status = "cancelled"
                task.finished_at = now
            elif task.attempt_count < task.max_attempts:
                task.status = "queued"
                task.lease_owner = None
                task.lease_expires_at = None
            else:
                task.status = "interrupted"
                task.error = {"code": "lease_expired", "message": "租约过期且重试耗尽"}
                task.finished_at = now
            changed.append(task.id)
        session.commit()
    return changed


def emit_event(session, task_id: int, event_type: str, *, phase: str | None = None, data: dict | None = None) -> int:
    """Append a run event with the next per-task seq (the SSE cursor)."""
    last = (
        session.query(RunEvent.seq)
        .filter(RunEvent.task_id == task_id)
        .order_by(RunEvent.seq.desc())
        .limit(1)
        .scalar()
    )
    event = RunEvent(
        task_id=task_id,
        seq=(last or 0) + 1,
        event_type=event_type,
        phase=phase,
        data=data or {},
    )
    session.add(event)
    return event.seq
