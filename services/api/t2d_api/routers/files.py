"""File endpoints: authenticated download proxy.

Downloads always go through this authenticated route — never a public
bucket or presigned URL handed to the browser (task book §6). sha256 is
verified on read so file_refs rows stay trustworthy.
"""

from __future__ import annotations

import hashlib

from fastapi import APIRouter, HTTPException, Response

from ..deps import CurrentUser, DbDep, get_workspace_role
from t2d_db.models import FileRef

router = APIRouter(prefix="/api/files", tags=["files"])


@router.get("/{file_id}")
def get_file(file_id: int, user: CurrentUser, db: DbDep):
    ref = db.get(FileRef, file_id)
    if ref is None:
        raise HTTPException(status_code=404, detail="文件不存在")
    if ref.workspace_id is not None:
        # Membership check only — role does not matter for reading a file
        # of a workspace you belong to (viewers see published dashboards).
        get_workspace_role(db, user, ref.workspace_id)
    from cloud_adapters.files.local_volume import LocalVolumeFileStore

    data = LocalVolumeFileStore().get(ref.storage_key)
    digest = hashlib.sha256(data).hexdigest()
    if digest != ref.sha256:
        raise HTTPException(status_code=503, detail="文件校验失败（存储不一致）")
    return Response(content=data, media_type=ref.mime)
