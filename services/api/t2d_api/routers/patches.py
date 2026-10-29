"""Patch endpoints: preview list, atomic apply, reject.

Apply is ONE transaction: revalidate base_revision against the dashboard's
current revision → apply_patch → insert DashboardVersion(revision+1) →
flip dashboard.current_version_id → patch.status=applied → complete the
waiting task. A conflict marks the patch conflict and requires
regeneration — never auto-merge (task book §12).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..deps import CurrentUser, DbDep, get_workspace_role, require_role
from t2d_db.models import Dashboard, DashboardPatch, DashboardVersion, Task
from t2d_db.session import utcnow
from dashboard_schema import apply_patch
from dashboard_schema.canvas import Canvas
from dashboard_schema.patch import Patch

router = APIRouter(prefix="/api", tags=["patches"])


def _patch_or_404(db, patch_id: int) -> tuple[DashboardPatch, Dashboard]:
    patch = db.get(DashboardPatch, patch_id)
    if patch is None:
        raise HTTPException(status_code=404, detail="候选变更不存在")
    dashboard = db.get(Dashboard, patch.dashboard_id)
    if dashboard is None:
        raise HTTPException(status_code=404, detail="看板不存在")
    return patch, dashboard


@router.get("/dashboards/{dashboard_id}/patches")
def list_patches(dashboard_id: int, user: CurrentUser, db: DbDep):
    dashboard = db.get(Dashboard, dashboard_id)
    if dashboard is None:
        raise HTTPException(status_code=404, detail="看板不存在")
    get_workspace_role(db, user, dashboard.workspace_id)
    rows = (
        db.query(DashboardPatch)
        .filter(DashboardPatch.dashboard_id == dashboard_id)
        .order_by(DashboardPatch.id.desc())
        .limit(20)
        .all()
    )
    return [
        {"id": p.id, "base_revision": p.base_revision, "status": p.status,
         "diff_summary": p.diff_summary, "task_id": p.task_id,
         "created_at": p.created_at.isoformat()}
        for p in rows
    ]


@router.post("/patches/{patch_id}/apply")
def apply(patch_id: int, user: CurrentUser, db: DbDep):
    patch, dashboard = _patch_or_404(db, patch_id)
    role = get_workspace_role(db, user, dashboard.workspace_id)
    require_role(role, "analyst")
    if patch.status == "applied":
        raise HTTPException(status_code=409, detail="该变更已应用")
    if patch.status != "validated":
        raise HTTPException(status_code=409, detail=f"变更当前状态不可应用（{patch.status}）")

    current = (
        db.get(DashboardVersion, dashboard.current_version_id)
        if dashboard.current_version_id
        else None
    )
    current_revision = current.revision if current else 0
    if patch.base_revision != current_revision:
        patch.status = "conflict"
        db.commit()
        raise HTTPException(status_code=409, detail=(
            f"版本冲突：变更基于 revision {patch.base_revision}，"
            f"看板已更新到 revision {current_revision}，请让 Agent 重新生成"))

    base_canvas = Canvas.model_validate(current.canvas_json) if current else Canvas(
        title=dashboard.title)
    patch_obj = Patch.model_validate(patch.patch_json)
    try:
        after = apply_patch(base_canvas, patch_obj)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"变更无法应用: {exc}")

    version = DashboardVersion(
        dashboard_id=dashboard.id, revision=current_revision + 1,
        canvas_json=after.model_dump(),
        base_revision=patch.base_revision,
        source_snapshot=(current.source_snapshot if current else {}),
        change_summary=patch.diff_summary,
        created_by=user.id, task_id=patch.task_id,
    )
    db.add(version)
    db.flush()
    dashboard.current_version_id = version.id
    dashboard.updated_at = utcnow()
    patch.status = "applied"
    patch.applied_version_id = version.id
    patch.applied_at = utcnow()

    # Complete the task that was waiting on this patch.
    if patch.task_id:
        task = db.get(Task, patch.task_id)
        if task and task.status == "waiting_for_apply":
            task.status = "succeeded"
            task.result = {"patch_id": patch.id, "version_id": version.id,
                           "dashboard_id": dashboard.id}
            task.finished_at = utcnow()
            task.lease_expires_at = None
    db.commit()
    return {"version_id": version.id, "revision": version.revision,
            "dashboard_id": dashboard.id}


@router.post("/patches/{patch_id}/reject")
def reject(patch_id: int, user: CurrentUser, db: DbDep):
    patch, dashboard = _patch_or_404(db, patch_id)
    role = get_workspace_role(db, user, dashboard.workspace_id)
    require_role(role, "analyst")
    if patch.status == "applied":
        raise HTTPException(status_code=409, detail="该变更已应用，无法拒绝")
    patch.status = "rejected"
    if patch.task_id:
        task = db.get(Task, patch.task_id)
        if task and task.status == "waiting_for_apply":
            task.status = "cancelled"
            task.error = {"code": "patch_rejected", "message": "用户拒绝了候选变更"}
            task.finished_at = utcnow()
            task.lease_expires_at = None
    db.commit()
    return {"ok": True}
