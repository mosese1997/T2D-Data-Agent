#!/usr/bin/env python3
"""Sandbox lifecycle acceptance check — runs under the probe venv (opensandbox SDK 1.2.0).

Assumes opensandbox-server is reachable at 127.0.0.1:8003. Executes the
t2d-mandated profile: resource 1 vCPU / 1 GiB, deny-all egress (opt-in —
never rely on defaults), per-command timeout, destroy at the end, zero
container residue. Prints check lines and a final JSON verdict.

Usage: probe-venv/bin/python scripts/check_sandbox_lifecycle.py
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from datetime import timedelta

from opensandbox import Sandbox
from opensandbox.config import ConnectionConfig
from opensandbox.models.execd import RunCommandOpts
from opensandbox.models.filesystem import WriteEntry
from opensandbox.models.sandboxes import NetworkPolicy

API_KEY = "t2d-probe-key-2026"
DOMAIN = "127.0.0.1:8003"
IMAGE = "python:3.12-slim"
RESOURCE = {"cpu": "1", "memory": "1Gi"}  # task book §11 defaults

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    RESULTS.append((name, bool(ok), detail))
    print(f"  {'✅' if ok else '❌'} {name} {detail}")
    return bool(ok)


async def run_cmd(sb, cmd: str, timeout: int | None = None):
    opts = RunCommandOpts(timeout=timeout) if timeout else None
    ex = await sb.commands.run(cmd, opts=opts)
    stdout = "".join(r.text or "" for r in ex.logs.stdout)
    return {"exit_code": ex.exit_code, "stdout": stdout.strip()}


async def main() -> int:
    conn = ConnectionConfig(api_key=API_KEY, domain=DOMAIN)
    sandbox = await Sandbox.create(
        IMAGE,
        resource=RESOURCE,
        timeout=timedelta(minutes=10),  # TTL 兜底（server 最小 60s）
        network_policy=NetworkPolicy(default_action="deny"),  # 必须显式：默认放通！
        connection_config=conn,
    )
    all_ok = True
    try:
        # 1. compute
        r = await run_cmd(sandbox, 'python3 -c "import json;print(json.dumps({\'answer\': 6*7}))"')
        all_ok &= check("run computes 6*7",
                        r["exit_code"] == 0 and '"answer":42' in r["stdout"].replace(" ", ""),
                        r["stdout"][:60])

        # 2. file write/read roundtrip
        await sandbox.files.write_files([WriteEntry(
            path="/tmp/t2d_check.txt", data="t2d-sandbox-check", mode=644)])
        content = await sandbox.files.read_file("/tmp/t2d_check.txt")
        all_ok &= check("file roundtrip", "t2d-sandbox-check" in content)

        # 3. egress denied (deny-all policy must actually block)
        r = await run_cmd(
            sandbox,
            "python3 -c \"import urllib.request;urllib.request.urlopen('http://93.184.216.34', timeout=5)\"",
            timeout=20,
        )
        all_ok &= check("egress denied", r["exit_code"] != 0, f"exit={r['exit_code']}")

        # 4. per-command timeout kills long sleeps but sandbox survives
        r = await run_cmd(sandbox, 'python3 -c "import time;time.sleep(60)"', timeout=5)
        all_ok &= check("command timeout enforced", r["exit_code"] != 0, f"exit={r['exit_code']}")
        r = await run_cmd(sandbox, "echo alive")
        all_ok &= check("sandbox survives timeout", r["exit_code"] == 0 and r["stdout"] == "alive")
    finally:
        await sandbox.destroy()

    # 5. zero residue
    residue = subprocess.run(
        ["docker", "ps", "-aq", "--filter", "label=opensandbox.io/id"],
        capture_output=True, text=True,
    ).stdout.strip()
    all_ok &= check("no container residue", residue == "", residue[:80])

    print(json.dumps({"ok": all_ok}, ensure_ascii=False))
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
