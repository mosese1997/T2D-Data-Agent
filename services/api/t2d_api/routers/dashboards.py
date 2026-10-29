"""Dashboard endpoints: list + detail (canvas from current version).

Version/patch/apply endpoints land in phase 3 with the worker.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..deps import CurrentUser, DbDep, get_workspace_role, workspace_or_404
from t2d_db.models import Dashboard, DashboardVersion

router = APIRouter(prefix="/api", tags=["dashboards"])


@router.get("/workspaces/{workspace_id}/dashboards")
def list_dashboards(workspace_id: int, user: CurrentUser, db: DbDep):
    workspace_or_404(db, workspace_id)
    get_workspace_role(db, user, workspace_id)
    rows = (
        db.query(Dashboard)
        .filter_by(workspace_id=workspace_id)
        .order_by(Dashboard.updated_at.desc())
        .all()
    )
    return [
        {
            "id": d.id,
            "title": d.title,
            "status": d.status,
            "current_version_id": d.current_version_id,
            "updated_at": d.updated_at.isoformat(),
        }
        for d in rows
    ]


@router.get("/dashboards/{dashboard_id}")
def get_dashboard(dashboard_id: int, user: CurrentUser, db: DbDep):
    dashboard = db.get(Dashboard, dashboard_id)
    if dashboard is None:
        raise HTTPException(status_code=404, detail="看板不存在")
    get_workspace_role(db, user, dashboard.workspace_id)
    version = (
        db.get(DashboardVersion, dashboard.current_version_id)
        if dashboard.current_version_id
        else None
    )
    return {
        "id": dashboard.id,
        "workspace_id": dashboard.workspace_id,
        "title": dashboard.title,
        "status": dashboard.status,
        "current_version_id": dashboard.current_version_id,
        "canvas": version.canvas_json if version else None,
        "revision": version.revision if version else 0,
        "updated_at": dashboard.updated_at.isoformat(),
    }
