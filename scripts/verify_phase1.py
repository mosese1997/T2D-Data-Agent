#!/usr/bin/env python3
"""Phase 1 acceptance: framework verification & contracts (assertion-style).

Checks (task book §17 阶段1 验收):
  1. toolloop: a REAL model call triggers a controlled tool and returns
     the tool's computed value.
  2. SwarmFlow probe verdict recorded (GO) — full probe in
     docs/phase-notes/swarmflow-probe.md.
  3. OpenSandbox: lifecycle + resource limits + deny-all egress + cleanup
     (starts its own server, tears it down).
  4. Alembic migration on a fresh SQLite (and MySQL when reachable).
  5. Canvas JSON roundtrip + validation.
  6. Queue primitives + semantic retrieval smoke.

Exit code 0 only when every REQUIRED check passes. Model/sandbox checks are
required — they are the phase's whole point; missing credentials fail loudly
instead of silently skipping.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

RESULTS: list[tuple[str, bool, str, bool]] = []


def check(name: str, ok: bool, detail: str = "", *, required: bool = True) -> bool:
    RESULTS.append((name, bool(ok), detail, required))
    mark = "✅" if ok else ("❌" if required else "⚠️ ")
    print(f"  {mark} {name} {detail}")
    return bool(ok)


def load_model_env() -> bool:
    """MODEL_API_* from env, falling back to the local litellm .env."""
    if os.environ.get("MODEL_API_KEY", "").startswith("sk-"):
        return True
    litellm_env = "/root/litellm/.env"
    if os.path.exists(litellm_env):
        with open(litellm_env) as f:
            for line in f:
                if line.startswith("LITELLM_MASTER_KEY="):
                    key = line.split("=", 1)[1].strip().strip("'\"")
                    os.environ["MODEL_API_KEY"] = key
                    os.environ.setdefault("MODEL_API_BASE", "http://localhost:4000/v1")
                    return True
    return False


def check_toolloop() -> bool:
    """Real model call → controlled tool → computed value in the answer."""
    print("\n[1] toolloop：真实模型调用触发受控工具")
    if not load_model_env():
        return check("model credentials", False, "MODEL_API_KEY 不可用（litellm .env 缺失）")
    from agent_adapter import AgentSession, Budget, Tool, ToolContext
    from agent_adapter.toolloop import ToolLoopRuntime
    from agent_adapter.toolloop.runtime import attach_context

    calls: list[dict] = []

    async def calculate(ctx: ToolContext, args: dict) -> dict:
        calls.append(args)
        return {"value": args["a"] * args["b"], "_summary": f"计算 {args['a']}×{args['b']}"}

    tool = Tool(
        name="calculate",
        description="计算两个整数的乘积并返回",
        parameters={
            "type": "object",
            "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
            "required": ["a", "b"],
        },
        handler=calculate,
    )
    events: list[str] = []

    async def run():
        runtime = ToolLoopRuntime()
        session = attach_context(
            AgentSession(
                agent_name="main",
                system_prompt="你是计算助手。必须调用 calculate 工具获取结果，然后用一句话回答。",
                messages=[{"role": "user", "content": "6 乘 7 等于多少？"}],
                tools=[tool],
                event_sink=lambda e: events.append(e.type),
                budget=Budget(max_steps=8, max_tool_calls=4),
            ),
            ToolContext(task_id=0, user_id=1, workspace_id=1, role="analyst", datasets=[]),
        )
        return await runtime.run(session, model="t2d/deepseek-v4.1-flash-1017")

    result = asyncio.run(run())
    ok = check("tool handler executed", len(calls) == 1, f"calls={calls}")
    ok &= check("tool computed 42", calls and calls[0].get("a", 0) * calls[0].get("b", 0) == 42)
    ok &= check("final answer contains 42", result.status == "succeeded" and "42" in (result.content or ""))
    ok &= check("events emitted", "tool_call" in events and "tool_result" in events, str(events))
    return ok


def check_probe_reports() -> bool:
    print("\n[2] 框架探测结论已固化")
    swarm = os.path.join(ROOT, "docs/phase-notes/swarmflow-probe.md")
    sand = os.path.join(ROOT, "docs/phase-notes/opensandbox-probe.md")
    boundaries = os.path.join(ROOT, "packages/agent_adapter/agent_adapter/boundaries.md")
    ok = check("swarmflow probe report", os.path.exists(swarm))
    ok &= check("opensandbox probe report", os.path.exists(sand))
    if os.path.exists(boundaries):
        text = open(boundaries, encoding="utf-8").read()
        ok &= check("boundaries.md has swarmflow GO", "GO" in text)
        ok &= check("boundaries.md has sandbox section", "OpenSandbox 1.2.0" in text)
    else:
        ok &= check("boundaries.md exists", False)
    return ok


def check_sandbox() -> bool:
    print("\n[3] OpenSandbox：生命周期/资源限制/禁网/清理")
    venv_python = os.path.join(ROOT, "var", "probe-venv", "bin", "python")
    server_bin = os.path.join(ROOT, "var", "probe-venv", "bin", "opensandbox-server")
    config = os.path.join(ROOT, "var", "probe-scripts", "opensandbox-config.toml")
    if not (os.path.exists(venv_python) and os.path.exists(server_bin)):
        return check("probe venv present", False, f"{venv_python} 缺失")
    import urllib.request

    def server_up() -> bool:
        try:
            with urllib.request.urlopen("http://127.0.0.1:8003/health", timeout=2) as r:
                return r.status == 200
        except Exception:
            return False

    started_proc = None
    # Dev-host hygiene: a stray server from an earlier aborted run holds
    # :8003 and fights the fresh instance over docker cleanup (observed:
    # bind failure + in-flight sandbox creation killed by the loser's
    # startup sweep). Kill strays, then always start our own.
    subprocess.run(["pkill", "-f", "opensandbox-server"], capture_output=True)
    time.sleep(1)
    started_proc = subprocess.Popen(
        [server_bin, "--config", config],
        cwd=os.path.join(ROOT, "var", "probe-scripts"),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    for _ in range(30):
        if server_up():
            break
        time.sleep(1)
    if not server_up():
        started_proc.terminate()
        return check("opensandbox-server started", False, "30s 内未就绪")
    check("opensandbox-server reachable", True, "(自启)")

    try:
        proc_result = subprocess.run(
            [venv_python, os.path.join(ROOT, "scripts", "check_sandbox_lifecycle.py")],
            capture_output=True, text=True, timeout=300,
        )
        ok = check("sandbox lifecycle checks", proc_result.returncode == 0)
        if proc_result.returncode != 0:
            print("    " + proc_result.stdout[-800:].replace("\n", "\n    "))
            print("    stderr: " + proc_result.stderr[-400:])
        return ok
    finally:
        if started_proc is not None:
            started_proc.terminate()
            try:
                started_proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                started_proc.kill()


def check_migration() -> bool:
    print("\n[4] Alembic 迁移（SQLite 必测；MySQL 可达则加测）")
    from alembic import command
    from alembic.config import Config

    ini = os.path.join(ROOT, "packages", "db", "alembic.ini")
    with tempfile.TemporaryDirectory() as tmp:
        # env.py reads STATE_DB_URL/MYSQL_URL and overrides the ini URL —
        # point the env at the temp file too.
        os.environ["STATE_DB_URL"] = f"sqlite:///{tmp}/state.db"
        os.environ.pop("MYSQL_URL", None)
        cfg = Config(ini)
        cfg.set_main_option("script_location", os.path.join(ROOT, "packages", "db", "t2d_db", "alembic"))
        cfg.set_main_option("sqlalchemy.url", os.environ["STATE_DB_URL"])
        try:
            command.upgrade(cfg, "head")
            ok = check("sqlite upgrade head", True)
        except Exception as exc:
            ok = check("sqlite upgrade head", False, str(exc)[:120])
            return ok
        import sqlite3

        tables = sqlite3.connect(f"{tmp}/state.db").execute(
            "SELECT count(*) FROM sqlite_master WHERE type='table'").fetchone()[0]
        ok &= check("sqlite table count", tables == 27, f"{tables} tables")

    # MySQL: only when a MYSQL_URL is provided (e.g. smoke container).
    mysql_url = os.environ.get("MYSQL_URL", "")
    if mysql_url:
        try:
            cfg = Config(ini)
            cfg.set_main_option("script_location", os.path.join(ROOT, "packages", "db", "t2d_db", "alembic"))
            cfg.set_main_option("sqlalchemy.url", mysql_url)
            command.upgrade(cfg, "head")
            ok &= check("mysql upgrade head", True, "(MYSQL_URL)")
        except Exception as exc:
            ok &= check("mysql upgrade head", False, str(exc)[:120])
    else:
        check("mysql upgrade head", False, "MYSQL_URL 未设置（跳过，非阻塞）", required=False)
    return ok


def check_contracts() -> bool:
    print("\n[5] 画布契约 roundtrip")
    from dashboard_schema import Canvas, Patch, apply_patch, summarize_changes, validate_canvas

    canvas = Canvas(title="t", filters={"allowed": ["country"]})
    patch = Patch.model_validate({
        "base_revision": 1,
        "operations": [{"op": "add_component", "value": {
            "id": "c1", "type": "metric_card", "source_id": "s1", "field": "gmv"}}],
    })
    after = apply_patch(canvas, patch)
    ok = check("canvas json roundtrip",
               Canvas.model_validate_json(after.model_dump_json()) == after)
    errors = validate_canvas(
        after, sources={"s1": {"workspace_id": 1, "col_schema": [{"name": "gmv"}]}},
        workspace_id=1,
    )
    ok &= check("canvas validation clean", errors == [])
    summary = summarize_changes(canvas, after, patch)
    ok &= check("diff summary produced", bool(summary))
    return ok


def check_queue_and_semantic() -> bool:
    print("\n[6] 队列与语义检索冒烟")
    os.environ["STATE_DB_URL"] = "sqlite:///var/verify-phase1.db"
    os.environ.pop("MYSQL_URL", None)
    from t2d_db import session as session_mod

    session_mod._cached_engine.cache_clear()
    from alembic import command
    from alembic.config import Config

    cfg = Config(os.path.join(ROOT, "packages", "db", "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(ROOT, "packages", "db", "t2d_db", "alembic"))
    cfg.set_main_option("sqlalchemy.url", os.environ["STATE_DB_URL"])
    command.upgrade(cfg, "head")

    from t2d_db import queue
    from t2d_db.models import User, Workspace
    from t2d_db.session import session_scope

    with session_scope() as s:
        u = User(username="verify_p1", display_name="V", password_hash="x")
        s.add(u); s.flush()
        w = Workspace(slug="verify-ws", name="V", type="personal", created_by=u.id)
        s.add(w); s.flush()
        uid, wid = u.id, w.id
    t1 = queue.enqueue(type="build_dashboard", workspace_id=wid, user_id=uid,
                       payload={}, idempotency_key="vp1")
    t2 = queue.enqueue(type="build_dashboard", workspace_id=wid, user_id=uid,
                       payload={}, idempotency_key="vp1")
    ok = check("queue idempotency", t1.id == t2.id)
    claim = queue.claim_next("verify-worker")
    ok &= check("queue claim", claim.claimed)

    from semantic import SemanticRetriever, load_semantics

    reg = load_semantics(os.path.join(ROOT, "config", "semantics"))
    hits = SemanticRetriever(reg).search("上周各国家GMV趋势", top_k=3)
    keys = [h.key for h in hits]
    ok &= check("retrieval hits gmv", "gmv" in keys or "GMV" in keys, str(keys))

    for f in ("var/verify-phase1.db", "var/verify-phase1.db-wal", "var/verify-phase1.db-shm"):
        if os.path.exists(f):
            os.remove(f)
    return ok


def main() -> int:
    print("═══ 阶段 1 验收 verify_phase1 ═══")
    all_ok = True
    all_ok &= check_toolloop()
    all_ok &= check_probe_reports()
    all_ok &= check_sandbox()
    all_ok &= check_migration()
    all_ok &= check_contracts()
    all_ok &= check_queue_and_semantic()

    print("\n═══ 结果 ═══")
    required_failed = [name for name, ok, _, required in RESULTS if not ok and required]
    for name, ok, detail, required in RESULTS:
        print(f"  {'✅' if ok else ('❌' if required else '⚠️ ')} {name}")
    passed = sum(1 for r in RESULTS if r[1])
    print(f"\n通过 {passed}/{len(RESULTS)}")
    if required_failed:
        print(f"❌ 阶段 1 验收未通过：{required_failed}")
        return 1
    print("✅ 阶段 1 验收全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
