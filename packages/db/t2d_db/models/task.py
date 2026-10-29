"""Task runtime state: queue rows, checkpoints, run events, trace tables.

Task statuses (task book §11):
  queued → running → waiting_for_user → running → …
  running → waiting_for_apply → succeeded
  any → failed | cancelled | interrupted

run_events.seq is the SSE resume cursor: clients reconnect with
Last-Event-ID=<seq> and the server replays seq > last. Events carry real
phases and tool summaries only — never model hidden reasoning (raw detail
lives in tool_calls/agent_runs for the admin Trace page).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, CreatedAtMixin, bigint_fk, big_int_pk, int_col, str32, str64


class Task(Base, CreatedAtMixin):
    __tablename__ = "tasks"
    __table_args__ = (
        Index("ix_tasks_status_priority", "status", "priority", "created_at"),
        Index("ix_tasks_lease", "status", "lease_expires_at"),
    )

    id: Mapped[int] = big_int_pk()
    # UNIQUE: re-submitting the same message returns the original task
    idempotency_key: Mapped[str] = mapped_column(
        String(128), nullable=False, unique=True
    )
    type: Mapped[str] = str32()  # build_dashboard | modify_dashboard | analysis | refresh
    status: Mapped[str] = str32(default="queued")  # see docstring
    priority: Mapped[int] = int_col(default=100)
    workspace_id: Mapped[int] = bigint_fk("workspaces.id")
    user_id: Mapped[int] = bigint_fk("users.id")
    conversation_id: Mapped[int | None] = bigint_fk("conversations.id", nullable=True)
    dashboard_id: Mapped[int | None] = bigint_fk("dashboards.id", nullable=True)
    payload: Mapped[dict] = mapped_column(JSON(), nullable=False, default=dict)
    result: Mapped[dict | None] = mapped_column(JSON(), nullable=True)
    error: Mapped[dict | None] = mapped_column(JSON(), nullable=True)
    attempt_count: Mapped[int] = int_col(default=0)
    max_attempts: Mapped[int] = int_col(default=3)
    # lease / heartbeat
    lease_owner: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)
    cancel_requested: Mapped[bool] = mapped_column(Boolean(), nullable=False, default=False)
    # latest checkpoint {step, state} — history in task_checkpoints
    checkpoint: Mapped[dict | None] = mapped_column(JSON(), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)


class TaskCheckpoint(Base, CreatedAtMixin):
    __tablename__ = "task_checkpoints"
    __table_args__ = (Index("ix_checkpoints_task", "task_id", "id"),)

    id: Mapped[int] = big_int_pk()
    task_id: Mapped[int] = bigint_fk("tasks.id")
    step: Mapped[str] = str64()  # e.g. semantic_search, query_executed, patch_proposed
    state_json: Mapped[dict] = mapped_column(JSON(), nullable=False, default=dict)


class RunEvent(Base, CreatedAtMixin):
    __tablename__ = "run_events"
    __table_args__ = (Index("ix_events_task_seq", "task_id", "seq"),)

    id: Mapped[int] = big_int_pk()
    task_id: Mapped[int] = bigint_fk("tasks.id")
    seq: Mapped[int] = int_col()  # per-task monotonic — the SSE cursor
    event_type: Mapped[str] = str64()  # task.status_changed | phase.started | ...
    phase: Mapped[str | None] = mapped_column(String(64), nullable=True)
    data: Mapped[dict] = mapped_column(JSON(), nullable=False, default=dict)


class ToolCall(Base, CreatedAtMixin):
    """Trace detail: every tool invocation with input/output and latency."""

    __tablename__ = "tool_calls"
    __table_args__ = (Index("ix_toolcalls_task_seq", "task_id", "seq"),)

    id: Mapped[int] = big_int_pk()
    task_id: Mapped[int] = bigint_fk("tasks.id")
    seq: Mapped[int] = int_col()
    agent_name: Mapped[str] = str64()  # main | query | analysis
    tool_name: Mapped[str] = str64()
    input_json: Mapped[dict] = mapped_column(JSON(), nullable=False, default=dict)
    output_json: Mapped[dict | None] = mapped_column(JSON(), nullable=True)
    status: Mapped[str] = str32(default="ok")  # ok | error | denied
    error: Mapped[str | None] = mapped_column(Text(), nullable=True)
    latency_ms: Mapped[int] = int_col(default=0)


class AgentRun(Base):
    """Trace tree: main agent → spawned sub-agents, with token budgets."""

    __tablename__ = "agent_runs"
    __table_args__ = (Index("ix_agentruns_task", "task_id", "id"),)

    id: Mapped[int] = big_int_pk()
    task_id: Mapped[int] = bigint_fk("tasks.id")
    parent_run_id: Mapped[int | None] = bigint_fk("agent_runs.id", nullable=True)
    agent_name: Mapped[str] = str64()  # main | query | analysis
    runtime: Mapped[str] = str32()  # toolloop | swarmflow
    model: Mapped[str] = str64()
    prompt_version: Mapped[str] = str32(default="1")
    token_usage: Mapped[dict] = mapped_column(JSON(), nullable=False, default=dict)
    status: Mapped[str] = str32(default="running")  # running | succeeded | failed | cancelled
    started_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)
