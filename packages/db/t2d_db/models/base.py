"""Shared declarative base and column conventions.

MySQL 8.0 / SQLite dual-dialect rules (CLAUDE.md rule 4) live here so every
model inherits them:
- BigInteger PK with Integer variant on SQLite (autoincrement rowid alias).
- String columns always carry explicit lengths.
- Timestamps are naive UTC (session.utcnow).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from ..session import utcnow


class Base(DeclarativeBase):
    pass


def big_int_pk() -> Mapped[int]:
    """Autoincrement PK that works on both MySQL and SQLite."""
    return mapped_column(
        BigInteger().with_variant(Integer(), "sqlite"),
        primary_key=True,
        autoincrement=True,
    )


def bigint_fk(target: str, *, nullable: bool = False) -> Mapped[int]:
    """BigInteger foreign key (Integer variant on SQLite)."""
    return mapped_column(
        BigInteger().with_variant(Integer(), "sqlite"),
        ForeignKey(target),
        nullable=nullable,
    )


def int_col(*, nullable: bool = False, **kw) -> Mapped[int]:
    """Plain Integer column (revisions, seq numbers, counters)."""
    return mapped_column(Integer(), nullable=nullable, **kw)


class CreatedAtMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(), nullable=False, default=utcnow
    )


class UpdatedAtMixin:
    # No ON UPDATE CURRENT_TIMESTAMP — the ORM owns updated_at.
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(), nullable=False, default=utcnow, onupdate=utcnow
    )


def str32(**kw) -> Mapped[str]:
    """Status/enum-like column: String(32) + app-layer validation."""
    return mapped_column(String(32), nullable=False, **kw)


def str64(**kw) -> Mapped[str]:
    return mapped_column(String(64), nullable=False, **kw)


def str255(**kw) -> Mapped[str]:
    return mapped_column(String(255), nullable=False, **kw)
