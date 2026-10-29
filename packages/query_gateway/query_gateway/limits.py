"""Query limits (task book §10/§11 defaults, env-overridable)."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class QueryLimits:
    timeout_s: int = 60
    max_rows: int = 10_000
    max_cells: int = 50_000
    max_bytes: int = 5 * 1024 * 1024

    @classmethod
    def from_env(cls) -> "QueryLimits":
        return cls(
            timeout_s=int(os.environ.get("TASK_QUERY_TIMEOUT_S", "60")),
            max_rows=int(os.environ.get("TASK_MAX_ROWS", "10000")),
            max_cells=int(os.environ.get("TASK_MAX_RESULT_CELLS", "50000")),
            max_bytes=int(os.environ.get("TASK_MAX_RESULT_BYTES", str(5 * 1024 * 1024))),
        )
