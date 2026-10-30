"""Worker-side shared dependencies: semantic registry, adapters, gateway.

Built once at worker boot; tool handlers close over these plus the
per-task ToolContext. SQLite note: every DB touch uses a SHORT session
(see phase-2 lock lessons in docs/phase-notes).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from cloud_adapters.dw.postgres_dw import PostgresDataWarehouse
from cloud_adapters.files.local_volume import LocalVolumeFileStore
from query_gateway import QueryGateway
from semantic import SemanticRetriever, load_semantics
from t2d_db.models import AuditLog
from t2d_db.session import get_sessionmaker

def _find_repo_root() -> Path:
    """Walk up until the repo layout is found (dev tree vs container /app
    layouts have different depths)."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "config" / "agent" / "agent_config.yaml").is_file():
            return parent
    return here.parents[1]


ROOT = _find_repo_root()


def _find_semantic_config_dir() -> str:
    """Env var first; then walk up (dev tree AND container layouts differ:
    services/worker/t2d_worker/deps.py has 4 parents to repo root, while
    /app/t2d_worker/deps.py in the image has only 2)."""
    env = os.environ.get("SEMANTIC_CONFIG_DIR")
    if env:
        return env
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "config" / "semantics"
        if (candidate / "metrics.yaml").is_file():
            return str(candidate)
    raise RuntimeError(
        "找不到语义配置目录（config/semantics/metrics.yaml）；"
        "请设置 SEMANTIC_CONFIG_DIR"
    )


SEMANTIC_CONFIG_DIR = _find_semantic_config_dir()


@dataclass
class WorkerDeps:
    registry: object          # semantic.SemanticRegistry
    retriever: SemanticRetriever
    warehouse: PostgresDataWarehouse
    files: LocalVolumeFileStore
    gateway: QueryGateway
    sessionmaker: object


def build_runtime():
    """Runtime from config/agent/agent_config.yaml (the single switch).

    toolloop is the verified default. swarmflow loads lazily — if the
    engine isn't installed in this environment we log prominently and
    fall back to toolloop (never crash the worker; the admin switch only
    allows swarmflow where the engine is actually importable).
    """
    import yaml
    from agent_adapter.toolloop import ToolLoopRuntime

    config_path = os.environ.get(
        "AGENT_CONFIG_PATH", str(ROOT / "config" / "agent" / "agent_config.yaml"))
    try:
        with open(config_path, encoding="utf-8") as f:
            runtime_name = (yaml.safe_load(f) or {}).get("agent", {}).get(
                "runtime", "toolloop")
    except OSError:
        runtime_name = "toolloop"

    if runtime_name == "swarmflow":
        try:
            from agent_adapter.swarmflow.runtime import SwarmFlowRuntime

            print("[worker] runtime: swarmflow (adapter, probe-verified)", flush=True)
            return SwarmFlowRuntime()
        except Exception as exc:
            print(f"[worker] ⚠️ runtime=swarmflow 但引擎不可用（{exc}）"
                  f"——回退 toolloop", flush=True)
            return ToolLoopRuntime()
    return ToolLoopRuntime()


def build_deps() -> WorkerDeps:
    registry = load_semantics(SEMANTIC_CONFIG_DIR)
    retriever = SemanticRetriever(registry)
    warehouse = PostgresDataWarehouse()
    files = LocalVolumeFileStore()
    maker = get_sessionmaker()

    def audit_hook(identity: str, sql: str, meta: dict) -> None:
        # Separate short session — never hold the worker's task transaction.
        with maker() as s:
            s.add(AuditLog(
                actor_user_id=None, action="query.execute",
                object_type="source", detail={"identity": identity, "sql": sql, **meta},
            ))
            s.commit()

    gateway = QueryGateway(
        dsn_for={"draft": warehouse.dsn_for("draft"),
                 "publisher": warehouse.dsn_for("publisher")},
        audit_hook=audit_hook,
    )
    return WorkerDeps(
        registry=registry, retriever=retriever, warehouse=warehouse,
        files=files, gateway=gateway, sessionmaker=maker,
    )
