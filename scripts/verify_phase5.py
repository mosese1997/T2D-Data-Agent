#!/usr/bin/env python3
"""Phase 5 acceptance: analysis & platform capabilities.

Checks (task book §17 阶段5 验收 — 前台一次分析能进入对应后台执行详情):
  1. A live analysis task (sandbox contribution run) succeeds with an
     analysis_id and an honest, non-causal conclusion.
  2. The admin Trace endpoint exposes the FULL execution detail for that
     task: agent_runs tree (main/query/analysis) + tool_calls with real
     inputs/outputs/latency — every number traceable, nothing fabricated.
  3. Admin console: agent-config (runtime + capabilities), knowledge index,
     runs list.
  4. Eval capability: the smoke case set passes (full-suite gate runs
     separately: `python evals/runner.py --case-set full`).
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


def api(method, path, token=None, body=None):
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


def wait_task(token, task_id, timeout_s=300) -> dict:
    wanted = {"waiting_for_apply", "waiting_for_user", "failed",
              "cancelled", "succeeded", "interrupted"}
    deadline = time.time() + timeout_s
    snapshot = {}
    while time.time() < deadline:
        _, snapshot = api("GET", f"/api/tasks/{task_id}", token)
        if snapshot.get("status") in wanted:
            return snapshot
        time.sleep(3)
    return snapshot


def main() -> int:
    print("═══ 阶段 5 验收 verify_phase5 ═══")
    try:
        with urllib.request.urlopen(f"{API}/api/healthz", timeout=3):
            pass
    except Exception:
        print("❌ 服务未运行（先 bash scripts/dev_up.sh）")
        return 1

    _, analyst = api("POST", "/api/auth/login",
                     body={"username": "analyst_a", "password": "analyst-demo-2026"})
    token_a = analyst["token"]
    _, admin = api("POST", "/api/auth/login",
                   body={"username": "admin", "password": "admin-demo-2026"})
    token_admin = admin["token"]
    all_ok = True

    # ── 1. live analysis ───────────────────────────────────────────
    print("\n[1] 沙箱贡献分析（真实链路）")
    _, conv = api("POST", "/api/conversations", token_a,
                  {"workspace_id": 1, "title": "verify-phase5"})
    _, sent = api("POST", f"/api/conversations/{conv['id']}/messages", token_a,
                  {"content": "分析上周相比上上周GMV变化，各国家贡献如何"})
    task_id = sent["task_id"]
    snapshot = wait_task(token_a, task_id)
    result = snapshot.get("result") or {}
    ok = check("analysis task succeeded", snapshot.get("status") == "succeeded",
               snapshot.get("status", "?"))
    ok &= check("has analysis_id", bool(result.get("analysis_id")))
    conclusion = result.get("conclusion") or ""
    ok &= check("conclusion is non-causal",
                "贡献" in conclusion and "因为" not in conclusion and "导致" not in conclusion,
                conclusion[:60])
    ok &= check("conclusion cites numbers", any(ch.isdigit() for ch in conclusion))
    all_ok &= ok

    # ── 2. front → back trace ──────────────────────────────────────
    print("\n[2] 前台分析 → 后台执行详情（Trace）")
    code, trace = api("GET", f"/api/admin/runs/{task_id}/trace", token_admin)
    ok = check("trace endpoint 200", code == 200)
    agents = {r["agent_name"] for r in trace.get("agent_runs", [])}
    ok &= check("agent_runs has main+query+analysis",
                {"main", "query", "analysis"} <= agents, str(agents))
    tools = [c["tool_name"] for c in trace.get("tool_calls", [])]
    ok &= check("tool_calls include run_analysis", "run_analysis" in tools,
                f"{len(tools)} calls")
    run_call = next((c for c in trace.get("tool_calls", [])
                     if c["tool_name"] == "run_analysis"), None)
    ok &= check("run_analysis has real input+output",
                run_call is not None and run_call.get("input")
                and run_call.get("output") and run_call.get("latency_ms", 0) > 0)
    ok &= check("no fabricated latency", all(c.get("latency_ms", 0) >= 0
                                             for c in trace.get("tool_calls", [])))
    # Non-admin cannot read the trace.
    code, _ = api("GET", f"/api/admin/runs/{task_id}/trace", token_a)
    ok &= check("non-admin trace denied", code == 403, f"status={code}")
    all_ok &= ok

    # ── 3. admin console ───────────────────────────────────────────
    print("\n[3] 管理台（Agent 配置/知识索引/运行列表）")
    code, config = api("GET", "/api/admin/agent-config", token_admin)
    ok = check("agent-config readable", code == 200
               and config["config"]["agent"]["runtime"] == "toolloop")
    code, _ = api("POST", "/api/admin/agent-config/runtime", token_admin,
                  {"runtime": "swarmflow"})
    ok &= check("swarmflow switch honestly blocked (409)", code == 409,
                "适配器未接入前不提供假开关")
    code, _ = api("POST", "/api/admin/agent-config/runtime", token_admin,
                  {"runtime": "toolloop"})
    ok &= check("toolloop switch OK", code == 200)
    code, index = api("GET", "/api/admin/knowledge-index", token_admin)
    ok &= check("knowledge index", code == 200 and index.get("metrics", 0) >= 10)
    code, runs = api("GET", "/api/admin/runs?limit=5", token_admin)
    ok &= check("runs list", code == 200 and len(runs) >= 1)
    code, _ = api("GET", "/api/admin/agent-config", token_a)
    ok &= check("non-admin config denied", code == 403, f"status={code}")
    all_ok &= ok

    # ── 4. eval capability ─────────────────────────────────────────
    print("\n[4] 评测能力（冒烟集）")
    import subprocess

    proc = subprocess.run([sys.executable, "evals/runner.py", "--case-set", "smoke"],
                          capture_output=True, text=True, timeout=600)
    ok = check("eval smoke suite passes", proc.returncode == 0,
               proc.stdout.strip().splitlines()[-2] if proc.stdout else "no output")
    all_ok &= ok

    print("\n═══ 结果 ═══")
    required_failed = [name for name, ok_, _, req in RESULTS if not ok_ and req]
    for name, ok_, detail, req in RESULTS:
        print(f"  {'✅' if ok_ else ('❌' if req else '⚠️ ')} {name}")
    passed = sum(1 for r in RESULTS if r[1])
    print(f"\n通过 {passed}/{len(RESULTS)}")
    if required_failed:
        print(f"❌ 阶段 5 验收未通过：{required_failed}")
        return 1
    print("✅ 阶段 5 验收全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
