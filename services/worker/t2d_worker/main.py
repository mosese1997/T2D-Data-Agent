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

WORKER_ID = f"worker-{os.getpid()}"
ANALYSIS_CONCURRENCY = int(os.environ.get("TASK_ANALYSIS_CONCURRENCY", "2"))
HEARTBEAT_S = int(os.environ.get("TASK_HEARTBEAT_SECONDS", "10"))
HEALTH_PORT = int(os.environ.get("WORKER_HEALTH_PORT", "8002"))

_running: set[int] = set()
_heartbeat_at = utcnow().isoformat()


def _start_health_server() -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            body = json.dumps({
                "status": "ok", "worker": WORKER_ID,
                "running_tasks": sorted(_running),
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


async def _heartbeat_loop() -> None:
    global _heartbeat_at
    while True:
        for task_id in list(_running):
            try:
                queue.heartbeat(task_id, WORKER_ID)
            except Exception:
                pass
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
    try:
        while True:
            now = time.monotonic()
            if now - last_reap > 15:
                reaped = queue.reap_expired()
                for tid in reaped:
                    print(f"[worker] reaped expired task {tid}", flush=True)
                last_reap = now
            claim = queue.claim_next(WORKER_ID)
            if claim.claimed:
                print(f"[worker] claimed task {claim.task_id}", flush=True)
                asyncio.create_task(_run_claimed(runner, claim.task_id, sem))
            else:
                await asyncio.sleep(1.0)
    finally:
        heartbeat_task.cancel()


if __name__ == "__main__":
    asyncio.run(main())
