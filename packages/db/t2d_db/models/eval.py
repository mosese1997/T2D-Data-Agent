"""Evaluation runs and per-case results (fixed 40-case set, task book §18)."""

from __future__ import annotations

from sqlalchemy import JSON, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, CreatedAtMixin, bigint_fk, big_int_pk, str32, str64


class EvalRun(Base, CreatedAtMixin):
    __tablename__ = "eval_runs"

    id: Mapped[int] = big_int_pk()
    case_set: Mapped[str] = str64()  # full | smoke | category name
    summary: Mapped[dict] = mapped_column(
        JSON(), nullable=False, default=dict
    )  # {total, passed, failed, accuracy}
    triggered_by: Mapped[int | None] = bigint_fk("users.id", nullable=True)


class EvalCaseResult(Base, CreatedAtMixin):
    __tablename__ = "eval_case_results"
    __table_args__ = (Index("ix_evalresults_run", "eval_run_id", "case_id"),)

    id: Mapped[int] = big_int_pk()
    eval_run_id: Mapped[int] = bigint_fk("eval_runs.id")
    case_id: Mapped[str] = str64()
    status: Mapped[str] = str32()  # passed | failed | error
    expected: Mapped[dict] = mapped_column(JSON(), nullable=False, default=dict)
    actual: Mapped[dict] = mapped_column(JSON(), nullable=False, default=dict)
    task_id: Mapped[int | None] = bigint_fk("tasks.id", nullable=True)
