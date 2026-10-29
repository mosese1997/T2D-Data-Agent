"""Publishing, approvals, sharing, refresh schedules.

Simplified publish rules (task book §14):
- Publishing creates an immutable version; later edits stay in draft;
  re-publishing creates a new published version.
- Changed SQL / data source / audience requires re-approval.
- A share grants access to the dashboard VIEW only — never underlying data
  permissions (share tokens never enter any tool context).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, CreatedAtMixin, bigint_fk, big_int_pk, str32, str64


class Publication(Base, CreatedAtMixin):
    __tablename__ = "publications"
    __table_args__ = (Index("ix_publications_dashboard", "dashboard_id", "id"),)

    id: Mapped[int] = big_int_pk()
    dashboard_id: Mapped[int] = bigint_fk("dashboards.id")
    version_id: Mapped[int] = bigint_fk("dashboard_versions.id")
    target_workspace_id: Mapped[int] = bigint_fk("workspaces.id")
    status: Mapped[str] = str32(default="pending")  # pending | published | rolled_back
    requested_by: Mapped[int] = bigint_fk("users.id")
    approved_by: Mapped[int | None] = bigint_fk("users.id", nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)


class Approval(Base, CreatedAtMixin):
    __tablename__ = "approvals"

    id: Mapped[int] = big_int_pk()
    request_type: Mapped[str] = str64()  # publish | source_change
    request_id: Mapped[int] = bigint_fk("publications.id")
    requester_id: Mapped[int] = bigint_fk("users.id")
    approver_id: Mapped[int | None] = bigint_fk("users.id", nullable=True)
    status: Mapped[str] = str32(default="pending")  # pending | approved | rejected
    comment: Mapped[str | None] = mapped_column(Text(), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)


class Share(Base, CreatedAtMixin):
    __tablename__ = "shares"

    id: Mapped[int] = big_int_pk()
    dashboard_id: Mapped[int] = bigint_fk("dashboards.id")
    version_id: Mapped[int | None] = bigint_fk("dashboard_versions.id", nullable=True)
    share_token: Mapped[str] = str64(unique=True)  # random, URL-safe
    granted_by: Mapped[int] = bigint_fk("users.id")
    grant_to_user_id: Mapped[int | None] = bigint_fk("users.id", nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)


class RefreshSchedule(Base, CreatedAtMixin):
    __tablename__ = "refresh_schedules"

    id: Mapped[int] = big_int_pk()
    dashboard_id: Mapped[int] = bigint_fk("dashboards.id")
    cron: Mapped[str] = mapped_column(String(64), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean(), nullable=False, default=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)
    created_by: Mapped[int] = bigint_fk("users.id")
