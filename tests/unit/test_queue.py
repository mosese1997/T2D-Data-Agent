"""Unit tests: task queue primitives (SQLite via migrated_db fixture)."""

import pytest

from t2d_db import queue
from t2d_db.models import Task, User, Workspace
from t2d_db.session import session_scope


@pytest.fixture()
def workspace(migrated_db):
    with session_scope() as s:
        user = User(username="queue_test", display_name="QT", password_hash="x")
        s.add(user)
        s.flush()
        ws = Workspace(slug="queue-ws", name="Queue WS", type="personal", created_by=user.id)
        s.add(ws)
        s.flush()
        uid, wid = user.id, ws.id
    # Session committed & closed before yielding — otherwise the open write
    # transaction holds the SQLite lock and every queue call deadlocks.
    yield uid, wid


def test_idempotent_enqueue(migrated_db, workspace):
    uid, wid = workspace
    t1 = queue.enqueue(type="build_dashboard", workspace_id=wid, user_id=uid,
                       payload={"q": "x"}, idempotency_key="idem-1")
    t2 = queue.enqueue(type="build_dashboard", workspace_id=wid, user_id=uid,
                       payload={"q": "x"}, idempotency_key="idem-1")
    assert t1.id == t2.id


def test_claim_single_winner(migrated_db, workspace):
    uid, wid = workspace
    queue.enqueue(type="build_dashboard", workspace_id=wid, user_id=uid,
                  payload={}, idempotency_key="claim-1")
    first = queue.claim_next("worker-a")
    second = queue.claim_next("worker-b")
    assert first.claimed
    assert not second.claimed


def test_claim_respects_priority(migrated_db, workspace):
    uid, wid = workspace
    low = queue.enqueue(type="build_dashboard", workspace_id=wid, user_id=uid,
                        payload={}, idempotency_key="prio-low", priority=200)
    high = queue.enqueue(type="build_dashboard", workspace_id=wid, user_id=uid,
                         payload={}, idempotency_key="prio-high", priority=1)
    claim = queue.claim_next("worker-a")
    assert claim.task_id == high.id


def test_claim_skips_cancelled(migrated_db, workspace):
    uid, wid = workspace
    t = queue.enqueue(type="build_dashboard", workspace_id=wid, user_id=uid,
                      payload={}, idempotency_key="cancel-1")
    queue.request_cancel(t.id)
    assert not queue.claim_next("worker-a").claimed


def test_heartbeat_renews_lease(migrated_db, workspace):
    uid, wid = workspace
    t = queue.enqueue(type="build_dashboard", workspace_id=wid, user_id=uid,
                      payload={}, idempotency_key="hb-1")
    queue.claim_next("worker-a")
    queue.heartbeat(t.id, "worker-a")
    with session_scope() as s:
        task = s.get(Task, t.id)
        assert task.heartbeat_at is not None
        assert task.lease_owner == "worker-a"


def test_reaper_requeues_expired(migrated_db, workspace, monkeypatch):
    import t2d_db.queue as q
    uid, wid = workspace
    t = queue.enqueue(type="build_dashboard", workspace_id=wid, user_id=uid,
                      payload={}, idempotency_key="reap-1")
    queue.claim_next("worker-a")
    # Force the lease into the past.
    from datetime import timedelta
    from t2d_db.session import utcnow
    with session_scope() as s:
        task = s.get(Task, t.id)
        task.lease_expires_at = utcnow() - timedelta(seconds=1)
    changed = queue.reap_expired()
    assert t.id in changed
    with session_scope() as s:
        assert s.get(Task, t.id).status == "queued"


def test_reaper_interrupts_after_max_attempts(migrated_db, workspace):
    from datetime import timedelta
    from t2d_db.session import utcnow
    uid, wid = workspace
    t = queue.enqueue(type="build_dashboard", workspace_id=wid, user_id=uid,
                      payload={}, idempotency_key="reap-max-1")
    with session_scope() as s:
        task = s.get(Task, t.id)
        task.max_attempts = 1
        task.attempt_count = 1
        task.status = "running"
        task.lease_expires_at = utcnow() - timedelta(seconds=1)
    queue.reap_expired()
    with session_scope() as s:
        assert s.get(Task, t.id).status == "interrupted"


def test_event_seq_monotonic(migrated_db, workspace):
    uid, wid = workspace
    t = queue.enqueue(type="build_dashboard", workspace_id=wid, user_id=uid,
                      payload={}, idempotency_key="ev-1")
    with session_scope() as s:
        seq1 = queue.emit_event(s, t.id, "task.created", data={})
        seq2 = queue.emit_event(s, t.id, "phase.started", phase="intent_parse")
    assert seq2 == seq1 + 1
