"""Version endpoints: history + restore.

Restoring a historical definition creates a NEW revision with the old
canvas — it never restores historical DATA (result snapshots are separate,
via file_refs). The response says so explicitly.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..deps import CurrentUser, DbDep, get_workspace_role, require_role
from t2d_db.models import Dashboard, DashboardVersion
from t2d_db.session import utcnow

router = APIRouter(prefix="/api/dashboards", tags=["versions"])


@router.get("/{dashboard_id}/versions")
def list_versions(dashboard_id: int, user: CurrentUser, db: DbDep):
    dashboard = db.get(Dashboard, dashboard_id)
    if dashboard is None:
        raise HTTPException(status_code=404, detail="看板不存在")
    get_workspace_role(db, user, dashboard.workspace_id)
    rows = (
        db.query(DashboardVersion)
        .filter(DashboardVersion.dashboard_id == dashboard_id)
        .order_by(DashboardVersion.revision.desc())
        .all()
    )
    return [
        {"id": v.id, "revision": v.revision, "change_summary": v.change_summary,
         "base_revision": v.base_revision, "created_by": v.created_by,
         "created_at": v.created_at.isoformat()}
        for v in rows
    ]


@router.post("/{dashboard_id}/versions/{revision}/restore")
def restore(dashboard_id: int, revision: int, user: CurrentUser, db: DbDep):
    dashboard = db.get(Dashboard, dashboard_id)
    if dashboard is None:
        raise HTTPException(status_code=404, detail="看板不存在")
    role = get_workspace_role(db, user, dashboard.workspace_id)
    require_role(role, "analyst")

    target = (
        db.query(DashboardVersion)
        .filter(DashboardVersion.dashboard_id == dashboard_id,
                DashboardVersion.revision == revision)
        .first()
    )
    if target is None:
        raise HTTPException(status_code=404, detail=f"版本 revision={revision} 不存在")

    current = (
        db.get(DashboardVersion, dashboard.current_version_id)
        if dashboard.current_version_id else None
    )
    current_revision = current.revision if current else 0
    new_version = DashboardVersion(
        dashboard_id=dashboard_id,
        revision=current_revision + 1,
        canvas_json=target.canvas_json,
        base_revision=current_revision,
        source_snapshot=target.source_snapshot,
        change_summary=f"恢复自 revision {revision}（仅恢复画布定义，不含历史数据快照）",
        created_by=user.id,
    )
    db.add(new_version)
    db.flush()
    dashboard.current_version_id = new_version.id
    dashboard.updated_at = utcnow()
    db.commit()
    return {
        "version_id": new_version.id, "revision": new_version.revision,
        "restored_from": revision,
        "note": "已恢复历史画布定义为新版本；历史数据结果快照不随定义恢复",
    }
