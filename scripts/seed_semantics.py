#!/usr/bin/env python3
"""Seed the semantic layer into the state DB (projection of the YAML truth).

The YAML under config/semantics/ is authoritative; these rows power
structured reads (get_semantic_definition) and the admin Wiki page.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from semantic import load_semantics
from t2d_db.models import JoinRule, Metric, Term
from t2d_db.session import get_sessionmaker

CONFIG_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "semantics"
)


def main() -> None:
    registry = load_semantics(CONFIG_DIR)
    maker = get_sessionmaker()
    with maker() as session:
        for m in registry.metrics.values():
            row = session.query(Metric).filter_by(metric_key=m.metric_key).first()
            values = dict(
                metric_key=m.metric_key, name=m.name, synonyms=m.synonyms,
                description=m.description, expression=m.expression,
                base_dataset=m.base_dataset, grain=m.grain, time_field=m.time_field,
                exclusions=m.exclusions, currency_policy=m.currency_policy,
                fx_date_rule=m.fx_date_rule, available_dimensions=m.available_dimensions,
                allowed_joins=m.allowed_joins, version=m.version, status=m.status,
            )
            if row is None:
                session.add(Metric(**values))
            else:
                for k, v in values.items():
                    setattr(row, k, v)

        for t in registry.terms.values():
            row = session.query(Term).filter_by(term=t.term).first()
            values = dict(term=t.term, aliases=t.aliases, definition=t.definition,
                          ref_metric_key=t.ref_metric, ref_dataset=t.ref_dataset)
            if row is None:
                session.add(Term(**values))
            else:
                for k, v in values.items():
                    setattr(row, k, v)

        for j in registry.join_rules.values():
            row = session.query(JoinRule).filter_by(rule_key=j.rule_key).first()
            values = dict(
                rule_key=j.rule_key, left_dataset=j.left_dataset,
                right_dataset=j.right_dataset, join_type=j.join_type,
                join_keys=j.join_keys, cardinality=j.cardinality,
                is_valid=True, notes=j.notes,
            )
            if row is None:
                session.add(JoinRule(**values))
            else:
                for k, v in values.items():
                    setattr(row, k, v)
        session.commit()

        print(f"✅ 语义入库: {session.query(Metric).count()} 指标, "
              f"{session.query(Term).count()} 术语, "
              f"{session.query(JoinRule).count()} 关联规则 "
              f"(semantic_version={registry.version})")


if __name__ == "__main__":
    main()
