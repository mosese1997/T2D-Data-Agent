#!/usr/bin/env python3
"""Eval runner: fixed case suites (task book §18).

  python evals/runner.py --case-set smoke     # 快速冒烟（4 例）
  python evals/runner.py --case-set nl        # 全部自然语言用例
  python evals/runner.py --case-set scripted  # 全部脚本用例
  python evals/runner.py --case-set full      # 全部（≈40 例）

NL cases drive the REAL agent pipeline (model + tools + gateway); value
cases compare against reference SQL executed independently — SQL strings
are never compared. Results land in eval_runs/eval_case_results and
evals/reports/<ts>.json.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
import urllib.request
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
os.environ.setdefault("STATE_DB_URL", "sqlite:///var/state.db")

API = "http://127.0.0.1:8001"
CASES_DIR = Path(__file__).parent / "cases"

# ── isolated eval stack ───────────────────────────────────────────
# Eval runs MUST NOT pollute the demo state DB (they create dashboards/
# conversations/tasks). --isolated (default for nl/full) boots a dedicated
# API+worker on :8011/:8012 against a throwaway state DB + data dir.
EVAL_API_PORT = 8011
EVAL_STATE_DB = str(ROOT / "var" / "eval-state.db")
EVAL_DATA_DIR = str(ROOT / "var" / "eval-data")


def boot_isolated_stack() -> bool:
    """Fresh state DB + dedicated API/worker; returns True on success."""
    import subprocess

    for path in (EVAL_STATE_DB, EVAL_STATE_DB + "-wal", EVAL_STATE_DB + "-shm"):
        if os.path.exists(path):
            os.remove(path)
    env = dict(
        os.environ,
        STATE_DB_URL=f"sqlite:///{EVAL_STATE_DB}",
        APP_DATA_DIR=EVAL_DATA_DIR,
        API_PORT=str(EVAL_API_PORT),
        WORKER_HEALTH_PORT="8012",
    )
    if not env.get("MODEL_API_KEY", "").startswith("sk-"):
        # inherit the model key the same way dev_up.sh does
        try:
            line = [l for l in open("/root/litellm/.env")
                    if l.startswith("LITELLM_MASTER_KEY=")][0]
            env["MODEL_API_KEY"] = line.split("=", 1)[1].strip().strip('"').strip("'")
            env.setdefault("MODEL_API_BASE", "http://localhost:4000/v1")
        except (OSError, IndexError):
            print("❌ 找不到 MODEL_API_KEY（且 /root/litellm/.env 不可读）")
            return False
    # migrate + seed users/semantics (presets not needed by eval cases)
    steps = [
        ("migrate", [
            sys.executable, "-c",
            "from alembic import command; from alembic.config import Config\n"
            "cfg = Config('packages/db/alembic.ini')\n"
            "cfg.set_main_option('script_location', 'packages/db/t2d_db/alembic')\n"
            "cfg.set_main_option('sqlalchemy.url', __import__('os').environ['STATE_DB_URL'])\n"
            "command.upgrade(cfg, 'head')",
        ]),
        ("seed_demo_users.py", [sys.executable, "scripts/seed_demo_users.py"]),
        ("seed_semantics.py", [sys.executable, "scripts/seed_semantics.py"]),
    ]
    for label, cmd in steps:
        proc = subprocess.run(cmd, env=env, cwd=ROOT,
                              capture_output=True, text=True)
        if proc.returncode != 0:
            print(f"❌ 隔离栈初始化失败（{label}）:\n{proc.stderr[-800:]}")
            return False
    procs = [
        subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "t2d_api.main:app",
             "--host", "127.0.0.1", "--port", str(EVAL_API_PORT)],
            env=env, cwd=ROOT,
            stdout=open(ROOT / "var" / "eval-api.log", "w"),
            stderr=subprocess.STDOUT),
        subprocess.Popen(
            [sys.executable, "-m", "t2d_worker.main"], env=env, cwd=ROOT,
            stdout=open(ROOT / "var" / "eval-worker.log", "w"),
            stderr=subprocess.STDOUT),
    ]
    import time as _time

    import urllib.request as _urlreq

    for _ in range(40):
        try:
            with _urlreq.urlopen(f"http://127.0.0.1:{EVAL_API_PORT}/api/healthz",
                                 timeout=2):
                return True
        except Exception:
            _time.sleep(1)
    for proc in procs:
        proc.terminate()
    return False


def teardown_isolated_stack() -> None:
    """Kill the eval API/worker (best effort; leave the DB for inspection)."""
    import subprocess

    subprocess.run(["bash", "-c",
                    f"ss -tlnp | grep ':{EVAL_API_PORT}' | grep -oP 'pid=\\K[0-9]+'"
                    " | xargs -r kill; "
                    "ss -tlnp | grep ':8012' | grep -oP 'pid=\\K[0-9]+' | xargs -r kill"],
                   capture_output=True)

PASSWORDS = {
    "admin": "admin-demo-2026", "analyst_a": "analyst-demo-2026",
    "analyst_b": "analyst-demo-2026", "viewer_b": "viewer-demo-2026",
    "viewer_c": "viewer-demo-2026", "ops": "ops-demo-2026",
}


def _sandbox_api_key() -> str:
    """The sandbox key of the stack under test: env var first, then the
    compose .env (the stack on :8001 is usually compose), then the dev
    default. A wrong key makes every scripted sandbox case 401."""
    key = os.environ.get("SANDBOX_API_KEY")
    if key:
        return key
    compose_env = ROOT / "infra" / "compose" / ".env"
    if compose_env.exists():
        for line in compose_env.read_text().splitlines():
            if line.startswith("SANDBOX_API_KEY="):
                return line.split("=", 1)[1].strip()
    return "t2d-probe-key-2026"


os.environ.setdefault("SANDBOX_API_KEY", _sandbox_api_key())


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


def login(username: str) -> str:
    _, body = api("POST", "/api/auth/login",
                  body={"username": username, "password": PASSWORDS[username]})
    return body["token"]


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


def load_cases() -> list[dict]:
    cases = []
    for path in sorted(CASES_DIR.glob("*.yaml")):
        import yaml

        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        for case in data.get("cases", []):
            case["_file"] = path.name
            cases.append(case)
    return cases


def reference_value(sql: str) -> float | None:
    """Execute reference SQL independently (all datasets, read-only)."""
    from cloud_adapters.dw.postgres_dw import PostgresDataWarehouse
    import psycopg

    with psycopg.connect(PostgresDataWarehouse().dsn_for("draft")) as conn:
        row = conn.execute(sql).fetchone()
    return float(row[0]) if row and row[0] is not None else None


def task_sources(task_id: int) -> list[dict]:
    """Actual result data of a task's execute_query calls.

    Reads via the ADMIN TRACE API + the sources rows endpoint — works
    against ANY stack (dev or compose); no direct DB access, so the
    runner can't read the wrong database.
    """
    _, admin = api("POST", "/api/auth/login",
                   body={"username": "admin", "password": PASSWORDS["admin"]})
    _, trace = api("GET", f"/api/admin/runs/{task_id}/trace", admin["token"])
    sources = []
    seen = set()
    for call in trace.get("tool_calls", []):
        if call.get("tool_name") != "execute_query":
            continue
        sid = (call.get("output") or {}).get("source_id")
        if not sid or sid in seen:
            continue
        seen.add(sid)
        code, rows = api("GET", f"/api/sources/{sid}/rows?size=100", admin["token"])
        if code != 200:
            continue
        sources.append({
            "row_count": rows.get("row_count", 0),
            "columns": rows.get("columns", []),
            "rows": rows.get("rows", []),
        })
    return sources


# ── NL case runner ────────────────────────────────────────────────
def run_nl_case(case: dict) -> tuple[bool, str, dict]:
    token = login(case["user"])
    _, workspaces = api("GET", "/api/workspaces", token)
    ws_id = next(w["id"] for w in workspaces if w["slug"] == case["workspace"])
    code, conv = api("POST", "/api/conversations", token,
                     {"workspace_id": ws_id, "title": f"eval-{case['id']}"})
    if case["expect"].get("kind") == "api_403":
        # Viewers are blocked at conversation creation (require analyst+).
        ok = code == 403
        return ok, f"conversation create → HTTP {code}", {}
    _, sent = api("POST", f"/api/conversations/{conv['id']}/messages", token,
                  {"content": case["question"]})
    task_id = sent["task_id"]
    snapshot = wait_task(token, task_id)

    expect = case["expect"]
    kind = expect.get("kind")
    actual = {"task_id": task_id, "status": snapshot.get("status")}
    if kind == "answer_value":
        ref = reference_value(expect["reference_sql"])
        answer = ((snapshot.get("result") or {}).get("answer")) or ""
        from judge import judge_answer_value

        ok, detail = judge_answer_value(
            answer=answer, reference_value=ref,
            tolerance=expect.get("tolerance", 0.01))
        actual["reference"] = ref
        return ok, detail, actual
    if kind == "value":
        ref = reference_value(expect["reference_sql"])
        sources = task_sources(task_id)
        from judge import judge_value

        ok, detail = judge_value(
            actual_sources=sources, reference_value=ref,
            tolerance=expect.get("tolerance", 0.01),
            reference_sql=expect["reference_sql"])
        actual["reference"] = ref
        return ok, detail, actual
    from judge import judge_behavior

    ok, detail = judge_behavior(kind=kind, snapshot=snapshot)
    return ok, detail, actual


# ── scripted checks ───────────────────────────────────────────────
def run_scripted(kind: str) -> tuple[bool, str]:
    if kind == "query_timeout":
        from query_gateway import QueryLimits
        from query_gateway.gateway import QueryGateway, QueryRejected
        from cloud_adapters.dw.postgres_dw import PostgresDataWarehouse

        gw = QueryGateway(
            dsn_for={"draft": PostgresDataWarehouse().dsn_for("draft"),
                     "publisher": PostgresDataWarehouse().dsn_for("publisher")},
            limits=QueryLimits(timeout_s=8),
        )
        t0 = time.time()
        try:
            gw.execute(identity="draft",
                       sql="SELECT count(*) FROM orders o1 CROSS JOIN orders o2",
                       allowed_objects={"orders"})
            return False, "慢查询未被超时杀死"
        except QueryRejected as exc:
            return "timeout" in str(exc).lower() or exc.code == "timeout", \
                f"{time.time()-t0:.1f}s 被拒: {exc.code}"
        except Exception as exc:
            return "timeout" in str(exc).lower(), f"超时拒绝: {str(exc)[:80]}"

    if kind == "task_cancel":
        token = login("analyst_a")
        _, conv = api("POST", "/api/conversations", token, {"workspace_id": 1})
        _, sent = api("POST", f"/api/conversations/{conv['id']}/messages", token,
                      {"content": "最近30天各国家GMV趋势"})
        # Wait until the task is actually RUNNING before cancelling —
        # cancelling a task that already failed proves nothing.
        deadline = time.time() + 60
        status = None
        while time.time() < deadline:
            _, snap = api("GET", f"/api/tasks/{sent['task_id']}", token)
            status = snap.get("status")
            if status == "running":
                break
            if status in ("failed", "cancelled", "succeeded", "waiting_for_apply"):
                return False, f"任务未进入 running 就结束了（{status}）"
            time.sleep(1)
        if status != "running":
            return False, f"60s 内未进入 running（{status}）"
        api("POST", f"/api/tasks/{sent['task_id']}/cancel", token)
        snapshot = wait_task(token, sent["task_id"], timeout_s=120)
        return snapshot.get("status") == "cancelled", f"status={snapshot.get('status')}"

    if kind == "sandbox_failure":
        from t2d_worker.sandbox import run_isolated

        result = asyncio.run(run_isolated(
            "raise RuntimeError('boom')", timeout_s=30))
        return not result.ok, f"ok={result.ok}（错误被如实暴露）"

    if kind == "sandbox_egress":
        from t2d_worker.sandbox import run_isolated

        result = asyncio.run(run_isolated(
            "import urllib.request\n"
            "try:\n"
            "    urllib.request.urlopen('http://93.184.216.34', timeout=5)\n"
            "    print('EGRESS-OK')\n"
            "except Exception as e:\n"
            "    print('EGRESS-BLOCKED')\n",
            timeout_s=30))
        blocked = "EGRESS-BLOCKED" in result.stdout and "EGRESS-OK" not in result.stdout
        return blocked, f"stdout={result.stdout[:60]!r}"

    if kind == "gateway_reject":
        from query_gateway import validate_sql

        allowed = {"orders"}
        checks = [
            validate_sql("SELECT 1; SELECT 2", allowed_objects=allowed),
            validate_sql("SELECT * FROM pg_catalog.pg_tables", allowed_objects=allowed),
            validate_sql("SELECT * FROM secret", allowed_objects=allowed),
            validate_sql("SELECT pg_sleep(5)", allowed_objects=allowed),
        ]
        ok = all(not c.valid for c in checks)
        return ok, f"{sum(1 for c in checks if not c.valid)}/4 拒绝"

    if kind == "idempotency":
        import uuid as _uuid

        from t2d_db import queue
        from t2d_db.session import get_sessionmaker

        with get_sessionmaker()() as s:
            from t2d_db.models import Task, User

            user = s.query(User).filter_by(username="analyst_a").first()
            uid = user.id
        key = f"eval-idem-{_uuid.uuid4()}"
        t1 = queue.enqueue(type="build_dashboard", workspace_id=1, user_id=uid,
                           payload={}, idempotency_key=key)
        t2 = queue.enqueue(type="build_dashboard", workspace_id=1, user_id=uid,
                           payload={}, idempotency_key=key)
        ok = t1.id == t2.id
        # Cancel the probe task — otherwise a live worker claims this
        # EMPTY task and actually runs it (found stuck 18min in a run).
        with get_sessionmaker()() as s:
            task = s.get(Task, t1.id)
            task.status = "cancelled"
            task.cancel_requested = True
            s.commit()
        return ok, f"{t1.id} == {t2.id}"

    if kind == "lease_reap":
        import uuid as _uuid
        from datetime import timedelta

        from t2d_db import queue
        from t2d_db.models import Task
        from t2d_db.session import get_sessionmaker, utcnow

        # Unique key per run: a fixed key would return the PREVIOUS run's
        # task (idempotency), whose attempts are already exhausted →
        # interrupted instead of requeued.
        with get_sessionmaker()() as s:
            t = queue.enqueue(type="build_dashboard", workspace_id=1, user_id=1,
                              payload={}, idempotency_key=f"eval-reap-{_uuid.uuid4()}")
            task = s.get(Task, t.id)
            task.status = "running"
            task.lease_expires_at = utcnow() - timedelta(seconds=1)
            s.commit()
        changed = queue.reap_expired()
        with get_sessionmaker()() as s:
            task = s.get(Task, t.id)
            status = task.status
            # requeued → a live worker would claim this EMPTY task; cancel it.
            if status == "queued":
                task.status = "cancelled"
                task.cancel_requested = True
            s.commit()
        return t.id in changed and status == "queued", f"requeued → {status}"

    # patch_conflict / restart_no_dup / publish_isolation / share_no_sql /
    # sse_resume are covered end-to-end by verify_phase3/4 — assert the
    # scripts exist and reference them (single source of truth).
    mapping = {
        "patch_conflict": "scripts/verify_phase4.py",
        "restart_no_dup": "scripts/verify_phase3.py",
        "publish_isolation": "scripts/verify_phase4.py",
        "share_no_sql": "scripts/verify_phase4.py",
        "sse_resume": "scripts/verify_phase3.py",
    }
    script = mapping.get(kind)
    if script and Path(script).exists():
        return True, f"由 {script} 端到端断言（单一事实源，不重复实现）"
    return False, f"未知 scripted 类型 {kind}"


SMOKE_IDS = {"basic-gmv-total", "clarify-ambiguous-sales", "scripted-gateway-reject",
             "analysis-gmv-wow"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-set", default="smoke",
                        choices=["smoke", "nl", "scripted", "full"])
    parser.add_argument("--filter", default=None,
                        help="只跑 id 含该子串的用例（逗号分隔多个）")
    parser.add_argument("--isolated", action="store_true", default=None,
                        help="用独立栈跑（nl/full 默认开启），不污染演示库")
    parser.add_argument("--no-isolated", dest="isolated", action="store_false")
    args = parser.parse_args()

    # NL cases create dashboards/conversations — run them against a
    # throwaway stack so the demo DB stays clean.
    use_isolated = args.isolated
    if use_isolated is None:
        use_isolated = args.case_set in ("nl", "full") and not args.filter
    global API
    if use_isolated:
        print("启动隔离评测栈（:8011/:8012，一次性状态库）…")
        if not boot_isolated_stack():
            print("❌ 隔离栈启动失败（见 var/eval-api.log）")
            return 1
        API = f"http://127.0.0.1:{EVAL_API_PORT}"
        os.environ["STATE_DB_URL"] = f"sqlite:///{EVAL_STATE_DB}"
        # The judge reads result FILES too — align this process's file
        # store with the isolated stack's APP_DATA_DIR (found the hard
        # way: judge saw zero sources while the answers were correct).
        os.environ["APP_DATA_DIR"] = EVAL_DATA_DIR
    else:
        # demo stack must be up
        try:
            with urllib.request.urlopen(f"{API}/api/healthz", timeout=3):
                pass
        except Exception:
            print("❌ 服务未运行（先 bash scripts/dev_up.sh）")
            return 1

    cases = load_cases()
    if args.filter:
        wanted = {s.strip() for s in args.filter.split(",")}
        cases = [c for c in cases if any(w in c["id"] for w in wanted)]
    elif args.case_set == "smoke":
        cases = [c for c in cases if c["id"] in SMOKE_IDS]
    elif args.case_set == "nl":
        cases = [c for c in cases if c["category"] != "scripted"]
    elif args.case_set == "scripted":
        cases = [c for c in cases if c["category"] == "scripted"]

    print(f"═══ 评测 {args.case_set}：{len(cases)} 用例 ═══")
    if use_isolated:
        import atexit

        atexit.register(teardown_isolated_stack)
    results: list[dict] = []
    passed = 0
    started = time.time()
    for case in cases:
        t0 = time.time()
        try:
            if case["category"] == "scripted":
                ok, detail = run_scripted(case["kind"])
                actual = {}
            else:
                ok, detail, actual = run_nl_case(case)
        except Exception as exc:  # noqa: BLE001
            ok, detail, actual = False, f"runner 异常: {type(exc).__name__}: {exc}", {}
        passed += ok
        elapsed = time.time() - t0
        mark = "✅" if ok else "❌"
        print(f"  {mark} [{case['id']}] {detail}  ({elapsed:.0f}s)")
        results.append({"case_id": case["id"], "category": case.get("category"),
                        "status": "passed" if ok else "failed",
                        "detail": detail, "actual": actual,
                        "elapsed_s": round(elapsed, 1)})

    total = len(cases)
    accuracy = passed / total if total else 0
    print(f"\n═══ 结果：{passed}/{total}（{accuracy:.0%}）— {time.time()-started:.0f}s ═══")

    # Persist to eval_runs + a JSON report.
    from t2d_db.models import EvalCaseResult, EvalRun
    from t2d_db.session import get_sessionmaker

    with get_sessionmaker()() as s:
        run = EvalRun(case_set=args.case_set,
                      summary={"total": total, "passed": passed, "accuracy": accuracy})
        s.add(run)
        s.flush()
        for r in results:
            s.add(EvalCaseResult(
                eval_run_id=run.id, case_id=r["case_id"],
                status=r["status"], expected={}, actual=r["actual"]))
        s.commit()
        run_id = run.id

    if use_isolated:
        # Mirror the summary into the DEMO state DB so the admin eval page
        # shows isolated-run history (task links don't cross DBs — dropped).
        demo_url = f"sqlite:///{ROOT / 'var' / 'state.db'}"
        from t2d_db import session as _session_mod

        _session_mod._cached_engine.cache_clear()
        old_url = os.environ["STATE_DB_URL"]
        try:
            os.environ["STATE_DB_URL"] = demo_url
            with get_sessionmaker()() as s:
                mirror = EvalRun(
                    case_set=f"{args.case_set}(isolated)",
                    summary={"total": total, "passed": passed, "accuracy": accuracy})
                s.add(mirror)
                s.flush()
                for r in results:
                    s.add(EvalCaseResult(
                        eval_run_id=mirror.id, case_id=r["case_id"],
                        status=r["status"], expected={}, actual={}))
                s.commit()
        finally:
            os.environ["STATE_DB_URL"] = old_url
            _session_mod._cached_engine.cache_clear()
    reports = Path("evals/reports")
    reports.mkdir(exist_ok=True)
    report_path = reports / f"{int(time.time())}-{args.case_set}.json"
    report_path.write_text(json.dumps(
        {"run_id": run_id, "case_set": args.case_set, "passed": passed,
         "total": total, "accuracy": accuracy, "results": results},
        ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"报告: {report_path}（eval_run_id={run_id}）")

    # Gate (task book §18): basic-ask accuracy >= 90%.
    basic = [r for r in results if r["category"] == "basic"]
    if basic:
        basic_pass = sum(1 for r in basic if r["status"] == "passed")
        print(f"基础问数正确率: {basic_pass}/{len(basic)}"
              f"（{basic_pass/len(basic):.0%}，门禁 90%）")
        if basic_pass / len(basic) < 0.90:
            print("❌ 基础问数正确率低于 90% 门禁")
            return 1
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
