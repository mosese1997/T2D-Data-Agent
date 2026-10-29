"""Semantic layer state: metrics, business terms, join rules.

The YAML files under config/semantics/ are the source of truth; these rows
are the queryable projection seeded by scripts/seed_semantics.py. The
retriever (CSS or local) discovers candidates; these structured rows are
what the agent reads for authoritative definitions — similarity never
decides permissions or formulas.
"""

from __future__ import annotations

from sqlalchemy import JSON, BigInteger, Boolean, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, CreatedAtMixin, UpdatedAtMixin, bigint_fk, big_int_pk, str32, str64


class Metric(Base, CreatedAtMixin, UpdatedAtMixin):
    __tablename__ = "metrics"

    id: Mapped[int] = big_int_pk()
    metric_key: Mapped[str] = str64(unique=True)  # e.g. gmv, refund_amount
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    synonyms: Mapped[dict] = mapped_column(JSON(), nullable=False, default=list)
    description: Mapped[str] = mapped_column(Text(), nullable=False)
    # measure expression (SQL fragment over base_dataset) or controlled calc
    expression: Mapped[str] = mapped_column(Text(), nullable=False)
    base_dataset: Mapped[str] = str64()  # e.g. orders / order_items
    grain: Mapped[str] = str32()  # order | item | day
    time_field: Mapped[str] = str64()  # e.g. created_at
    exclusions: Mapped[dict] = mapped_column(JSON(), nullable=False, default=list)
    currency_policy: Mapped[str] = str32(default="local")  # local | usd_fixed
    fx_date_rule: Mapped[str] = str32(default="order_date")  # order_date | snapshot
    available_dimensions: Mapped[dict] = mapped_column(JSON(), nullable=False, default=list)
    allowed_joins: Mapped[dict] = mapped_column(JSON(), nullable=False, default=list)
    version: Mapped[int] = str32(default="1")  # semantic version tag
    status: Mapped[str] = str32(default="active")  # draft | active | deprecated
    owner_id: Mapped[int | None] = bigint_fk("users.id", nullable=True)


class Term(Base, CreatedAtMixin):
    __tablename__ = "terms"

    id: Mapped[int] = big_int_pk()
    term: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    aliases: Mapped[dict] = mapped_column(JSON(), nullable=False, default=list)
    definition: Mapped[str] = mapped_column(Text(), nullable=False)
    ref_metric_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ref_dataset: Mapped[str | None] = mapped_column(String(64), nullable=True)


class JoinRule(Base, CreatedAtMixin):
    __tablename__ = "join_rules"

    id: Mapped[int] = big_int_pk()
    rule_key: Mapped[str] = str64(unique=True)
    left_dataset: Mapped[str] = str64()
    right_dataset: Mapped[str] = str64()
    join_type: Mapped[str] = str32()  # inner | left
    join_keys: Mapped[dict] = mapped_column(JSON(), nullable=False, default=dict)
    cardinality: Mapped[str] = str32()  # 1:1 | 1:N | N:1
    is_valid: Mapped[bool] = mapped_column(Boolean(), nullable=False, default=True)
    notes: Mapped[str | None] = mapped_column(Text(), nullable=True)
