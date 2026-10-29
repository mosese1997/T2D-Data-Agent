"""Publishing with approval (task book §14, simplified rules).

Publish = request → target-workspace ADMIN approves → an immutable copy
(dashboard + version + sources + result files) lands in the target
workspace with status=published. The copy IS the published result —
viewers in the target space see the snapshot; no underlying data
permissions are granted (分享/发布不授予底层数据权限).
Re-publishing creates a new published version; changed SQL/source/audience
requires re-approval (each request is a fresh Approval row).
"""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..deps import CurrentUser, DbDep, get_workspace_role, require_role
from t2d_db.models import (
    Approval, Dashboard, DashboardPatch, DashboardVersion, FileRef, Publication,
    Source, Workspace,
)
from t2d_db.session import utcnow
from cloud_adapters.files.local_volume import LocalVolumeFileStore

router = APIRouter(prefix="/api", tags=["publish"])


class PublishRequest(BaseModel):
    target_workspace_id: int
    comment: str = ""


@router.post("/dashboards/{dashboard_id}/publish")
def request_publish(dashboard_id: int, body: PublishRequest,
                    user: CurrentUser, db: DbDep):
    dashboard = db.get(Dashboard, dashboard_id)
    if dashboard is None:
        raise HTTPException(status_code=404, detail="看板不存在")
    role = get_workspace_role(db, user, dashboard.workspace_id)
    require_role(role, "analyst")
    if dashboard.current_version_id is None:
        raise HTTPException(status_code=409, detail="看板没有可发布的版本（先 Apply）")
    target = db.get(Workspace, body.target_workspace_id)
    if target is None:
        raise HTTPException(status_code=404, detail="目标业务空间不存在")
    if target.id == dashboard.workspace_id:
        raise HTTPException(status_code=400, detail="目标空间不能是当前空间")

    version = db.get(DashboardVersion, dashboard.current_version_id)
    publication = Publication(
        dashboard_id=dashboard.id, version_id=version.id,
        target_workspace_id=target.id, status="pending",
        requested_by=user.id,
    )
    db.add(publication)
    db.flush()
    db.add(Approval(
        request_type="publish", request_id=publication.id,
        requester_id=user.id, status="pending", comment=body.comment,
    ))
    db.commit()
    return {"publication_id": publication.id, "status": "pending",
            "version_id": version.id}


@router.get("/requests")
def list_requests(user: CurrentUser, db: DbDep):
    """Pending approvals visible to the user (as target-workspace admin)."""
    rows = (
        db.query(Approval, Publication)
        .join(Publication, Publication.id == Approval.request_id)
        .filter(Approval.request_type == "publish", Approval.status == "pending")
        .order_by(Approval.id.desc())
        .limit(50)
        .all()
    )
    result = []
    for approval, publication in rows:
        target = db.get(Workspace, publication.target_workspace_id)
        member_role = get_workspace_role(db, user, target.id)
        if member_role != "admin":
            continue
        source_dashboard = db.get(Dashboard, publication.dashboard_id)
        result.append({
            "approval_id": approval.id,
            "publication_id": publication.id,
            "dashboard_title": source_dashboard.title if source_dashboard else "?",
            "target_workspace": target.name,
            "comment": approval.comment,
            "requested_by": approval.requester_id,
            "created_at": approval.created_at.isoformat(),
        })
    return result


@router.post("/approvals/{approval_id}/approve")
def approve(approval_id: int, user: CurrentUser, db: DbDep):
    return _decide(approval_id, user, db, approved=True)


@router.post("/approvals/{approval_id}/reject")
def reject(approval_id: int, user: CurrentUser, db: DbDep):
    return _decide(approval_id, user, db, approved=False)


def _decide(approval_id: int, user, db, *, approved: bool) -> dict:
    approval = db.get(Approval, approval_id)
    if approval is None or approval.status != "pending":
        raise HTTPException(status_code=404, detail="审批不存在或已处理")
    publication = db.get(Publication, approval.request_id)
    target = db.get(Workspace, publication.target_workspace_id)
    role = get_workspace_role(db, user, target.id)
    if role != "admin":
        raise HTTPException(status_code=403, detail="只有目标业务空间管理员可审批")

    approval.status = "approved" if approved else "rejected"
    approval.approver_id = user.id
    approval.decided_at = utcnow()

    if not approved:
        publication.status = "rolled_back"
        db.commit()
        return {"status": "rejected"}

    # Immutable copy into the target workspace.
    source_dashboard = db.get(Dashboard, publication.dashboard_id)
    version = db.get(DashboardVersion, publication.version_id)
    files = LocalVolumeFileStore()

    published = Dashboard(
        workspace_id=target.id, title=source_dashboard.title,
        status="published", created_by=source_dashboard.created_by,
    )
    db.add(published)
    db.flush()

    # Copy sources + result files (id remap keeps canvas bindings intact).
    canvas = json.loads(json.dumps(version.canvas_json))
    remap: dict[str, int] = {}
    for component in canvas.get("components", []):
        sid = component.get("source_id")
        if not sid:
            continue
        src = db.get(Source, int(sid))
        if src is None or src.workspace_id != source_dashboard.workspace_id:
            continue
        old_ref = db.get(FileRef, src.result_file_id) if src.result_file_id else None
        new_ref = None
        if old_ref is not None:
            data = files.get(old_ref.storage_key)
            new_meta = files.put(
                f"published/{published.id}-{src.id}.json", data,
                mime=old_ref.mime)
            new_ref = FileRef(
                kind="source_result", storage_key=new_meta.storage_key,
                mime=old_ref.mime, size_bytes=new_meta.size_bytes,
                sha256=new_meta.sha256, workspace_id=target.id,
                created_by=user.id,
            )
            db.add(new_ref)
            db.flush()
        new_source = Source(
            workspace_id=target.id, title=src.title, sql_text=src.sql_text,
            params_json=src.params_json, semantic_refs=src.semantic_refs,
            caliber_notes=src.caliber_notes, col_schema=src.col_schema,
            row_count=src.row_count,
            result_file_id=new_ref.id if new_ref else None,
            status="active", created_by=user.id,
        )
        db.add(new_source)
        db.flush()
        remap[str(sid)] = new_source.id
    for component in canvas.get("components", []):
        sid = component.get("source_id")
        if sid and sid in remap:
            component["source_id"] = str(remap[sid])

    new_version = DashboardVersion(
        dashboard_id=published.id, revision=1, canvas_json=canvas,
        source_snapshot={"published_from": {
            "dashboard_id": source_dashboard.id, "version_id": version.id,
            "publication_id": publication.id,
        }},
        change_summary=f"发布自「{source_dashboard.title}」revision {version.revision}",
        created_by=user.id,
    )
    db.add(new_version)
    db.flush()
    published.current_version_id = new_version.id

    publication.status = "published"
    publication.approved_by = user.id
    publication.published_at = utcnow()
    db.commit()
    return {"status": "published", "published_dashboard_id": published.id}
