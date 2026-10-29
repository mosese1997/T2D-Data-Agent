"""Identity & authorization: users, workspaces, membership, dataset grants.

workspace_datasets is the root of data permission isolation: a workspace is
only ever allowed to query datasets listed here, and the query gateway
enforces it against the semantic layer's base_dataset.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, CreatedAtMixin, bigint_fk, big_int_pk, str32, str64


class User(Base, CreatedAtMixin):
    __tablename__ = "users"

    id: Mapped[int] = big_int_pk()
    # Lowercase-normalized on write: MySQL default collation is
    # case-insensitive, SQLite is not — normalize in the app layer.
    username: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    # argon2 hash; demo accounts seeded by scripts/seed_demo_users.py
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean(), nullable=False, default=True)

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "username": self.username,
            "display_name": self.display_name,
        }


class Workspace(Base, CreatedAtMixin):
    __tablename__ = "workspaces"

    id: Mapped[int] = big_int_pk()
    slug: Mapped[str] = str64(unique=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    type: Mapped[str] = str32()  # personal | business
    created_by: Mapped[int] = bigint_fk("users.id")


class WorkspaceMember(Base):
    __tablename__ = "workspace_members"
    __table_args__ = (UniqueConstraint("workspace_id", "user_id", name="uq_member"),)

    id: Mapped[int] = big_int_pk()
    workspace_id: Mapped[int] = bigint_fk("workspaces.id")
    user_id: Mapped[int] = bigint_fk("users.id")
    role: Mapped[str] = str32()  # admin | analyst | viewer


class WorkspaceDataset(Base):
    """Dataset grant whitelist — the root of permission isolation."""

    __tablename__ = "workspace_datasets"
    __table_args__ = (UniqueConstraint("workspace_id", "dataset_name", name="uq_dataset"),)

    id: Mapped[int] = big_int_pk()
    workspace_id: Mapped[int] = bigint_fk("workspaces.id")
    dataset_name: Mapped[str] = str64()  # e.g. orders, order_items, fx_rates
    granted: Mapped[bool] = mapped_column(Boolean(), nullable=False, default=True)
    granted_at: Mapped[datetime] = mapped_column(DateTime(), nullable=False)
    note: Mapped[str | None] = mapped_column(Text(), nullable=True)
