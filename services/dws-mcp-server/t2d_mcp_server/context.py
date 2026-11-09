"""Identity resolution for the MCP server (evolution plan D1).

The worker (MCP client) injects X-T2D-User / X-T2D-Workspace / X-T2D-Task
headers per task — the model never touches them. This module reads those
headers and VALIDATES them against the state DB (user exists, workspace
exists, user is a member) before constructing the ToolContext. Headers are
never trusted blindly: the authorized-dataset list is always derived from
the DB, not from the request.

This preserves the 1.0 security invariant across the protocol boundary:
the tool JSON schemas carry no identity fields, and the identity that
reaches the handlers is server-verified.
"""

from __future__ import annotations

from agent_adapter import ToolContext, ToolError
from cloud_adapters import demo_mode_active
from t2d_db.models import User, Workspace, WorkspaceDataset, WorkspaceMember
from t2d_db.session import get_sessionmaker


def context_from_headers(headers) -> ToolContext:
    """Build a server-verified ToolContext from MCP request headers.

    Raises ToolError (permission_denied) on missing/invalid identity —
    the caller surfaces it as a tool error, never a crash.
    """
    h = {k.lower(): v for k, v in (headers or {}).items()}
    raw_user = h.get("x-t2d-user", "")
    raw_workspace = h.get("x-t2d-workspace", "")
    raw_task = h.get("x-t2d-task", "")

    if not raw_user or not raw_workspace:
        raise ToolError(
            "permission_denied",
            "缺少身份请求头（X-T2D-User / X-T2D-Workspace）——"
            "MCP 客户端必须为每次调用注入任务身份",
        )
    try:
        user_id = int(raw_user)
        workspace_id = int(raw_workspace)
        task_id = int(raw_task) if raw_task else 0
    except ValueError:
        raise ToolError("permission_denied", "身份请求头格式无效（须为数字 ID）")

    maker = get_sessionmaker()
    with maker() as s:
        user = s.get(User, user_id)
        if user is None or not user.is_active:
            raise ToolError("permission_denied", f"用户不存在或已停用: {user_id}")
        workspace = s.get(Workspace, workspace_id)
        if workspace is None:
            raise ToolError("permission_denied", f"业务空间不存在: {workspace_id}")
        member = (
            s.query(WorkspaceMember)
            .filter_by(workspace_id=workspace_id, user_id=user_id)
            .first()
        )
        if member is None:
            raise ToolError(
                "permission_denied",
                f"用户 {user.username} 不是业务空间 {workspace.slug} 的成员",
            )
        # Authorized datasets are ALWAYS derived from the DB — never from headers.
        datasets = {
            r.dataset_name
            for r in s.query(WorkspaceDataset)
            .filter_by(workspace_id=workspace_id, granted=True)
            .all()
        }
        # Task reference: informational — null it out if the task doesn't
        # exist (Source.task_id is nullable; a broken FK would fail inserts).
        from t2d_db.models import Task
        if task_id and s.get(Task, task_id) is None:
            task_id = None  # Source/FileRef.task_id 是可空 FK；0 会违反外键

    return ToolContext(
        task_id=task_id,
        user_id=user_id,
        workspace_id=workspace_id,
        role=member.role,
        datasets=sorted(datasets),
        demo_mode=demo_mode_active(),
    )
