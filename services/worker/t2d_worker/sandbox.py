"""Sandbox adapter: run_isolated() — the ONLY path to code execution.

Profile (task book §15 + probe findings, see boundaries.md):
- resource 1 vCPU / 1 GiB (enforced, probe-verified OOM behavior)
- network: deny-all — EXPLICIT on every call (OpenSandbox default is OPEN!)
- per-command timeout (default 120s, task book §11); TTL 10 min backstop
- no credentials ever injected; inputs are authorized result sets only
- destroy in finally; zero container residue expected (asserted by caller)
- result contract: script writes /tmp/t2d_result.json, we read it back
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from datetime import timedelta

from opensandbox import Sandbox
from opensandbox.config import ConnectionConfig
from opensandbox.models.execd import RunCommandOpts
from opensandbox.models.filesystem import WriteEntry
from opensandbox.models.sandboxes import NetworkPolicy

SERVER = os.environ.get("SANDBOX_SERVER", "http://127.0.0.1:8003")
API_KEY = os.environ.get("SANDBOX_API_KEY", "t2d-probe-key-2026")
IMAGE = os.environ.get("SANDBOX_IMAGE", "python:3.12-slim")
TIMEOUT_S = int(os.environ.get("SANDBOX_TIMEOUT_S", "120"))
RESOURCE = {"cpu": "1", "memory": "1Gi"}


class SandboxError(Exception):
    pass


@dataclass
class SandboxResult:
    ok: bool
    result: dict | None      # parsed /tmp/t2d_result.json
    stdout: str
    stderr: str
    duration_ms: int


def _conn() -> ConnectionConfig:
    host_port = SERVER.removeprefix("http://").removeprefix("https://")
    return ConnectionConfig(api_key=API_KEY, domain=host_port)


async def run_isolated(
    code: str,
    *,
    input_files: dict[str, str] | None = None,
    timeout_s: int | None = None,
) -> SandboxResult:
    """Write code + inputs into a fresh sandbox, run, read the result JSON.

    The script contract: write your result dict to /tmp/t2d_result.json.
    """
    timeout = timeout_s or TIMEOUT_S
    files = {"/tmp/t2d_task.py": code}
    for name, content in (input_files or {}).items():
        files[f"/tmp/t2d_inputs/{name}"] = content

    import time

    started = time.monotonic()
    sandbox = await Sandbox.create(
        IMAGE,
        resource=RESOURCE,
        timeout=timedelta(minutes=10),  # TTL backstop (server min 60s)
        network_policy=NetworkPolicy(default_action="deny"),  # opt-in deny!
        connection_config=_conn(),
    )
    try:
        await sandbox.files.write_files([
            WriteEntry(path=path, data=content, mode=0o644)
            for path, content in files.items()
        ])
        execution = await sandbox.commands.run(
            f"python3 /tmp/t2d_task.py",
            opts=RunCommandOpts(timeout=timeout),
        )
        stdout = "".join(r.text or "" for r in execution.logs.stdout)
        stderr = "".join(r.text or "" for r in execution.logs.stderr)
        exit_code = execution.exit_code
        result: dict | None = None
        if exit_code == 0:
            try:
                raw = await sandbox.files.read_file("/tmp/t2d_result.json")
                result = json.loads(raw)
            except Exception:
                result = None
        duration_ms = int((time.monotonic() - started) * 1000)
        return SandboxResult(
            ok=exit_code == 0 and result is not None,
            result=result, stdout=stdout[-2000:], stderr=stderr[-2000:],
            duration_ms=duration_ms,
        )
    finally:
        await sandbox.destroy()


def contribution_template() -> str:
    """Deterministic contribution-decomposition script (task book §8:
    贡献分析不得冒充因果分析 — the report says 'contribution', not 'cause')."""
    return '''
import json


def load(path):
    with open(path) as f:
        data = json.load(f)
    rows = data["rows"]
    columns = [c["name"] if isinstance(c, dict) else c for c in data.get("columns", [])]
    if rows and isinstance(rows[0], list):
        # positional rows (from COPY/psycopg tuples) -> dicts via columns
        rows = [dict(zip(columns, r)) for r in rows]
    return rows, data["key_field"], data["value_field"]


cur_rows, key, value = load("/tmp/t2d_inputs/current.json")
prev_rows, _, _ = load("/tmp/t2d_inputs/previous.json")
if not key or not value:
    raise SystemExit("缺少 key_field/value_field — 从 Source 的 columns 中选择维度列与数值列")

cur = {str(r[key]): float(r[value] or 0) for r in cur_rows}
prev = {str(r[key]): float(r[value] or 0) for r in prev_rows}

all_keys = sorted(set(cur) | set(prev), key=lambda k: abs(cur.get(k, 0) - prev.get(k, 0)), reverse=True)
total_delta = sum(cur.values()) - sum(prev.values())
denominator = sum(abs(cur.get(k, 0) - prev.get(k, 0)) for k in all_keys) or 1.0

contributions = []
for k in all_keys:
    delta = cur.get(k, 0) - prev.get(k, 0)
    contributions.append({
        "dimension": k,
        "current": round(cur.get(k, 0), 2),
        "previous": round(prev.get(k, 0), 2),
        "delta": round(delta, 2),
        "delta_pct": round(delta / prev[k] * 100, 2) if prev.get(k) else None,
        "contribution_pct": round(abs(delta) / denominator * 100, 2),
    })

result = {
    "analysis_type": "contribution",
    "total_current": round(sum(cur.values()), 2),
    "total_previous": round(sum(prev.values()), 2),
    "total_delta": round(total_delta, 2),
    "total_delta_pct": round(total_delta / sum(prev.values()) * 100, 2) if sum(prev.values()) else None,
    "contributions": contributions[:10],
    "note": "贡献分解只说明各维度对变化的贡献占比，不构成因果解释",
}
with open("/tmp/t2d_result.json", "w") as f:
    json.dump(result, f, ensure_ascii=False)
print(json.dumps(result, ensure_ascii=False))
'''
