"""Dashboards, immutable versions, and candidate patches.

Versioning model (task book §12):
- A dashboard points at current_version_id; every Apply creates a new
  dashboard_versions row atomically (single transaction).
- A patch records the base_revision it was generated against; applying a
  patch whose base_revision no longer equals the current revision must fail
  with status=conflict and require regeneration.
- A version snapshots the source bindings + semantic version so restoring a
  historical definition never silently re-points at moved data. Restoring a
  definition does NOT restore historical data — result snapshots are shown
  separately via file_refs.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import (
    Base,
    CreatedAtMixin,
    UpdatedAtMixin,
    bigint_fk,
    big_int_pk,
    int_col,
    str32,
)


class Dashboard(Base, CreatedAtMixin, UpdatedAtMixin):
    __tablename__ = "dashboards"

    id: Mapped[int] = big_int_pk()
    workspace_id: Mapped[int] = bigint_fk("workspaces.id")
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    current_version_id: Mapped[int | None] = bigint_fk(
        "dashboard_versions.id", nullable=True
    )
    status: Mapped[str] = str32(default="draft")  # draft | published | archived
    created_by: Mapped[int] = bigint_fk("users.id")


class DashboardVersion(Base, CreatedAtMixin):
    __tablename__ = "dashboard_versions"
    __table_args__ = (Index("ix_versions_dashboard_rev", "dashboard_id", "revision"),)

    id: Mapped[int] = big_int_pk()
    dashboard_id: Mapped[int] = bigint_fk("dashboards.id")
    revision: Mapped[int] = int_col()  # monotonically increasing per dashboard
    canvas_json: Mapped[dict] = mapped_column(JSON(), nullable=False)
    # {source_id: {semantic_version, created_by, task_id}} per bound source
    source_snapshot: Mapped[dict] = mapped_column(JSON(), nullable=False, default=dict)
    base_revision: Mapped[int | None] = int_col(nullable=True)
    change_summary: Mapped[str | None] = mapped_column(Text(), nullable=True)
    created_by: Mapped[int] = bigint_fk("users.id")
    task_id: Mapped[int | None] = bigint_fk("tasks.id", nullable=True)


class DashboardPatch(Base, CreatedAtMixin):
    __tablename__ = "dashboard_patches"
    __table_args__ = (Index("ix_patches_dashboard_status", "dashboard_id", "status"),)

    id: Mapped[int] = big_int_pk()
    dashboard_id: Mapped[int] = bigint_fk("dashboards.id")
    base_revision: Mapped[int] = int_col()
    patch_json: Mapped[dict] = mapped_column(JSON(), nullable=False)
    diff_summary: Mapped[str | None] = mapped_column(Text(), nullable=True)
    # proposed -> validated -> applied | rejected | conflict | expired
    status: Mapped[str] = str32(default="proposed")
    proposed_by: Mapped[int] = bigint_fk("users.id")
    task_id: Mapped[int | None] = bigint_fk("tasks.id", nullable=True)
    applied_version_id: Mapped[int | None] = bigint_fk(
        "dashboard_versions.id", nullable=True
    )
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)
