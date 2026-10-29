#!/usr/bin/env python3
"""Seed demo accounts, workspaces, membership and dataset grants.

Role matrix (task book §14): admin / analyst / viewer. Dataset grants are
the permission root — mx-focus deliberately gets a SUBSET so authorization
differences are demonstrable.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from t2d_db.models import User, Workspace, WorkspaceDataset, WorkspaceMember
from t2d_db.session import get_sessionmaker, session_scope, utcnow

# username, display_name, password (demo-only, shown in the login hint page)
ACCOUNTS = [
    ("admin", "管理员", "admin-demo-2026"),
    ("analyst_a", "分析师A", "analyst-demo-2026"),
    ("analyst_b", "分析师B", "analyst-demo-2026"),
    ("viewer_b", "业务查看者B", "viewer-demo-2026"),
    ("viewer_c", "业务查看者C", "viewer-demo-2026"),
    ("ops", "运营分析", "ops-demo-2026"),
]

ALL_DATASETS = [
    "orders", "order_items", "refunds", "fulfillment_events",
    "dim_country", "dim_city", "dim_category", "dim_channel", "dim_product", "fx_rates",
]
MX_SUBSET = ["orders", "order_items", "dim_country", "dim_channel", "fx_rates"]

WORKSPACES = [
    # slug, name, type, member roles {username: role}, datasets
    ("latam-growth", "拉美增长", "business",
     {"admin": "admin", "analyst_a": "analyst", "analyst_b": "analyst",
      "viewer_b": "viewer", "viewer_c": "viewer", "ops": "analyst"},
     ALL_DATASETS),
    ("mx-focus", "墨西哥专项", "business",
     {"admin": "admin", "analyst_b": "analyst", "viewer_c": "viewer"},
     MX_SUBSET),
]


def main() -> None:
    from t2d_api.auth.passwords import hash_password

    maker = get_sessionmaker()
    with maker() as session:
        users: dict[str, User] = {}
        for username, display, password in ACCOUNTS:
            user = session.query(User).filter_by(username=username).first()
            if user is None:
                user = User(
                    username=username,
                    display_name=display,
                    password_hash=hash_password(password),
                )
                session.add(user)
            else:
                user.display_name = display
                user.password_hash = hash_password(password)
            session.flush()
            users[username] = user

        for slug, name, wtype, members, datasets in WORKSPACES:
            ws = session.query(Workspace).filter_by(slug=slug).first()
            if ws is None:
                ws = Workspace(slug=slug, name=name, type=wtype, created_by=users["admin"].id)
                session.add(ws)
                session.flush()
            for username, role in members.items():
                member = (
                    session.query(WorkspaceMember)
                    .filter_by(workspace_id=ws.id, user_id=users[username].id)
                    .first()
                )
                if member is None:
                    session.add(WorkspaceMember(
                        workspace_id=ws.id, user_id=users[username].id, role=role))
                else:
                    member.role = role
            existing = {
                r.dataset_name for r in session.query(WorkspaceDataset)
                .filter_by(workspace_id=ws.id).all()
            }
            for ds in datasets:
                if ds not in existing:
                    session.add(WorkspaceDataset(
                        workspace_id=ws.id, dataset_name=ds, granted=True,
                        granted_at=utcnow()))
        session.commit()

    with session_scope() as s:
        n_users = s.query(User).count()
        n_ws = s.query(Workspace).count()
        n_grants = s.query(WorkspaceDataset).count()
    print(f"✅ 种子完成: {n_users} 账号, {n_ws} 业务空间, {n_grants} 数据集授权")
    print("   演示账号: " + ", ".join(f"{u}/{p}" for u, _, p in ACCOUNTS[:3]) + " …（见 scripts/seed_demo_users.py）")


if __name__ == "__main__":
    main()
