"""Real DWS (GaussDB) warehouse — activates only with credentials.

Wiring checklist when credentials arrive (see docs/phase-notes):
- DWS_HOST/PORT/DATABASE/SCHEMA/USER/PASSWORD in .env
- restricted read-only account; ideally t2d_draft / t2d_publisher roles
- security group allowing the app ECS's internal IP
- sqlglot dialect check against the actual DWS version

GaussDB(DWS) speaks the PostgreSQL wire protocol; psycopg connects with
the DWS port (default 8000, per console connection info). This module is
intentionally NOT wired into the factory until a live verification pass
runs against the real cluster (CLAUDE.md rule 3: no unverified claims).
"""

from __future__ import annotations

import os

from ..base import AdapterError, DataWarehouse


class DwsDataWarehouse(DataWarehouse):
    is_demo = False

    def __init__(self) -> None:
        self.host = os.environ.get("DWS_HOST", "")
        self.port = int(os.environ.get("DWS_PORT", "8000"))
        self.database = os.environ.get("DWS_DATABASE", "")
        self.schema = os.environ.get("DWS_SCHEMA", "t2d")
        self.user = os.environ.get("DWS_USER", "")
        self.password = os.environ.get("DWS_PASSWORD", "")
        if not all([self.host, self.database, self.user, self.password]):
            raise AdapterError("DWS 凭据不完整（需要 DWS_HOST/DATABASE/USER/PASSWORD）")

    def dsn_for(self, identity: str) -> str:
        role = os.environ.get(
            "DWS_DRAFT_ROLE" if identity == "draft" else "DWS_PUBLISHER_ROLE",
            self.user,
        )
        return (
            f"host={self.host} port={self.port} dbname={self.database} "
            f"user={role} password={self.password} options='-c search_path={self.schema}'"
        )

    def authorized_schema(self, datasets: list[str]) -> dict:
        raise NotImplementedError("待真实 DWS 集群接入后按实测补齐（含 schema 限定）")

    def test_connection(self) -> bool:
        raise NotImplementedError("待真实 DWS 集群接入后按实测补齐")
