"""YAML → SemanticRegistry. The YAML files are the source of truth; the
state DB rows and the retrieval index are projections of this."""

from __future__ import annotations

from pathlib import Path

import yaml

from .models import JoinRuleDef, MetricDef, SemanticBundle, TermDef


class SemanticRegistry:
    """In-memory view of one semantic version, keyed for fast lookup."""

    def __init__(self, bundle: SemanticBundle) -> None:
        self.bundle = bundle
        self.metrics = {m.metric_key: m for m in bundle.metrics}
        self.terms = {t.term: t for t in bundle.terms}
        self.join_rules = {j.rule_key: j for j in bundle.join_rules}

    @property
    def version(self) -> str:
        return self.bundle.semantic_version

    def metric(self, key: str) -> MetricDef | None:
        return self.metrics.get(key)

    def active_metrics(self) -> list[MetricDef]:
        return [m for m in self.metrics.values() if m.status == "active"]

    def datasets_for(self, metric_keys: list[str]) -> set[str]:
        """Base datasets of the given metrics — intersected with the
        workspace's authorized datasets by the caller."""
        return {self.metrics[k].base_dataset for k in metric_keys if k in self.metrics}


def load_semantics(config_dir: str | Path) -> SemanticRegistry:
    """Load metrics.yaml / terms.yaml / join_rules.yaml / datasets.yaml."""
    config_dir = Path(config_dir)
    with (config_dir / "metrics.yaml").open(encoding="utf-8") as f:
        metrics_raw = yaml.safe_load(f) or {"metrics": []}
    with (config_dir / "terms.yaml").open(encoding="utf-8") as f:
        terms_raw = yaml.safe_load(f) or {"terms": []}
    with (config_dir / "join_rules.yaml").open(encoding="utf-8") as f:
        joins_raw = yaml.safe_load(f) or {"join_rules": []}
    datasets_path = config_dir / "datasets.yaml"
    datasets = {}
    semantic_version = "1"
    if datasets_path.exists():
        with datasets_path.open(encoding="utf-8") as f:
            ds_raw = yaml.safe_load(f) or {}
        datasets = ds_raw.get("datasets", {})
        semantic_version = str(ds_raw.get("semantic_version", "1"))

    bundle = SemanticBundle(
        semantic_version=semantic_version,
        metrics=[MetricDef.model_validate(m) for m in metrics_raw.get("metrics", [])],
        terms=[TermDef.model_validate(t) for t in terms_raw.get("terms", [])],
        join_rules=[JoinRuleDef.model_validate(j) for j in joins_raw.get("join_rules", [])],
        datasets=datasets,
    )
    return SemanticRegistry(bundle)
