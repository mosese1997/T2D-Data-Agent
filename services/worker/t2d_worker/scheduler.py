"""Refresh scheduler: enqueue due refresh tasks from refresh_schedules.

Runs inside the worker's poll loop. Idempotency key is bucketed per
(dashboard, scheduled-fire-time) so a re-run never double-enqueues the
same scheduled refresh.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

from croniter import croniter

from t2d_db import queue
from t2d_db.models import Dashboard, RefreshSchedule
from t2d_db.session import get_sessionmaker, utcnow

POLL_INTERVAL_S = int(os.environ.get("REFRESH_POLL_INTERVAL_S", "30"))


def _next_fire(cron: str, base: datetime) -> datetime | None:
    try:
        itr = croniter(cron, base)
        return itr.get_next(datetime)
    except (ValueError, KeyError):
        return None


def poll_refresh_schedules() -> int:
    """Enqueue due refreshes; returns how many were enqueued."""
    maker = get_sessionmaker()
    now = utcnow()
    enqueued = 0
    with maker() as s:
        due = (
            s.query(RefreshSchedule, Dashboard)
            .join(Dashboard, Dashboard.id == RefreshSchedule.dashboard_id)
            .filter(RefreshSchedule.enabled.is_(True))
            .filter(RefreshSchedule.next_run_at.isnot(None))
            .filter(RefreshSchedule.next_run_at <= now)
            .all()
        )
        for schedule, dashboard in due:
            fire_bucket = schedule.next_run_at.strftime("%Y%m%d%H%M")
            task = queue.enqueue(
                type="refresh",
                workspace_id=dashboard.workspace_id,
                user_id=schedule.created_by,
                payload={"dashboard_id": dashboard.id, "scheduled": True},
                idempotency_key=f"refresh-sched:{dashboard.id}:{fire_bucket}",
                dashboard_id=dashboard.id,
                session=s,
            )
            schedule.last_run_at = now
            schedule.next_run_at = _next_fire(schedule.cron, now)
            enqueued += 1
        s.commit()
    return enqueued


def prime_next_run_at(schedule_id: int) -> None:
    """Set next_run_at for a newly created schedule (called by the API)."""
    maker = get_sessionmaker()
    with maker() as s:
        schedule = s.get(RefreshSchedule, schedule_id)
        if schedule is not None and schedule.next_run_at is None:
            schedule.next_run_at = _next_fire(schedule.cron, utcnow())
            s.commit()
