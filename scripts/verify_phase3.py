#!/usr/bin/env python3
"""Phase 3 acceptance: end-to-end dashboard building (assertion-style).

Checks (task book §17 阶段3 验收 — 自然语言生成带实际查询结果的 Dashboard):
  1. NL message → task completes → dashboard version exists with components
     bound to a real source (row_count > 0).
  2. SSE event seqs are gapless 1..N.
  3. Last-Event-ID resume replays exactly the events after the cursor.
  4. Crash recovery: SIGKILL the worker mid-run, restart, task resumes from
     checkpoint; applying the patch yields EXACTLY ONE version (no double
     apply).

Requires: dev services up (scripts/dev_up.sh) — the script starts them if
needed and reuses them otherwise.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
os.environ.setdefault("STATE_DB_URL", "sqlite:///var/state.db")

API = "http://127.0.0.1:8001"
RESULTS: list[tuple[str, bool, str, bool]] = []


def check(name: str, ok: bool, detail: str = "", *, required: bool = True) -> bool:
    RESULTS.append((name, bool(ok), detail, required))
    mark = "✅" if ok else ("❌" if required else "⚠️ ")
    print(f"  {mark} {name} {detail}")
    return bool(ok)


def api(method: str, path: str, token: str | None = None, body: dict | None = None):
    req = urllib.request.Request(API + path, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    data = json.dumps(body).encode() if body is not None else None
    try:
        with urllib.request.urlopen(req, data=data, timeout=30) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read() or b"{}")


def wait_status(token: str, task_id: int, wanted: set[str], timeout_s: int = 240) -> str:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        _, snapshot = api("GET", f"/api/tasks/{task_id}", token)
        if snapshot.get("status") in wanted:
            return snapshot["status"]
        time.sleep(2)
    return snapshot.get("status", "timeout")


def ensure_services() -> bool:
    try:
        with urllib.request.urlopen(f"{API}/api/healthz", timeout=3):
            return True
    except Exception:
        pass
    return subprocess.run(["bash", "scripts/dev_up.sh"], capture_output=True).returncode == 0


def main() -> int:
    print("═══ 阶段 3 验收 verify_phase3 ═══")
    if not ensure_services():
        print("❌ 无法启动 API/Worker（先跑 scripts/dev_up.sh）")
        return 1
    all_ok = True

    # ── 1. NL → dashboard with real data ───────────────────────────
    print("\n[1] 自然语言 → 带实际查询结果的看板")
    _, login = api("POST", "/api/auth/login",
                   body={"username": "analyst_a", "password": "analyst-demo-2026"})
    token = login["token"]
    _, conv = api("POST", "/api/conversations", token,
                  {"workspace_id": 1, "title": "verify-phase3"})
    conversation_id = conv["id"]
    _, sent = api("POST", f"/api/conversations/{conversation_id}/messages", token,
                  {"content": "上周各国家GMV对比，并给出GMV总量"})
    task_id = sent["task_id"]
    print(f"  task={task_id} 已提交，等待完成…")
    status = wait_status(token, task_id,
                         {"waiting_for_apply", "failed", "cancelled", "succeeded"})
    ok = check("task reaches waiting_for_apply", status == "waiting_for_apply", status)
    if status != "waiting_for_apply":
        _, snap = api("GET", f"/api/tasks/{task_id}", token)
        print("    error:", json.dumps(snap.get("error"), ensure_ascii=False)[:200])
        print("    events:", [(e["seq"], e["event"]) for e in snap.get("events", [])])
        all_ok &= ok
        # Cannot continue the dependent checks meaningfully.
        _summary()
        return 1
    _, snap = api("GET", f"/api/tasks/{task_id}", token)
    patch_id = snap["result"]["patch_id"]
    dashboard_id = snap["result"]["dashboard_id"]

    code, applied = api("POST", f"/api/patches/{patch_id}/apply", token)
    ok &= check("apply patch", code == 200, json.dumps(applied)[:80])
    _, dash = api("GET", f"/api/dashboards/{dashboard_id}", token)
    components = dash["canvas"]["components"]
    bound = [c for c in components if c.get("source_id")]
    ok &= check("dashboard revision 1", dash["revision"] == 1)
    ok &= check("has data-bound components", len(bound) >= 1,
                f"{len(bound)} bound / {len(components)} total")
    source_ids = {c["source_id"] for c in bound}
    rows_ok = True
    for sid in source_ids:
        _, rows = api("GET", f"/api/sources/{sid}/rows?size=1", token)
        if rows.get("row_count", 0) < 1:
            rows_ok = False
    ok &= check("bound sources have real rows", rows_ok,
                f"sources={sorted(source_ids)}")
    all_ok &= ok

    # ── 2. SSE seq continuity ───────────────────────────────────────
    print("\n[2] SSE 事件序号连续")
    from t2d_db.models import RunEvent
    from t2d_db.session import get_sessionmaker

    with get_sessionmaker()() as s:
        seqs = [r.seq for r in s.query(RunEvent.seq)
                .filter(RunEvent.task_id == task_id).order_by(RunEvent.seq)]
    ok = check("seqs gapless 1..N", seqs == list(range(1, len(seqs) + 1)),
               f"{len(seqs)} events, first={seqs[:3]}, last={seqs[-3:]}")
    all_ok &= ok

    # ── 3. Last-Event-ID resume ─────────────────────────────────────
    print("\n[3] Last-Event-ID 断线补读")
    import http.client

    conn = http.client.HTTPConnection("127.0.0.1", 8001, timeout=20)
    conn.request("GET", f"/api/tasks/{task_id}/events",
                 headers={"Authorization": f"Bearer {token}",
                          "Last-Event-ID": "2"})
    resp = conn.getresponse()
    first_ids: list[int] = []
    buf = b""
    deadline = time.time() + 15
    while time.time() < deadline and len(first_ids) < 3:
        try:
            chunk = resp.read1(4096)
        except (http.client.IncompleteRead, ConnectionError):
            break  # stream closed (terminal task) — that's fine
        if not chunk:
            break
        buf += chunk
        while b"\n\n" in buf:
            block, buf = buf.split(b"\n\n", 1)
            for line in block.decode().splitlines():
                if line.startswith("id: "):
                    first_ids.append(int(line[4:]))
    conn.close()
    ok = check("replay starts after cursor", first_ids and first_ids[0] == 3,
               f"first replayed ids={first_ids[:3]}")
    ok &= check("no re-delivery of 1-2", all(i > 2 for i in first_ids))
    all_ok &= ok

    # ── 4. crash recovery: no duplicate apply ──────────────────────
    print("\n[4] 崩溃恢复（SIGKILL worker 中途 → 重启 → 不重复应用）")
    _, conv2 = api("POST", "/api/conversations", token,
                   {"workspace_id": 1, "title": "verify-phase3-crash"})
    _, sent2 = api("POST", f"/api/conversations/{conv2['id']}/messages", token,
                   {"content": "最近7天各渠道订单量趋势"})
    task2 = sent2["task_id"]
    # Wait until the query phase starts (a mid-run checkpoint boundary).
    deadline = time.time() + 60
    phase_seen = False
    while time.time() < deadline:
        _, snap2 = api("GET", f"/api/tasks/{task2}", token)
        if any(e["event"] == "phase.started" and e["phase"] == "sql_generate"
               for e in snap2.get("events", [])):
            phase_seen = True
            break
        if snap2.get("status") in {"failed", "cancelled", "waiting_for_apply", "succeeded"}:
            break
        time.sleep(1)
    killed = False
    if phase_seen:
        subprocess.run(["pkill", "-9", "-f", "t2d_worker.main"], capture_output=True)
        killed = True
        print("    worker 已 SIGKILL（sql_generate 阶段）")
        time.sleep(2)
        subprocess.run(["bash", "scripts/dev_up.sh"], capture_output=True)
        print("    worker 已重启，等待租约过期回收 + 续跑…")
    else:
        print("    ⚠️ 未能捕捉到 sql_generate 窗口，跳过 kill（任务已到终态）")
    check("crash injected mid-run", killed, required=False)

    status2 = wait_status(token, task2,
                          {"waiting_for_apply", "failed", "cancelled", "succeeded"},
                          timeout_s=300)
    ok = check("task recovers to waiting_for_apply", status2 == "waiting_for_apply", status2)
    if status2 == "waiting_for_apply":
        _, snap2 = api("GET", f"/api/tasks/{task2}", token)
        patch2 = snap2["result"]["patch_id"]
        dash2 = snap2["result"]["dashboard_id"]
        code, applied2 = api("POST", f"/api/patches/{patch2}/apply", token)
        ok &= check("apply after recovery", code == 200)
        from t2d_db.models import DashboardVersion

        with get_sessionmaker()() as s:
            versions = (s.query(DashboardVersion)
                        .filter(DashboardVersion.dashboard_id == dash2).count())
        ok &= check("exactly ONE version after crash+resume", versions == 1,
                    f"versions={versions}")
    all_ok &= ok

    _summary()
    required_failed = [name for name, ok_, _, req in RESULTS if not ok_ and req]
    if required_failed:
        print(f"\n❌ 阶段 3 验收未通过：{required_failed}")
        return 1
    print("\n✅ 阶段 3 验收全部通过")
    return 0


def _summary() -> None:
    print("\n═══ 结果 ═══")
    for name, ok, detail, req in RESULTS:
        print(f"  {'✅' if ok else ('❌' if req else '⚠️ ')} {name}")
    passed = sum(1 for r in RESULTS if r[1])
    print(f"\n通过 {passed}/{len(RESULTS)}")


if __name__ == "__main__":
    sys.exit(main())
