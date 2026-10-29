"""Build the server-side ToolContext from a task id (never from the model)."""

from __future__ import annotations

from agent_adapter import ToolContext
from cloud_adapters import demo_mode_active
from t2d_db.models import Task, WorkspaceDataset, WorkspaceMember
from t2d_db.session import get_sessionmaker


def context_for_task(task_id: int) -> ToolContext:
    """Identity & permission scope loaded from the state DB — the single
    source of truth for who this run acts as (CLAUDE.md rule 2)."""
    maker = get_sessionmaker()
    with maker() as s:
        task = s.get(Task, task_id)
        if task is None:
            raise ValueError(f"task {task_id} 不存在")
        member = (
            s.query(WorkspaceMember)
            .filter_by(workspace_id=task.workspace_id, user_id=task.user_id)
            .first()
        )
        role = member.role if member else "viewer"
        datasets = {
            r.dataset_name
            for r in s.query(WorkspaceDataset)
            .filter_by(workspace_id=task.workspace_id, granted=True)
            .all()
        }
        workspace_id = task.workspace_id
        user_id = task.user_id
    return ToolContext(
        task_id=task_id,
        user_id=user_id,
        workspace_id=workspace_id,
        role=role,
        datasets=sorted(datasets),
        demo_mode=demo_mode_active(),
    )
