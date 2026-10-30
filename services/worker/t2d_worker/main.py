"""Worker entrypoint: queue polling with 2 analysis slots, leases, reaper.

Concurrency (task book §11): 2 analysis tasks in flight, everything else
serialized; leases renewed every TASK_HEARTBEAT_SECONDS; expired leases
reaped (requeue from checkpoint or interrupt). Health endpoint on :8002.
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

from t2d_db import queue
from t2d_db.session import utcnow

from .deps import build_deps
from .runner import TaskRunner
from .scheduler import POLL_INTERVAL_S, poll_refresh_schedules

WORKER_ID = f"worker-{os.getpid()}"
ANALYSIS_CONCURRENCY = int(os.environ.get("TASK_ANALYSIS_CONCURRENCY", "2"))
HEARTBEAT_S = int(os.environ.get("TASK_HEARTBEAT_SECONDS", "10"))
HEALTH_PORT = int(os.environ.get("WORKER_HEALTH_PORT", "8002"))

_running: set[int] = set()
_heartbeat_at = utcnow().isoformat()


def _start_health_server() -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            from t2d_db.models import Task
            from t2d_db.session import get_sessionmaker
            try:
                with get_sessionmaker()() as dbs:
                    queued = dbs.query(Task).filter_by(status="queued").count()
            except Exception:
                queued = -1
            body = json.dumps({
                "status": "ok", "worker": WORKER_ID,
                "running_tasks": sorted(_running),
                "queued_tasks": queued,
                "heartbeat_failures": _hb_failures["count"],
                "heartbeat_at": _heartbeat_at,
            }).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):  # silence
            pass

    server = HTTPServer(("0.0.0.0", HEALTH_PORT), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()


_hb_failures = {"count": 0}


async def _heartbeat_loop() -> None:
    global _heartbeat_at
    while True:
        failed = 0
        for task_id in list(_running):
            try:
                queue.heartbeat(task_id, WORKER_ID)
            except Exception as exc:  # noqa: BLE001
                failed += 1
                print(f"[worker] ⚠️ heartbeat failed for task {task_id}: {exc}",
                      flush=True)
        if failed:
            _hb_failures["count"] += 1
            if _hb_failures["count"] >= 3:
                print(f"[worker] ⚠️⚠️ heartbeat 连续 {_hb_failures['count']} 轮失败——"
                      f"租约可能过期，任务或被回收器重排（注意双执行风险）", flush=True)
        else:
            _hb_failures["count"] = 0
        _heartbeat_at = utcnow().isoformat()
        await asyncio.sleep(HEARTBEAT_S)


async def _run_claimed(runner: TaskRunner, task_id: int, sem: asyncio.Semaphore) -> None:
    async with sem:
        _running.add(task_id)
        try:
            await runner.run_task(task_id)
        finally:
            _running.discard(task_id)
            # If the runner left the task running (crash between status
            # writes), the reaper will pick it up via the expired lease.


async def main() -> None:
    deps = build_deps()
    runner = TaskRunner(deps)
    sem = asyncio.Semaphore(ANALYSIS_CONCURRENCY)
    _start_health_server()
    heartbeat_task = asyncio.create_task(_heartbeat_loop())
    print(f"[worker] {WORKER_ID} started — concurrency={ANALYSIS_CONCURRENCY}, "
          f"model={os.environ.get('MODEL_NAME', '?')}", flush=True)

    last_reap = 0.0
    last_refresh_poll = 0.0
    try:
        while True:
            now = time.monotonic()
            if now - last_reap > 15:
                reaped = queue.reap_expired()
                for tid in reaped:
                    print(f"[worker] reaped expired task {tid}", flush=True)
                last_reap = now
            if now - last_refresh_poll > POLL_INTERVAL_S:
                try:
                    n = poll_refresh_schedules()
                    if n:
                        print(f"[worker] scheduler enqueued {n} refresh task(s)", flush=True)
                except Exception as exc:  # noqa: BLE001 — scheduling must not kill the loop
                    print(f"[worker] refresh poll failed: {exc}", flush=True)
                last_refresh_poll = now
            try:
                claim = queue.claim_next(WORKER_ID)
            except Exception as exc:  # noqa: BLE001 — 轮询失败绝不杀死 worker
                print(f"[worker] ⚠️ claim 轮询失败（1s 后重试）: {exc}", flush=True)
                await asyncio.sleep(1.0)
                continue
            if claim.claimed:
                print(f"[worker] claimed task {claim.task_id}", flush=True)
                asyncio.create_task(_run_claimed(runner, claim.task_id, sem))
            else:
                await asyncio.sleep(1.0)
    finally:
        heartbeat_task.cancel()


if __name__ == "__main__":
    asyncio.run(main())
