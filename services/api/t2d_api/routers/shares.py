"""Sharing: token-based view of a dashboard version.

A share grants access to the dashboard VIEW only — the public endpoint
returns canvas + rendered data, never SQL/source metadata, and never any
tool context (task book §14: 分享资产不自动授予底层数据权限).
"""

from __future__ import annotations

import json
import secrets
from datetime import timedelta

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..deps import CurrentUser, DbDep, get_workspace_role, require_role
from t2d_db.models import Dashboard, DashboardVersion, FileRef, Share, Source
from t2d_db.session import utcnow
from cloud_adapters.files.local_volume import LocalVolumeFileStore

router = APIRouter(prefix="/api", tags=["shares"])


class ShareRequest(BaseModel):
    expires_in_hours: int = 72


@router.post("/dashboards/{dashboard_id}/shares")
def create_share(dashboard_id: int, body: ShareRequest,
                 user: CurrentUser, db: DbDep):
    dashboard = db.get(Dashboard, dashboard_id)
    if dashboard is None:
        raise HTTPException(status_code=404, detail="看板不存在")
    role = get_workspace_role(db, user, dashboard.workspace_id)
    require_role(role, "analyst")
    share = Share(
        dashboard_id=dashboard.id,
        version_id=dashboard.current_version_id,
        share_token=secrets.token_urlsafe(24),
        granted_by=user.id,
        expires_at=utcnow() + timedelta(hours=min(max(body.expires_in_hours, 1), 720)),
    )
    db.add(share)
    db.commit()
    return {"share_token": share.share_token,
            "expires_at": share.expires_at.isoformat()}


@router.get("/shared/{share_token}")
def view_shared(share_token: str, db: DbDep):
    """Public: canvas + data only. No SQL, no source metadata, no auth."""
    share = db.query(Share).filter_by(share_token=share_token).first()
    if share is None:
        raise HTTPException(status_code=404, detail="分享链接不存在")
    if share.expires_at and share.expires_at < utcnow():
        raise HTTPException(status_code=410, detail="分享链接已过期")
    dashboard = db.get(Dashboard, share.dashboard_id)
    version = db.get(DashboardVersion, share.version_id) if share.version_id else None
    if dashboard is None or version is None:
        raise HTTPException(status_code=404, detail="看板或版本不存在")

    canvas = version.canvas_json
    data: dict[str, dict] = {}
    files = LocalVolumeFileStore()
    for component in canvas.get("components", []):
        sid = component.get("source_id")
        if not sid or sid in data:
            continue
        source = db.get(Source, int(sid))
        if source is None or not source.result_file_id:
            continue
        ref = db.get(FileRef, source.result_file_id)
        if ref is None:
            continue
        try:
            payload = json.loads(files.get(ref.storage_key))
        except Exception:
            continue
        data[sid] = {
            "columns": payload.get("columns", []),
            "rows": payload.get("rows", [])[:500],
            "row_count": payload.get("row_count", 0),
        }
    return {
        "title": dashboard.title,
        "revision": version.revision,
        "canvas": canvas,
        "data": data,
        "shared_view": True,  # the UI shows a read-only banner
    }
