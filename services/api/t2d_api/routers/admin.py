"""Admin console endpoints: agent config, runs, trace, knowledge index.

Trace = the "前台一次分析能进入对应后台执行详情" requirement (task book
§17 阶段5): every task exposes its agent_runs tree + tool_calls with real
inputs/outputs/latency — no fabricated records.
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..deps import CurrentUser, DbDep, get_workspace_role, require_role
from t2d_db.models import AgentRun, Dashboard, Task, ToolCall

router = APIRouter(prefix="/api/admin", tags=["admin"])

CONFIG_PATH = Path(os.environ.get(
    "AGENT_CONFIG_PATH",
    str(Path(__file__).resolve().parents[4] / "config" / "agent" / "agent_config.yaml"),
))


def _require_admin(user, db, workspace_id: int | None = None) -> None:
    """Admin console: workspace admin (or any-workspace admin when no ws)."""
    if workspace_id is None:
        from t2d_db.models import WorkspaceMember

        is_admin = (
            db.query(WorkspaceMember)
            .filter_by(user_id=user.id, role="admin")
            .first()
            is not None
        )
        if not is_admin:
            raise HTTPException(status_code=403, detail="需要管理员权限")
    else:
        role = get_workspace_role(db, user, workspace_id)
        require_role(role, "admin")


@router.get("/agent-config")
def get_agent_config(user: CurrentUser, db: DbDep):
    _require_admin(user, db)
    with open(CONFIG_PATH, encoding="utf-8") as f:
        config = yaml.safe_load(f)
    return {
        "config": config,
        "runtime_capabilities": {
            "toolloop": {"streaming": False, "step_level_cancel": True,
                         "budget_control": True, "parallel_subagents": False},
            "swarmflow": {"verified": "GO", "adapter": "phase-3+ 可切换实现",
                          "see": "packages/agent_adapter/agent_adapter/boundaries.md"},
        },
    }


class RuntimeSwitch(BaseModel):
    runtime: str  # toolloop | swarmflow


@router.post("/agent-config/runtime")
def switch_runtime(body: RuntimeSwitch, user: CurrentUser, db: DbDep):
    _require_admin(user, db)
    if body.runtime not in ("toolloop", "swarmflow"):
        raise HTTPException(status_code=400, detail="runtime 仅支持 toolloop | swarmflow")
    if body.runtime == "swarmflow":
        # Honest boundary: the adapter lands after phase-3 integration tests.
        raise HTTPException(status_code=409, detail=(
            "swarmflow 适配器尚未接入主链路（探测 GO，见 boundaries.md）；"
            "当前可用 runtime: toolloop"))
    with open(CONFIG_PATH, encoding="utf-8") as f:
        config = yaml.safe_load(f)
    config["agent"]["runtime"] = body.runtime
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.safe_dump(config, f, allow_unicode=True, sort_keys=False)
    return {"runtime": body.runtime}


@router.get("/runs")
def list_runs(user: CurrentUser, db: DbDep, limit: int = 50, task_id: int | None = None):
    _require_admin(user, db)
    query = db.query(Task).order_by(Task.id.desc())
    if task_id:
        query = query.filter(Task.id == task_id)
    tasks = query.limit(min(limit, 200)).all()
    return [
        {
            "task_id": t.id, "type": t.type, "status": t.status,
            "workspace_id": t.workspace_id, "user_id": t.user_id,
            "dashboard_id": t.dashboard_id,
            "created_at": t.created_at.isoformat(),
            "finished_at": t.finished_at.isoformat() if t.finished_at else None,
            "error": t.error,
        }
        for t in tasks
    ]


@router.get("/runs/{task_id}/trace")
def run_trace(task_id: int, user: CurrentUser, db: DbDep):
    """Full execution detail: agent runs tree + tool calls with I/O."""
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    _require_admin(user, db, workspace_id=task.workspace_id)

    runs = (
        db.query(AgentRun).filter(AgentRun.task_id == task_id).order_by(AgentRun.id).all()
    )
    calls = (
        db.query(ToolCall).filter(ToolCall.task_id == task_id).order_by(ToolCall.seq).all()
    )
    return {
        "task": {
            "id": task.id, "type": task.type, "status": task.status,
            "result": task.result, "error": task.error,
            "checkpoint": task.checkpoint,
            "created_at": task.created_at.isoformat(),
        },
        "agent_runs": [
            {
                "id": r.id, "agent_name": r.agent_name, "parent_run_id": r.parent_run_id,
                "runtime": r.runtime, "model": r.model, "status": r.status,
                "token_usage": r.token_usage,
                "started_at": r.started_at.isoformat() if r.started_at else None,
                "finished_at": r.finished_at.isoformat() if r.finished_at else None,
            }
            for r in runs
        ],
        "tool_calls": [
            {
                "seq": c.seq, "agent_name": c.agent_name, "tool_name": c.tool_name,
                "input": c.input_json, "output": c.output_json, "status": c.status,
                "error": c.error, "latency_ms": c.latency_ms,
                "created_at": c.created_at.isoformat(),
            }
            for c in calls
        ],
    }


@router.get("/knowledge-index")
def knowledge_index(user: CurrentUser, db: DbDep):
    """Index status: what's in the semantic registry (demo: local hybrid)."""
    _require_admin(user, db)
    from semantic import load_semantics

    config_dir = os.environ.get(
        "SEMANTIC_CONFIG_DIR",
        str(Path(__file__).resolve().parents[4] / "config" / "semantics"),
    )
    registry = load_semantics(config_dir)
    return {
        "engine": "local-hybrid (demo)" ,
        "semantic_version": registry.version,
        "metrics": len(registry.metrics),
        "terms": len(registry.terms),
        "join_rules": len(registry.join_rules),
        "note": "演示模式：本地词法+向量混合检索；CSS 凭据接入后切换（见 boundaries.md）",
    }


@router.get("/evals")
def list_evals(user: CurrentUser, db: DbDep, limit: int = 20):
    """Eval runs with summaries (fixed case suites, task book §18)."""
    _require_admin(user, db)
    from t2d_db.models import EvalCaseResult, EvalRun

    runs = (
        db.query(EvalRun).order_by(EvalRun.id.desc()).limit(min(limit, 100)).all()
    )
    result = []
    for run in runs:
        cases = (
            db.query(EvalCaseResult)
            .filter(EvalCaseResult.eval_run_id == run.id)
            .order_by(EvalCaseResult.id)
            .all()
        )
        result.append({
            "id": run.id, "case_set": run.case_set, "summary": run.summary,
            "created_at": run.created_at.isoformat(),
            "cases": [
                {"case_id": c.case_id, "status": c.status} for c in cases
            ],
        })
    return result


@router.get("/wiki")
def wiki(user: CurrentUser, db: DbDep):
    """Metric & term dictionary (Wiki page). Any member can read."""
    from t2d_db.models import Metric, Term

    metrics = db.query(Metric).filter_by(status="active").order_by(Metric.metric_key).all()
    terms = db.query(Term).order_by(Term.term).all()
    return {
        "metrics": [
            {"metric_key": m.metric_key, "name": m.name, "synonyms": m.synonyms,
             "description": m.description, "base_dataset": m.base_dataset,
             "grain": m.grain, "exclusions": m.exclusions,
             "currency_policy": m.currency_policy, "version": m.version}
            for m in metrics
        ],
        "terms": [
            {"term": t.term, "aliases": t.aliases, "definition": t.definition,
             "ref_metric": t.ref_metric_key}
            for t in terms
        ],
    }
