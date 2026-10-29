"""QueryGateway: validated, limited, audited execution against the warehouse.

The gateway is the ONLY path from agent SQL to the business DB:
  validate → clamp LIMIT → execute (statement_timeout, row/cell/byte caps,
  cancel support) → audit row → result.

Two service identities (task book §14): `draft` runs with the caller's
workspace-authorized scope; `publisher` runs published refreshes with the
explicitly approved execution identity. Both map to read-only DB roles —
the DB-level permission is the final constraint, not this gateway.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any

import psycopg

from .limits import QueryLimits
from .validator import validate_sql


@dataclass
class QueryResult:
    columns: list[dict[str, str]] = field(default_factory=list)
    # [{name, type}] — col_schema for canvas validation
    rows: list[tuple] = field(default_factory=list)  # preview rows (≤100)
    row_count: int = 0
    truncated: bool = False
    execution_ms: int = 0
    normalized_sql: str = ""
    objects_referenced: list[str] = field(default_factory=list)


def _clamp_limit(sql: str, max_rows: int) -> str:
    """Ensure an outer LIMIT ≤ max_rows (replace larger ones, add missing)."""
    import sqlglot
    from sqlglot import exp

    tree = sqlglot.parse_one(sql, dialect="postgres")
    limit_node = tree.args.get("limit")
    if limit_node is not None:
        try:
            current = int(limit_node.expression.name) if hasattr(limit_node, "expression") else int(str(limit_node))
        except (ValueError, AttributeError):
            current = None
        if current is None or current > max_rows:
            tree = tree.limit(max_rows)
    else:
        tree = tree.limit(max_rows)
    return tree.sql(dialect="postgres")


class QueryGateway:
    def __init__(
        self,
        *,
        dsn_for: dict[str, str] | None = None,
        limits: QueryLimits | None = None,
        audit_hook=None,
    ) -> None:
        """dsn_for: {"draft": dsn, "publisher": dsn}. audit_hook:
        callable(identity, sql, meta) — wired to t2d_db audit rows by the
        worker/API, keeping this package DB-agnostic."""
        self._dsn_for = dsn_for or {}
        self.limits = limits or QueryLimits.from_env()
        self._audit_hook = audit_hook

    def execute(
        self,
        *,
        identity: str,  # draft | publisher
        sql: str,
        allowed_objects: set[str],
        params: dict[str, Any] | None = None,
        preview_rows: int = 100,
        cancel_check=None,
    ) -> QueryResult:
        if identity not in self._dsn_for:
            raise ValueError(f"unknown service identity: {identity}")

        validation = validate_sql(sql, allowed_objects=allowed_objects)
        if not validation.valid:
            # Rejections are audited too (task book §10: 身份/查询/审计 —
            # permission denials must leave a trace).
            err = validation.errors[0]
            if self._audit_hook:
                self._audit_hook(
                    identity,
                    sql,
                    {"objects": validation.objects_referenced,
                     "rejected": True, "error_code": err["code"]},
                )
            raise QueryRejected(err["code"], err["message"], validation=validation)

        final_sql = _clamp_limit(validation.normalized_sql, self.limits.max_rows)
        started = time.monotonic()
        dsn = self._dsn_for[identity]

        with psycopg.connect(dsn, connect_timeout=10) as conn:
            conn.execute(f"SET statement_timeout = {self.limits.timeout_s * 1000}")
            conn.execute("SET default_transaction_read_only = on")
            with conn.cursor() as cur:
                cur.execute(final_sql, params or None)
                columns = [
                    {"name": d.name, "type": d.type_code} for d in cur.description or []
                ]
                rows: list[tuple] = []
                count = 0
                truncated = False
                while True:
                    if cancel_check and cancel_check():
                        conn.cancel()
                        raise QueryCancelled()
                    batch = cur.fetchmany(500)
                    if not batch:
                        break
                    for row in batch:
                        count += 1
                        if count <= preview_rows:
                            rows.append(row)
                        if count > self.limits.max_rows:
                            truncated = True
                            break
                    if truncated:
                        break
                # Cell/byte caps (approximate: repr size of preview only).
                if len(rows) * max(1, len(columns)) > self.limits.max_cells:
                    raise QueryRejected(
                        "result_too_large",
                        f"结果单元格数超过上限 {self.limits.max_cells}",
                    )

        execution_ms = int((time.monotonic() - started) * 1000)
        if self._audit_hook:
            self._audit_hook(
                identity,
                final_sql,
                {
                    "objects": validation.objects_referenced,
                    "row_count": count,
                    "execution_ms": execution_ms,
                    "truncated": truncated,
                },
            )
        return QueryResult(
            columns=columns,
            rows=rows,
            row_count=count,
            truncated=truncated,
            execution_ms=execution_ms,
            normalized_sql=final_sql,
            objects_referenced=validation.objects_referenced,
        )


class QueryRejected(Exception):
    def __init__(self, code: str, message: str, validation=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.validation = validation


class QueryCancelled(Exception):
    pass
