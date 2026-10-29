"""Sources: a saved, parameterized query plus its result reference.

A Source is the only way a dashboard component gets data. It stores the SQL,
params, column schema, caliber notes (口径说明), semantic references and a
file_refs pointer to the full result set (preview rows live in the file,
not in the state DB).
"""

from __future__ import annotations

from sqlalchemy import JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, CreatedAtMixin, bigint_fk, big_int_pk, int_col, str32


class Source(Base, CreatedAtMixin):
    __tablename__ = "sources"

    id: Mapped[int] = big_int_pk()
    workspace_id: Mapped[int] = bigint_fk("workspaces.id")
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    sql_text: Mapped[str] = mapped_column(Text(), nullable=False)
    params_json: Mapped[dict] = mapped_column(JSON(), nullable=False, default=dict)
    # [{metric_key, version}] — which semantic definitions this source used
    semantic_refs: Mapped[dict] = mapped_column(JSON(), nullable=False, default=dict)
    # human-readable caliber notes: exclusions, timezone, fx rule, week rule
    caliber_notes: Mapped[dict] = mapped_column(JSON(), nullable=False, default=dict)
    # [{name, type, comment}] — result column schema for canvas validation
    col_schema: Mapped[dict] = mapped_column(JSON(), nullable=False, default=list)
    row_count: Mapped[int] = int_col()
    result_file_id: Mapped[int | None] = bigint_fk("file_refs.id", nullable=True)
    status: Mapped[str] = str32(default="active")  # active | stale | failed
    created_by: Mapped[int] = bigint_fk("users.id")
    task_id: Mapped[int | None] = bigint_fk("tasks.id", nullable=True)
