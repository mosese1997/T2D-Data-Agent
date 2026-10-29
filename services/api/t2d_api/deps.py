"""FastAPI dependencies: current user, DB session, workspace role."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, HTTPException

from .auth.tokens import verify_token
from .settings import settings
from t2d_db.models import User, Workspace, WorkspaceDataset, WorkspaceMember
from t2d_db.session import get_sessionmaker


def get_db():
    maker = get_sessionmaker()
    with maker() as session:
        yield session


DbDep = Annotated[object, Depends(get_db)]


def get_current_user(
    db: DbDep,
    authorization: Annotated[str | None, Header()] = None,
) -> User:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="未登录")
    user_id = verify_token(authorization[7:])
    if user_id is None:
        raise HTTPException(status_code=401, detail="会话已过期，请重新登录")
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="账号不可用")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def get_workspace_role(db: DbDep, user: User, workspace_id: int) -> str:
    """Role of user in workspace; 403 when not a member."""
    member = (
        db.query(WorkspaceMember)
        .filter_by(workspace_id=workspace_id, user_id=user.id)
        .first()
    )
    if member is None:
        raise HTTPException(status_code=403, detail="不是该业务空间成员")
    return member.role


def require_role(role: str, minimum: str) -> None:
    """Role hierarchy check: admin > analyst > viewer."""
    order = {"viewer": 0, "analyst": 1, "admin": 2}
    if order[role] < order[minimum]:
        raise HTTPException(status_code=403, detail=f"需要 {minimum} 及以上权限")


def authorized_datasets(db: DbDep, workspace_id: int) -> set[str]:
    """Granted dataset whitelist for a workspace (permission root)."""
    rows = (
        db.query(WorkspaceDataset)
        .filter_by(workspace_id=workspace_id, granted=True)
        .all()
    )
    return {r.dataset_name for r in rows}


def workspace_or_404(db: DbDep, workspace_id: int) -> Workspace:
    ws = db.get(Workspace, workspace_id)
    if ws is None:
        raise HTTPException(status_code=404, detail="业务空间不存在")
    return ws


def demo_mode() -> bool:
    from cloud_adapters import demo_mode_active

    return demo_mode_active() or settings.force_demo_banner
