"""File references and audit logs.

file_refs rows point at stored artifacts (source result sets, analysis
reports, exports) in the FileStore adapter (OBS or local volume). Temporary
objects carry expires_at for the cleanup policy.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, CreatedAtMixin, bigint_fk, big_int_pk, str32, str64


class FileRef(Base, CreatedAtMixin):
    __tablename__ = "file_refs"

    id: Mapped[int] = big_int_pk()
    kind: Mapped[str] = str64()  # source_result | analysis_report | export
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    mime: Mapped[str] = mapped_column(String(128), nullable=False, default="application/json")
    size_bytes: Mapped[int] = mapped_column(Integer(), nullable=False, default=0)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    workspace_id: Mapped[int | None] = bigint_fk("workspaces.id", nullable=True)
    created_by: Mapped[int | None] = bigint_fk("users.id", nullable=True)
    task_id: Mapped[int | None] = bigint_fk("tasks.id", nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)


class AuditLog(Base, CreatedAtMixin):
    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_actor_time", "actor_user_id", "created_at"),)

    id: Mapped[int] = big_int_pk()
    actor_user_id: Mapped[int | None] = bigint_fk("users.id", nullable=True)
    action: Mapped[str] = str64()  # query.execute | patch.apply | publish | ...
    object_type: Mapped[str] = str64()
    object_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # {sql, params, identity, objects, row_count, latency_ms, result_ref, ...}
    detail: Mapped[dict] = mapped_column(JSON(), nullable=False, default=dict)
