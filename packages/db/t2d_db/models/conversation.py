"""Conversations and messages (the chat surface next to the canvas)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, CreatedAtMixin, bigint_fk, big_int_pk, int_col, str32


class Conversation(Base, CreatedAtMixin):
    __tablename__ = "conversations"

    id: Mapped[int] = big_int_pk()
    workspace_id: Mapped[int] = bigint_fk("workspaces.id")
    user_id: Mapped[int] = bigint_fk("users.id")
    dashboard_id: Mapped[int | None] = bigint_fk(
        "dashboards.id", nullable=True,
        name="fk_conversations_dashboard", use_alter=True,
    )
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = str32(default="active")  # active | archived


class Message(Base, CreatedAtMixin):
    __tablename__ = "messages"
    __table_args__ = (UniqueConstraint("conversation_id", "seq", name="uq_message_seq"),)

    id: Mapped[int] = big_int_pk()
    conversation_id: Mapped[int] = bigint_fk("conversations.id")
    seq: Mapped[int] = int_col()  # per-conversation monotonic
    role: Mapped[str] = str32()  # user | assistant
    content: Mapped[str] = mapped_column(Text(), nullable=False)
    task_id: Mapped[int | None] = bigint_fk("tasks.id", nullable=True)
