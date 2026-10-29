"""Workspace endpoints: list, detail with role and dataset grants."""

from __future__ import annotations

from fastapi import APIRouter

from ..deps import (
    CurrentUser,
    DbDep,
    authorized_datasets,
    get_workspace_role,
    workspace_or_404,
)
from t2d_db.models import Dashboard, Workspace, WorkspaceMember

router = APIRouter(prefix="/api/workspaces", tags=["workspaces"])


@router.get("")
def list_workspaces(user: CurrentUser, db: DbDep):
    rows = (
        db.query(Workspace, WorkspaceMember.role)
        .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
        .filter(WorkspaceMember.user_id == user.id)
        .order_by(Workspace.id)
        .all()
    )
    return [
        {
            "id": ws.id,
            "slug": ws.slug,
            "name": ws.name,
            "type": ws.type,
            "role": role,
        }
        for ws, role in rows
    ]


@router.get("/{workspace_id}")
def workspace_detail(workspace_id: int, user: CurrentUser, db: DbDep):
    ws = workspace_or_404(db, workspace_id)
    role = get_workspace_role(db, user, workspace_id)
    return {
        "id": ws.id,
        "slug": ws.slug,
        "name": ws.name,
        "type": ws.type,
        "role": role,
        "datasets": sorted(authorized_datasets(db, workspace_id)),
        "dashboard_count": db.query(Dashboard)
        .filter_by(workspace_id=workspace_id)
        .count(),
    }
