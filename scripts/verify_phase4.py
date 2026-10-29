#!/usr/bin/env python3
"""Phase 4 acceptance: modify, share, publish (assertion-style).

Checks (task book §17 阶段4 验收 — 草稿到业务空间发布完整闭环):
  1. Multi-round modify on an existing dashboard → revision advances.
  2. Concurrent patches: applying the second one after the first bumped
     the revision → 409 + patch.status=conflict (regeneration required).
  3. Publish approval loop: analyst requests → target admin approves →
     immutable copy lands in the target workspace; target viewer can view.
  4. Share link: public view works WITHOUT auth; viewers still cannot
     drive the agent (403 on message send) — share grants no data rights.
  5. Refresh: manual trigger re-executes bound sources (publisher
     identity), swaps result files in place.
"""

from __future__ import annotations

import json
import os
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
        try:
            return exc.code, json.loads(exc.read() or b"{}")
        except Exception:
            return exc.code, {}


def wait_status(token: str, task_id: int, timeout_s: int = 240) -> dict:
    wanted = {"waiting_for_apply", "failed", "cancelled", "succeeded", "interrupted"}
    deadline = time.time() + timeout_s
    snapshot = {}
    while time.time() < deadline:
        _, snapshot = api("GET", f"/api/tasks/{task_id}", token)
        if snapshot.get("status") in wanted:
            return snapshot
        time.sleep(2)
    return snapshot


def ensure_services() -> bool:
    try:
        with urllib.request.urlopen(f"{API}/api/healthz", timeout=3):
            return True
    except Exception:
        pass
    return subprocess_run_up()


def subprocess_run_up() -> bool:
    import subprocess

    return subprocess.run(["bash", "scripts/dev_up.sh"], capture_output=True).returncode == 0


def main() -> int:
    print("═══ 阶段 4 验收 verify_phase4 ═══")
    if not ensure_services():
        print("❌ 无法启动服务")
        return 1
    all_ok = True

    _, analyst = api("POST", "/api/auth/login",
                     body={"username": "analyst_a", "password": "analyst-demo-2026"})
    token_a = analyst["token"]
    _, admin = api("POST", "/api/auth/login",
                   body={"username": "admin", "password": "admin-demo-2026"})
    token_admin = admin["token"]
    _, viewer_c = api("POST", "/api/auth/login",
                      body={"username": "viewer_c", "password": "viewer-demo-2026"})
    token_vc = viewer_c["token"]

    # Find mx-focus workspace id (publish target; viewer_c is a member).
    _, workspaces = api("GET", "/api/workspaces", token_admin)
    ws_by_slug = {w["slug"]: w["id"] for w in workspaces}
    mx_id = ws_by_slug["mx-focus"]

    # ── 1+2. multi-round modify & conflict ──────────────────────────
    print("\n[1] 多轮修改（既有看板）")
    # Build a fresh dashboard first (deterministic starting point).
    _, conv = api("POST", "/api/conversations", token_a,
                  {"workspace_id": ws_by_slug["latam-growth"], "title": "p4"})
    _, sent = api("POST", f"/api/conversations/{conv['id']}/messages", token_a,
                  {"content": "上周各国家GMV对比"})
    snap = wait_status(token_a, sent["task_id"])
    ok = check("build task ok", snap.get("status") == "waiting_for_apply",
               snap.get("status", "?"))
    if snap.get("status") != "waiting_for_apply":
        print("    error:", json.dumps(snap.get("error"), ensure_ascii=False)[:200])
        _summary()
        return 1
    dashboard_id = snap["result"]["dashboard_id"]
    _, applied = api("POST", f"/api/patches/{snap['result']['patch_id']}/apply", token_a)
    ok &= check("initial apply", applied.get("revision") == 1)
    all_ok &= ok

    print("\n[2] 并发候选变更冲突")
    # Two modify tasks on the same dashboard (both patch against revision 1).
    _, conv2 = api("POST", "/api/conversations", token_a,
                   {"workspace_id": ws_by_slug["latam-growth"],
                    "dashboard_id": dashboard_id, "title": "p4-mod1"})
    _, m1 = api("POST", f"/api/conversations/{conv2['id']}/messages", token_a,
                {"content": "把看板标题改为「GMV 周报」"})
    snap1 = wait_status(token_a, m1["task_id"])
    _, conv3 = api("POST", "/api/conversations", token_a,
                   {"workspace_id": ws_by_slug["latam-growth"],
                    "dashboard_id": dashboard_id, "title": "p4-mod2"})
    _, m2 = api("POST", f"/api/conversations/{conv3['id']}/messages", token_a,
                {"content": "加一个说明文字组件，内容为「数据口径见 Wiki」"})
    snap2 = wait_status(token_a, m2["task_id"])
    ok = check("two pending patches",
               snap1.get("status") == "waiting_for_apply"
               and snap2.get("status") == "waiting_for_apply",
               f"{snap1.get('status')}/{snap2.get('status')}")
    if snap1.get("status") != "waiting_for_apply" or snap2.get("status") != "waiting_for_apply":
        for name, snap in (("task1", snap1), ("task2", snap2)):
            print(f"    {name}: {snap.get('status')} "
                  f"{json.dumps(snap.get('error'), ensure_ascii=False)[:150]}")
        _summary()
        return 1
    patch1 = snap1["result"]["patch_id"]
    patch2 = snap2["result"]["patch_id"]
    code, first = api("POST", f"/api/patches/{patch1}/apply", token_a)
    ok &= check("apply first patch", code == 200 and first.get("revision") == 2,
                json.dumps(first)[:80])
    code2, second = api("POST", f"/api/patches/{patch2}/apply", token_a)
    ok &= check("second patch conflicts (409)", code2 == 409, json.dumps(second)[:100])
    from t2d_db.models import DashboardPatch
    from t2d_db.session import get_sessionmaker

    with get_sessionmaker()() as s:
        status2 = s.get(DashboardPatch, patch2).status
    ok &= check("conflicted patch marked conflict", status2 == "conflict", status2)
    all_ok &= ok

    # ── 3. publish approval loop ────────────────────────────────────
    print("\n[3] 审批发布闭环（latam-growth → mx-focus）")
    code, pub = api("POST", f"/api/dashboards/{dashboard_id}/publish", token_a,
                    {"target_workspace_id": mx_id, "comment": "阶段4验收"})
    ok = check("publish request pending", code == 200 and pub.get("status") == "pending",
               json.dumps(pub)[:80])
    _, requests = api("GET", "/api/requests", token_admin)
    mine = [r for r in requests if r.get("publication_id") == pub.get("publication_id")]
    ok &= check("admin sees the request", len(mine) == 1)
    approval_id = mine[0]["approval_id"] if mine else None
    code, approved = api("POST", f"/api/approvals/{approval_id}/approve", token_admin)
    ok &= check("admin approves", code == 200 and approved.get("status") == "published",
                json.dumps(approved)[:80])
    published_id = approved.get("published_dashboard_id")
    # Target-space viewer sees the published copy with data.
    code, published = api("GET", f"/api/dashboards/{published_id}", token_vc)
    ok &= check("target viewer views published dashboard", code == 200
                and published.get("status") == "published")
    bound = [c for c in (published.get("canvas") or {}).get("components", [])
             if c.get("source_id")]
    rows_ok = bool(bound)
    for comp in bound[:2]:
        code, rows = api("GET", f"/api/sources/{comp['source_id']}/rows?size=1", token_vc)
        if code != 200 or rows.get("row_count", 0) < 1:
            rows_ok = False
    ok &= check("target viewer reads published data", rows_ok)
    # Analyst_a is NOT an mx-focus member → must NOT see the published copy.
    code, _ = api("GET", f"/api/dashboards/{published_id}", token_a)
    ok &= check("non-member denied (403/404)", code in (403, 404), f"status={code}")
    all_ok &= ok

    # ── 4. share link ───────────────────────────────────────────────
    print("\n[4] 分享链接（仅视图，不授数据权限）")
    code, share = api("POST", f"/api/dashboards/{dashboard_id}/shares", token_a,
                      {"expires_in_hours": 24})
    ok = check("share created", code == 200 and share.get("share_token"))
    # Public access WITHOUT any token:
    req = urllib.request.Request(f"{API}/api/shared/{share['share_token']}")
    with urllib.request.urlopen(req, timeout=10) as resp:
        shared = json.loads(resp.read())
    ok &= check("public share view works", shared.get("shared_view") is True
                and bool(shared.get("data")))
    ok &= check("share exposes no SQL", "sql" not in json.dumps(shared))
    # Viewers still cannot drive the agent:
    code, _ = api("POST", f"/api/conversations/{conv['id']}/messages", token_vc,
                  {"content": "改一下"})
    ok &= check("viewer cannot send agent messages (403)", code == 403, f"status={code}")
    all_ok &= ok

    # ── 5. refresh ──────────────────────────────────────────────────
    print("\n[5] 刷新（publisher 身份重执行 Source）")
    from t2d_db.models import Source

    # Refresh targets the ORIGINAL dashboard; the published copy is an
    # immutable snapshot and must NOT change (that's the point of §14).
    _, original = api("GET", f"/api/dashboards/{dashboard_id}", token_a)
    with get_sessionmaker()() as s:
        first_bound = next(c["source_id"] for c in
                           (original.get("canvas") or {}).get("components", [])
                           if c.get("source_id"))
        before_file = s.get(Source, int(first_bound)).result_file_id
    code, ref_task = api("POST", f"/api/dashboards/{dashboard_id}/refresh", token_a)
    ok = check("refresh task enqueued", code == 200)
    snap = wait_status(token_a, ref_task["task_id"], timeout_s=180)
    ok &= check("refresh task succeeded", snap.get("status") == "succeeded",
                f"{snap.get('status')} {json.dumps(snap.get('error'), ensure_ascii=False)[:100]}")
    with get_sessionmaker()() as s:
        after_file = s.get(Source, int(first_bound)).result_file_id
    ok &= check("result file swapped in place", before_file != after_file,
                f"{before_file} → {after_file}")
    code, rows = api("GET", f"/api/sources/{first_bound}/rows?size=1", token_a)
    ok &= check("refreshed rows readable", code == 200 and rows.get("row_count", 0) >= 1)
    all_ok &= ok

    _summary()
    required_failed = [name for name, ok_, _, req in RESULTS if not ok_ and req]
    if required_failed:
        print(f"\n❌ 阶段 4 验收未通过：{required_failed}")
        return 1
    print("\n✅ 阶段 4 验收全部通过")
    return 0


def _summary() -> None:
    print("\n═══ 结果 ═══")
    for name, ok, detail, req in RESULTS:
        print(f"  {'✅' if ok else ('❌' if req else '⚠️ ')} {name}")
    passed = sum(1 for r in RESULTS if r[1])
    print(f"\n通过 {passed}/{len(RESULTS)}")


if __name__ == "__main__":
    sys.exit(main())
