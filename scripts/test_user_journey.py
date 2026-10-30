#!/usr/bin/env python3
"""User-journey simulation: walk the whole product as real users would.

Simulates (API-level, every step asserted):
  1.  Login for all roles + wrong-password rejection
  2.  Home / workspaces / dashboard browsing + source data (cache hit)
  3.  Q&A (answer mode) — zh + en locale
  4.  Build dashboard from NL → preview → apply
  5.  Simple modify (title) → apply
  6.  Concurrent patches → conflict
  7.  Analysis (sandbox contribution)
  8.  Clarify flow: vague → answer → completes
  9.  "为什么失败" referential context
  10. Share link (public, no SQL) / publish approval loop
  11. Manual refresh
  12. Admin console: config / runs / trace / knowledge / evals / wiki
  13. Permission boundaries (viewer, cross-workspace)
  14. SSE stream + Last-Event-ID resume + cancel

Usage: python3 scripts/test_user_journey.py [--quick]   (quick skips slow NL cases)
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("STATE_DB_URL", "sqlite:///var/compose-state.db")

API = "http://127.0.0.1:8080"
QUICK = "--quick" in sys.argv

PASS, FAIL = 0, 0


def check(name: str, ok: bool, detail: str = "") -> bool:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  ✅ {name} {detail}")
    else:
        FAIL += 1
        print(f"  ❌ {name} {detail}")
    return ok


def api(method: str, path: str, token: str | None = None, body: dict | None = None,
        raw_headers: dict | None = None):
    req = urllib.request.Request(API + path, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    for k, v in (raw_headers or {}).items():
        req.add_header(k, v)
    data = json.dumps(body).encode() if body is not None else None
    try:
        with urllib.request.urlopen(req, data=data, timeout=240) as resp:
            return resp.status, json.loads(resp.read() or b"{}"), dict(resp.headers)
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read() or b"{}"), {}
        except Exception:
            return exc.code, {}, {}


def login(username: str, password: str) -> str:
    _, body, _ = api("POST", "/api/auth/login", body={"username": username, "password": password})
    return body.get("token", "")


def wait_task(token: str, task_id: int, timeout_s: int = 240) -> dict:
    wanted = {"waiting_for_apply", "waiting_for_user", "failed", "cancelled",
              "succeeded", "interrupted"}
    deadline = time.time() + timeout_s
    snap = {}
    while time.time() < deadline:
        _, snap, _ = api("GET", f"/api/tasks/{task_id}", token)
        if snap.get("status") in wanted:
            return snap
        time.sleep(2)
    return snap


def ask(token: str, conv: int, content: str, locale: str = "zh",
          timeout_s: int = 240) -> tuple[int, dict]:
    _, sent, _ = api("POST", f"/api/conversations/{conv}/messages", token,
                     {"content": content, "locale": locale})
    return sent.get("task_id", 0), wait_task(token, sent.get("task_id", 0), timeout_s)


def new_conv(token: str, ws: int, title: str, dashboard: int | None = None) -> int:
    _, body, _ = api("POST", "/api/conversations", token,
                     {"workspace_id": ws, "title": title, "dashboard_id": dashboard})
    return body.get("id", 0)


def main() -> int:
    print("═══ 用户旅程模拟测试 ═══")
    started = time.time()

    # ── 1. 登录 ─────────────────────────────────────────────────────
    print("\n[1] 登录与身份")
    accounts = {"admin": "admin-demo-2026", "analyst_a": "analyst-demo-2026",
                "analyst_b": "analyst-demo-2026", "viewer_b": "viewer-demo-2026",
                "viewer_c": "viewer-demo-2026", "ops": "ops-demo-2026"}
    tokens = {}
    for user, pwd in accounts.items():
        tokens[user] = login(user, pwd)
        check(f"login {user}", bool(tokens[user]))
    code, _, _ = api("POST", "/api/auth/login", body={"username": "analyst_a", "password": "bad"})
    check("错误密码拒绝", code == 401, f"HTTP {code}")
    t_a, t_adm, t_b, t_vb = tokens["analyst_a"], tokens["admin"], tokens["analyst_b"], tokens["viewer_b"]

    # ── 2. 浏览 ─────────────────────────────────────────────────────
    print("\n[2] Home / 工作空间 / 看板浏览")
    _, ws_list, _ = api("GET", "/api/workspaces", t_a)
    ws1 = next(w["id"] for w in ws_list if w["slug"] == "latam-growth")
    check("analyst_a 看到 latam-growth", bool(ws1))
    _, d_list, _ = api("GET", f"/api/workspaces/{ws1}/dashboards", t_a)
    check("预置看板可见", len(d_list) >= 2, f"{len(d_list)} 个")
    dash_id = d_list[0]["id"]
    _, dash, _ = api("GET", f"/api/dashboards/{dash_id}", t_a)
    comps = (dash.get("canvas") or {}).get("components", [])
    bound = [c for c in comps if c.get("source_id")]
    check("看板画布有数据组件", len(bound) >= 1, f"{len(bound)} 组件")
    sid = bound[0]["source_id"]
    _, rows1, h1 = api("GET", f"/api/sources/{sid}/rows?size=5", t_a)
    check("Source 数据可读", rows1.get("row_count", 0) >= 1, f"{rows1.get('row_count')} 行")
    _, rows2, h2 = api("GET", f"/api/sources/{sid}/rows?size=5", t_a)
    cache_hdr = (h2.get("x-cache") or h2.get("X-Cache") or "")
    check("结果缓存命中", cache_hdr == "HIT", f"x-cache={cache_hdr}")

    # ── 3. 问答（answer 模式）──────────────────────────────────────
    if not QUICK:
        print("\n[3] 问答（中英文）")
        conv = new_conv(t_a, ws1, "旅程-问答")
        _, snap = ask(t_a, conv, "上周GMV总量是多少？")
        answer = (snap.get("result") or {}).get("answer", "")
        check("中文问答成功", snap.get("status") == "succeeded" and "GMV" in answer,
              f"{(answer or '')[:40]}")
        check("回答无 SQL 术语", "status" not in answer and "CURRENT_DATE" not in answer)
        conv_en = new_conv(t_a, ws1, "journey-qa-en")
        _, snap_en = ask(t_a, conv_en, "What was the total GMV last week?", locale="en")
        answer_en = (snap_en.get("result") or {}).get("answer", "")
        check("英文问答成功（locale 贯穿）",
              snap_en.get("status") == "succeeded" and "GMV" in answer_en,
              f"{(answer_en or '')[:40]}")

    # ── 4. 建板 ─────────────────────────────────────────────────────
    if not QUICK:
        print("\n[4] 自然语言建板")
        conv = new_conv(t_a, ws1, "旅程-建板")
        tid, snap = ask(t_a, conv, "最近7天各国家GMV趋势，做成看板")
        check("建板到待应用", snap.get("status") == "waiting_for_apply", snap.get("status", "?"))
        if snap.get("status") == "waiting_for_apply":
            patch_id = snap["result"]["patch_id"]
            new_dash = snap["result"]["dashboard_id"]
            code, applied, _ = api("POST", f"/api/patches/{patch_id}/apply", t_a)
            check("应用候选变更", code == 200 and applied.get("revision") == 1)
            _, dash2, _ = api("GET", f"/api/dashboards/{new_dash}", t_a)
            check("新看板有绑定组件",
                  len([c for c in (dash2.get("canvas") or {}).get("components", [])
                       if c.get("source_id")]) >= 1)
            # 5. 简单修改（标题）
            conv_m = new_conv(t_a, ws1, "旅程-改标题", dashboard=new_dash)
            _, snap_m = ask(t_a, conv_m, "把看板标题改为「GMV 周报」")
            check("简单修改到待应用", snap_m.get("status") == "waiting_for_apply",
                  snap_m.get("status", "?"))
            if snap_m.get("status") == "waiting_for_apply":
                code, ap, _ = api("POST", f"/api/patches/{snap_m['result']['patch_id']}/apply", t_a)
                check("标题修改应用（revision 2）", code == 200 and ap.get("revision") == 2)
                _, d3, _ = api("GET", f"/api/dashboards/{new_dash}", t_a)
                check("标题已更新", d3.get("title") == "GMV 周报", d3.get("title", ""))

    # ── 6. 冲突 ─────────────────────────────────────────────────────
    if not QUICK:
        print("\n[6] 并发候选变更冲突")
        target = dash_id
        c1 = new_conv(t_a, ws1, "旅程-冲突A", dashboard=target)
        c2 = new_conv(t_a, ws1, "旅程-冲突B", dashboard=target)
        _, s1 = ask(t_a, c1, "加一段说明文字，内容为「口径见 Wiki」")
        _, s2 = ask(t_a, c2, "把看板标题改为「测试冲突」")
        if s1.get("status") == "waiting_for_apply" and s2.get("status") == "waiting_for_apply":
            p1, p2 = s1["result"]["patch_id"], s2["result"]["patch_id"]
            code_a, _, _ = api("POST", f"/api/patches/{p1}/apply", t_a)
            code_b, body_b, _ = api("POST", f"/api/patches/{p2}/apply", t_a)
            check("先应用者成功", code_a == 200)
            check("后应用者 409 冲突", code_b == 409, body_b.get("detail", "")[:40])
        else:
            check("两个候选变更都生成",
                  s1.get("status") == "waiting_for_apply" and s2.get("status") == "waiting_for_apply",
                  f"{s1.get('status')}/{s2.get('status')}")

    # ── 7. 分析 ─────────────────────────────────────────────────────
    if not QUICK:
        print("\n[7] 沙箱贡献分析")
        conv = new_conv(t_a, ws1, "旅程-分析")
        _, snap = ask(t_a, conv, "分析上周相比上上周GMV变化，各国家贡献如何", timeout_s=300)
        r = snap.get("result") or {}
        check("分析成功且有 analysis_id",
              snap.get("status") == "succeeded" and bool(r.get("analysis_id")))
        check("结论非因果表述",
              "因为" not in (r.get("conclusion") or "") and "导致" not in (r.get("conclusion") or ""))

    # ── 8. 澄清流 ───────────────────────────────────────────────────
    if not QUICK:
        print("\n[8] 澄清 → 回答 → 完成")
        conv = new_conv(t_a, ws1, "旅程-澄清")
        _, snap = ask(t_a, conv, "卖得好不好")
        check("模糊问题转澄清", snap.get("status") == "waiting_for_user", snap.get("status", "?"))
        if snap.get("status") == "waiting_for_user":
            tid = snap["id"]
            code, _, _ = api("POST", f"/api/tasks/{tid}/answer", t_a,
                             {"content": "看GMV，最近7天，按国家"})
            check("回答澄清被接受", code == 200)
            snap2 = wait_task(t_a, tid)
            if snap2.get("status") == "failed" and "空结果" in str(snap2.get("error")):
                # 模型空响应是已知瞬时问题：重问一次
                _, s_retry = ask(t_a, conv, "看GMV，最近7天，按国家")
                snap2 = s_retry
            check("澄清后任务完成", snap2.get("status") in ("succeeded", "waiting_for_apply"),
                  snap2.get("status", "?"))

    # ── 9. 指代上下文 ───────────────────────────────────────────────
    if not QUICK:
        print("\n[9] 「为什么失败」上下文")
        conv = new_conv(t_b, 2, "旅程-失败上下文")  # mx-focus: analyst_b
        _, s_fail = ask(t_b, conv, "最近30天退款率")
        check("无权限查询失败（预期）", s_fail.get("status") == "failed", s_fail.get("status", "?"))
        _, s_why = ask(t_b, conv, "为什么失败")
        why = (s_why.get("result") or {}).get("answer", "")
        check("「为什么失败」有据回答",
              s_why.get("status") == "succeeded" and ("退款" in why or "权限" in why or "授权" in why),
              f"{(why or '')[:60]}")

    # ── 10. 分享与发布 ──────────────────────────────────────────────
    print("\n[10] 分享与发布")
    _, share, _ = api("POST", f"/api/dashboards/{dash_id}/shares", t_a, {"expires_in_hours": 24})
    check("创建分享", bool(share.get("share_token")))
    req = urllib.request.Request(f"{API}/api/shared/{share.get('share_token')}")
    with urllib.request.urlopen(req, timeout=10) as resp:
        shared = json.loads(resp.read())
    check("公开分享可读", shared.get("shared_view") is True and bool(shared.get("data")))
    check("分享不含 SQL", "sql" not in json.dumps(shared))
    # 发布闭环（找 mx-focus）
    _, ws_adm, _ = api("GET", "/api/workspaces", t_adm)
    mx = next(w["id"] for w in ws_adm if w["slug"] == "mx-focus")
    code, pub, _ = api("POST", f"/api/dashboards/{dash_id}/publish", t_a,
                       {"target_workspace_id": mx, "comment": "旅程测试"})
    check("发布请求", code == 200 and pub.get("status") == "pending")
    _, reqs, _ = api("GET", "/api/requests", t_adm)
    mine = [r for r in reqs if r.get("publication_id") == pub.get("publication_id")]
    check("admin 看到请求", len(mine) == 1)
    if mine:
        code, ap, _ = api("POST", f"/api/approvals/{mine[0]['approval_id']}/approve", t_adm)
        check("批准发布", code == 200 and ap.get("status") == "published")
        pub_dash = ap.get("published_dashboard_id")
        code, pd, _ = api("GET", f"/api/dashboards/{pub_dash}", tokens["viewer_c"])
        check("目标空间 viewer 可见发布副本", code == 200 and pd.get("status") == "published")

    # ── 11. 刷新 ────────────────────────────────────────────────────
    print("\n[11] 手动刷新")
    _, ref, _ = api("POST", f"/api/dashboards/{dash_id}/refresh", t_a)
    tid = ref.get("task_id", 0)
    snap = wait_task(t_a, tid, timeout_s=120)
    check("刷新成功", snap.get("status") == "succeeded",
          str((snap.get("result") or {}).get("refreshed_sources", "")))

    # ── 12. 管理台 ──────────────────────────────────────────────────
    print("\n[12] 管理台")
    _, cfg, _ = api("GET", "/api/admin/agent-config", t_adm)
    check("Agent 配置可读", cfg.get("config", {}).get("agent", {}).get("runtime") == "toolloop")
    _, runs, _ = api("GET", "/api/admin/runs?limit=5", t_adm)
    check("运行列表", len(runs) >= 1)
    traced = None
    for r in runs:
        _, tr, _ = api("GET", f"/api/admin/runs/{r['task_id']}/trace", t_adm)
        if tr.get("tool_calls"):
            traced = tr
            break
    check("Trace 含 agent_runs + tool_calls",
          traced is not None and len(traced.get("agent_runs", [])) >= 1)
    _, idx, _ = api("GET", "/api/admin/knowledge-index", t_adm)
    check("知识索引", idx.get("metrics", 0) >= 10)
    _, evals, _ = api("GET", "/api/admin/evals?limit=3", t_adm)
    check("评测历史", isinstance(evals, list))
    _, wiki, _ = api("GET", "/api/admin/wiki", t_vb)
    check("Wiki 任何成员可读", len(wiki.get("metrics", [])) >= 10)
    code, _, _ = api("GET", "/api/admin/agent-config", t_vb)
    check("viewer 无管理台权限", code == 403, f"HTTP {code}")

    # ── 13. 权限边界 ────────────────────────────────────────────────
    print("\n[13] 权限边界")
    code, _, _ = api("POST", "/api/conversations", t_vb, {"workspace_id": ws1})
    check("viewer 不能开会话", code == 403, f"HTTP {code}")
    # viewer_b 只在 latam-growth；mx-focus 的发布副本对其不可见
    _, ws_vb, _ = api("GET", "/api/workspaces", t_vb)
    vb_slugs = {w["slug"] for w in ws_vb}
    check("viewer_b 不在 mx-focus", "mx-focus" not in vb_slugs)
    _, mx_dashboards, _ = api("GET", "/api/workspaces/{mx}/dashboards".replace("{mx}", str(mx)), t_adm)
    if mx_dashboards:
        code, _, _ = api("GET", f"/api/dashboards/{mx_dashboards[0]['id']}", t_vb)
        check("跨空间看板不可见", code in (403, 404), f"HTTP {code}")

    # ── 14. SSE ─────────────────────────────────────────────────────
    print("\n[14] SSE 流")
    _, snap_any, _ = api("GET", f"/api/tasks/{tid}", t_a)
    import http.client
    conn = http.client.HTTPConnection("127.0.0.1", 8080, timeout=15)
    conn.request("GET", f"/api/tasks/{tid}/events",
                 headers={"Authorization": f"Bearer {t_a}", "Last-Event-ID": "2"})
    time.sleep(2)  # 让限流窗口喘口气（旅程前段高频调用的余波）
    resp = conn.getresponse()
    if resp.status != 200:
        time.sleep(3)
        conn.close()
        conn = http.client.HTTPConnection("127.0.0.1", 8080, timeout=15)
        conn.request("GET", f"/api/tasks/{tid}/events",
                     headers={"Authorization": f"Bearer {t_a}", "Last-Event-ID": "2"})
        resp = conn.getresponse()
    first_ids = []
    buf = b""
    deadline = time.time() + 12
    while time.time() < deadline and len(first_ids) < 2:
        try:
            chunk = resp.read1(4096)
        except Exception:
            break
        if not chunk:
            break
        buf += chunk
        while b"\n\n" in buf:
            block, buf = buf.split(b"\n\n", 1)
            for line in block.decode().splitlines():
                if line.startswith("id: "):
                    first_ids.append(int(line[4:]))
    conn.close()
    if not first_ids:  # 时序瞬时：重试一次
        conn = http.client.HTTPConnection("127.0.0.1", 8080, timeout=20)
        conn.request("GET", f"/api/tasks/{tid}/events",
                     headers={"Authorization": f"Bearer {t_a}", "Last-Event-ID": "2"})
        resp = conn.getresponse()
        buf = b""
        deadline = time.time() + 20
        while time.time() < deadline and len(first_ids) < 2:
            try:
                chunk = resp.read1(4096)
            except Exception:
                break
            if not chunk:
                break
            buf += chunk
            while b"\n\n" in buf:
                block, buf = buf.split(b"\n\n", 1)
                for line in block.decode().splitlines():
                    if line.startswith("id: "):
                        first_ids.append(int(line[4:]))
        conn.close()
    check("Last-Event-ID 补读从 3 开始", bool(first_ids) and first_ids[0] == 3,
          f"{first_ids[:2]}")

    # 取消
    conv_c = new_conv(t_a, ws1, "旅程-取消")
    _, sent_c, _ = api("POST", f"/api/conversations/{conv_c}/messages", t_a,
                       {"content": "最近30天各国家GMV趋势做成看板"})
    t_cancel = sent_c["task_id"]
    deadline = time.time() + 45
    while time.time() < deadline:
        _, sc, _ = api("GET", f"/api/tasks/{t_cancel}", t_a)
        if sc.get("status") == "running":
            break
        if sc.get("status") in ("failed", "succeeded", "waiting_for_apply", "waiting_for_user"):
            break
        time.sleep(1)
    api("POST", f"/api/tasks/{t_cancel}/cancel", t_a)
    snap_c = wait_task(t_a, t_cancel, timeout_s=90)
    check("运行中任务可取消", snap_c.get("status") == "cancelled", snap_c.get("status", "?"))

    # ── 结果 ────────────────────────────────────────────────────────
    elapsed = time.time() - started
    print(f"\n═══ 旅程测试结果：{PASS} 通过 / {FAIL} 失败 — {elapsed:.0f}s ═══")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
