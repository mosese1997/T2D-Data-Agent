"""Refresh: schedules + manual trigger.

Refresh re-executes every source bound by the current canvas version with
the PUBLISHER identity (approved execution identity, task book §14) and
swaps the result files in place — source ids stay stable so canvas
bindings never break.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..deps import CurrentUser, DbDep, get_workspace_role, require_role
from t2d_db import queue
from t2d_db.models import Dashboard, RefreshSchedule
from t2d_db.session import utcnow

router = APIRouter(prefix="/api/dashboards", tags=["refresh"])


class ScheduleRequest(BaseModel):
    cron: str  # 5-field cron; validated loosely, demo-grade


@router.post("/{dashboard_id}/refresh")
def refresh_now(dashboard_id: int, user: CurrentUser, db: DbDep):
    dashboard = db.get(Dashboard, dashboard_id)
    if dashboard is None:
        raise HTTPException(status_code=404, detail="看板不存在")
    role = get_workspace_role(db, user, dashboard.workspace_id)
    require_role(role, "analyst")
    if dashboard.current_version_id is None:
        raise HTTPException(status_code=409, detail="看板没有版本可刷新")
    task = queue.enqueue(
        type="refresh", workspace_id=dashboard.workspace_id, user_id=user.id,
        payload={"dashboard_id": dashboard_id},
        idempotency_key=f"refresh:{dashboard_id}:{uuid.uuid4()}",
        dashboard_id=dashboard_id, session=db,
    )
    db.commit()  # enqueue with a passed-in session does not commit itself
    return {"task_id": task.id}


@router.post("/{dashboard_id}/refresh-schedules")
def create_schedule(dashboard_id: int, body: ScheduleRequest,
                    user: CurrentUser, db: DbDep):
    dashboard = db.get(Dashboard, dashboard_id)
    if dashboard is None:
        raise HTTPException(status_code=404, detail="看板不存在")
    role = get_workspace_role(db, user, dashboard.workspace_id)
    require_role(role, "analyst")
    fields = body.cron.split()
    if len(fields) != 5:
        raise HTTPException(status_code=400, detail="cron 须为 5 段式（分 时 日 月 周）")
    schedule = RefreshSchedule(
        dashboard_id=dashboard_id, cron=body.cron, enabled=True,
        created_by=user.id,
    )
    db.add(schedule)
    db.commit()
    return {"id": schedule.id, "cron": schedule.cron, "enabled": True}


@router.get("/{dashboard_id}/refresh-schedules")
def list_schedules(dashboard_id: int, user: CurrentUser, db: DbDep):
    dashboard = db.get(Dashboard, dashboard_id)
    if dashboard is None:
        raise HTTPException(status_code=404, detail="看板不存在")
    get_workspace_role(db, user, dashboard.workspace_id)
    rows = (db.query(RefreshSchedule)
            .filter_by(dashboard_id=dashboard_id).order_by(RefreshSchedule.id).all())
    return [
        {"id": r.id, "cron": r.cron, "enabled": r.enabled,
         "last_run_at": r.last_run_at.isoformat() if r.last_run_at else None,
         "next_run_at": r.next_run_at.isoformat() if r.next_run_at else None}
        for r in rows
    ]
