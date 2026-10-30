"""Source endpoints: metadata + paginated rows (read from the FileStore)."""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException

from ..deps import CurrentUser, DbDep, get_workspace_role
from t2d_db.models import FileRef, Source

router = APIRouter(prefix="/api/sources", tags=["sources"])


def _source_or_404(db, source_id: int) -> Source:
    source = db.get(Source, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Source 不存在")
    return source


@router.get("/{source_id}")
def get_source(source_id: int, user: CurrentUser, db: DbDep):
    source = _source_or_404(db, source_id)
    get_workspace_role(db, user, source.workspace_id)
    return {
        "id": source.id, "title": source.title, "sql": source.sql_text,
        "params": source.params_json, "col_schema": source.col_schema,
        "row_count": source.row_count, "status": source.status,
        "caliber_notes": source.caliber_notes,
        "semantic_refs": source.semantic_refs,
        "created_at": source.created_at.isoformat(),
    }


@router.get("/{source_id}/rows")
def get_rows(source_id: int, user: CurrentUser, db: DbDep,
             page: int = 1, size: int = 50):
    source = _source_or_404(db, source_id)
    role = get_workspace_role(db, user, source.workspace_id)
    size = min(max(size, 1), 500)
    page = max(page, 1)

    file_ref = db.get(FileRef, source.result_file_id) if source.result_file_id else None
    if file_ref is None:
        raise HTTPException(status_code=404, detail="Source 没有结果文件")

    # Permission-scoped cache (task book §14): key includes user/workspace/
    # role/dataset scope + file_ref_id (source & refresh version) + params.
    from fastapi.responses import JSONResponse

    from ..cache import cache_key, get_result_cache
    from ..deps import authorized_datasets

    datasets = frozenset(authorized_datasets(db, source.workspace_id))
    key = cache_key(user_id=user.id, workspace_id=source.workspace_id, role=role,
                    datasets=datasets, file_ref_id=file_ref.id, page=page, size=size)
    cache = get_result_cache()
    cached, hit = cache.get(key)
    if hit:
        return JSONResponse(content=cached, headers={"X-Cache": "HIT"})

    import hashlib

    from cloud_adapters.files.local_volume import LocalVolumeFileStore

    data = LocalVolumeFileStore().get(file_ref.storage_key)
    if hashlib.sha256(data).hexdigest() != file_ref.sha256:
        raise HTTPException(status_code=503, detail="结果文件校验失败（存储不一致）")
    payload = json.loads(data)
    rows = payload.get("rows", [])
    start = (page - 1) * size
    result = {
        "columns": payload.get("columns", []),
        "rows": rows[start : start + size],
        "row_count": payload.get("row_count", len(rows)),
        "truncated": payload.get("truncated", False),
        "page": page,
        "size": size,
    }
    cache.put(key, result)
    return JSONResponse(content=result, headers={"X-Cache": "MISS"})
