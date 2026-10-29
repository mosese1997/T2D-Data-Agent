"""Demo-mode warehouse: local Postgres simulating DWS (GaussDB is PG-family).

Read-only enforcement happens at three layers: the query gateway's
validator, `SET default_transaction_read_only = on` per connection, and the
demo DB role's own grants (final constraint).
"""

from __future__ import annotations

import os

import psycopg

from ..base import AdapterError, DataWarehouse


class PostgresDataWarehouse(DataWarehouse):
    is_demo = True

    def __init__(self, *, host: str | None = None, port: int | None = None,
                 database: str | None = None, user: str | None = None,
                 password: str | None = None) -> None:
        self.host = host or os.environ.get("DEMO_PG_HOST", "localhost")
        self.port = port or int(os.environ.get("DEMO_PG_PORT", "5434"))
        self.database = database or os.environ.get("DEMO_PG_DATABASE", "t2d_biz")
        self.user = user or os.environ.get("DEMO_PG_USER", "t2d")
        self.password = password or os.environ.get("DEMO_PG_PASSWORD", "t2d-demo-only")

    def dsn_for(self, identity: str) -> str:
        if identity not in ("draft", "publisher"):
            raise ValueError(f"unknown service identity: {identity}")
        # Demo mode: both identities map to the same read-only demo role.
        # Production DWS maps them to t2d_draft / t2d_publisher roles.
        return (
            f"host={self.host} port={self.port} dbname={self.database} "
            f"user={self.user} password={self.password}"
        )

    def authorized_schema(self, datasets: list[str]) -> dict:
        result: dict = {}
        for dataset in datasets:
            try:
                with psycopg.connect(self.dsn_for("draft"), connect_timeout=10) as conn:
                    rows = conn.execute(
                        """
                        SELECT column_name, data_type,
                               col_description((quote_ident(%s) || '.' || quote_ident(%s))::regclass::oid,
                                               ordinal_position)
                        FROM information_schema.columns
                        WHERE table_schema = 'public' AND table_name = %s
                        ORDER BY ordinal_position
                        """,
                        ("public", dataset, dataset),
                    ).fetchall()
                    estimate = conn.execute(
                        "SELECT GREATEST(reltuples::bigint, 0) FROM pg_class "
                        "WHERE oid = (quote_ident('public') || '.' || quote_ident(%s))::regclass::oid",
                        (dataset,),
                    ).fetchone()
                result[dataset] = {
                    "columns": [
                        {"name": name, "type": dtype, "comment": comment or ""}
                        for name, dtype, comment in rows
                    ],
                    "row_estimate": int(estimate[0]) if estimate else 0,
                }
            except psycopg.Error as exc:
                raise AdapterError(f"无法读取数据集 {dataset} 的结构: {exc}") from exc
        return result

    def test_connection(self) -> bool:
        try:
            with psycopg.connect(self.dsn_for("draft"), connect_timeout=5) as conn:
                conn.execute("SELECT 1")
            return True
        except psycopg.Error:
            return False
