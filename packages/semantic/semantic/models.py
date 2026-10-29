"""Pydantic models for the semantic layer (YAML source of truth)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class MetricDef(BaseModel):
    metric_key: str
    name: str
    synonyms: list[str] = Field(default_factory=list)
    description: str
    # SQL measure expression over base_dataset (may reference columns).
    expression: str
    base_dataset: str
    grain: str = "order"  # order | item | day
    time_field: str = "created_at"
    exclusions: list[str] = Field(default_factory=list)
    # e.g. ["status != 'cancelled'", "refund handled by refund_amount"]
    currency_policy: str = "local"  # local | usd_fixed
    fx_date_rule: str = "order_date"  # order_date | snapshot
    available_dimensions: list[str] = Field(default_factory=list)
    allowed_joins: list[str] = Field(default_factory=list)  # join rule keys
    version: str = "1"
    status: str = "active"  # draft | active | deprecated
    owner: str = ""


class TermDef(BaseModel):
    term: str
    aliases: list[str] = Field(default_factory=list)
    definition: str
    ref_metric: str | None = None
    ref_dataset: str | None = None


class JoinRuleDef(BaseModel):
    rule_key: str
    left_dataset: str
    right_dataset: str
    join_type: str = "left"  # inner | left
    join_keys: dict[str, str] = Field(default_factory=dict)  # left_col -> right_col
    cardinality: str = "1:N"
    notes: str = ""


class SemanticBundle(BaseModel):
    """Everything loaded from config/semantics/*.yaml in one versioned bag."""

    semantic_version: str
    metrics: list[MetricDef]
    terms: list[TermDef]
    join_rules: list[JoinRuleDef]
    datasets: dict[str, dict] = Field(default_factory=dict)
    # dataset_name -> {grain, primary_key, time_field, description, columns: {col: comment}}
