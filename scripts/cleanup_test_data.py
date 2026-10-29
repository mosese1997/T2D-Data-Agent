#!/usr/bin/env python3
"""Clean test-run noise from the demo environment.

Eval/verify runs create conversations, tasks, empty draft dashboards and
sources. Keep: preset dashboards, APPLIED dashboards (have real content),
and user-created conversations. Delete: test-pattern conversations with
their task/event/trace cascades, never-applied (empty) dashboards, and
sources created by the deleted tasks.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("STATE_DB_URL", "sqlite:///var/state.db")

from t2d_db.models import (
    AgentRun, Conversation, Dashboard, DashboardPatch, FileRef, Message,
    RunEvent, Source, Task, TaskCheckpoint, ToolCall,
)
from t2d_db.session import get_sessionmaker

TEST_TITLE_PATTERNS = (
    "eval-", "verify-", "p4", "compose彩排", "分析测试", "建板测试",
    "问答测试", "自初始化验证", "smoke",
)


def main() -> None:
    maker = get_sessionmaker()
    with maker() as s:
        # 1. test conversations → their tasks → cascade
        test_convs = [
            c for c in s.query(Conversation).all()
            if c.title and any(c.title.startswith(p) for p in TEST_TITLE_PATTERNS)
        ]
        conv_ids = {c.id for c in test_convs}
        tasks = s.query(Task).filter(Task.conversation_id.in_(conv_ids)).all()
        task_ids = {t.id for t in tasks}

        # also: tasks whose idempotency key marks them as test refreshes
        sched_tasks = {
            t.id for t in s.query(Task)
            .filter(Task.idempotency_key.like("refresh-sched:%")).all()
        } | {
            t.id for t in s.query(Task)
            .filter(Task.idempotency_key.like("eval-%")).all()
        }
        task_ids |= sched_tasks

        deleted = {"conversations": len(conv_ids), "tasks": len(task_ids)}

        # 2. never-applied (EMPTY) dashboards — no current version = no canvas
        empty_dashboards = (
            s.query(Dashboard)
            .filter(Dashboard.current_version_id.is_(None))
            .all()
        )
        empty_ids = {d.id for d in empty_dashboards}
        deleted["empty_dashboards"] = len(empty_ids)

        # 3. sources created by the deleted tasks (+ their file refs)
        sources = (
            s.query(Source).filter(Source.task_id.in_(task_ids)).all()
            if task_ids else []
        )
        source_ids = {src.id for src in sources}
        file_ref_ids = {src.result_file_id for src in sources if src.result_file_id}
        deleted["sources"] = len(source_ids)

        # delete in FK-safe order: everything referencing tasks first.
        from t2d_db.models import EvalCaseResult

        if task_ids:
            for model in (RunEvent, ToolCall, AgentRun, TaskCheckpoint):
                s.query(model).filter(model.task_id.in_(task_ids)).delete()
            s.query(Message).filter(Message.task_id.in_(task_ids)).delete()
            s.query(DashboardPatch).filter(
                DashboardPatch.task_id.in_(task_ids)).delete()
            s.query(Source).filter(Source.task_id.in_(task_ids)).delete()
            # Only delete file refs no REMAINING source points at (a kept
            # source may point at a file created by a deleted refresh task).
            refs_in_use = {
                src.result_file_id for src in s.query(Source).all()
                if src.result_file_id
            }
            s.query(FileRef).filter(
                FileRef.task_id.in_(task_ids),
                FileRef.id.notin_(refs_in_use),
            ).delete(synchronize_session=False)
            # In-use file refs (kept sources point at them) survive, but
            # drop their link to the deleted task.
            s.query(FileRef).filter(
                FileRef.task_id.in_(task_ids),
                FileRef.id.in_(refs_in_use),
            ).update({FileRef.task_id: None}, synchronize_session=False)
            # Kept dashboards' versions may have been created by deleted
            # tasks — keep the version, drop the task link.
            from t2d_db.models import DashboardVersion

            s.query(DashboardVersion).filter(
                DashboardVersion.task_id.in_(task_ids),
            ).update({DashboardVersion.task_id: None},
                     synchronize_session=False)
            s.query(EvalCaseResult).filter(
                EvalCaseResult.task_id.in_(task_ids)).delete()
            s.query(Task).filter(Task.id.in_(task_ids)).delete()
        if conv_ids:
            s.query(Message).filter(Message.conversation_id.in_(conv_ids)).delete()
            s.query(Conversation).filter(Conversation.id.in_(conv_ids)).delete()
        if empty_ids:
            s.query(DashboardPatch).filter(
                DashboardPatch.dashboard_id.in_(empty_ids)).delete()
            s.query(Dashboard).filter(Dashboard.id.in_(empty_ids)).delete()
        s.commit()

        remaining = s.query(Dashboard).order_by(Dashboard.id).all()
        print(f"清理: {deleted}")
        print("保留的看板:")
        for d in remaining:
            print(f"  #{d.id} {d.title} ({d.status})")


if __name__ == "__main__":
    main()
