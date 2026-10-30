#!/usr/bin/env python3
"""SwarmFlow adapter integration test — run under var/probe-venv.

Validates SwarmFlowRuntime (the AgentRuntime implementation over the
JiuwenSwarm engine) against the REAL engine + REAL model:
  1. tool injection: our Tool (JSON Schema) is callable by the engine
  2. tool result captured into AgentResult.tool_results
  3. final answer flows back; structured schema path returns a dict
  4. events are mapped to AgentEvent (run_started/message/...)

Usage:
  var/probe-venv/bin/pip install -e packages/agent_adapter -q   # once
  var/probe-venv/bin/python scripts/test_swarmflow_adapter.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Model env: litellm proxy (key from /root/litellm/.env, never printed).
os.environ.setdefault("MODEL_API_BASE", "http://localhost:4000/v1")
if not os.environ.get("MODEL_API_KEY", "").startswith("sk-"):
    line = [l for l in open("/root/litellm/.env")
            if l.startswith("LITELLM_MASTER_KEY=")][0]
    os.environ["MODEL_API_KEY"] = line.split("=", 1)[1].strip().strip('"').strip("'")

from agent_adapter import AgentSession, Budget, Tool, ToolContext  # noqa: E402
from agent_adapter.swarmflow.runtime import SwarmFlowRuntime, available  # noqa: E402


def check(name: str, ok: bool, detail: str = "") -> bool:
    print(f"  {'✅' if ok else '❌'} {name} {detail}")
    return ok


async def main() -> int:
    if not available():
        print("❌ 当前环境没有 openjiuwen（用 var/probe-venv 运行本脚本）")
        return 1
    print("═══ SwarmFlow 适配器集成测试 ═══")
    all_ok = True

    calls: list[dict] = []

    async def calculate(ctx: ToolContext, args: dict) -> dict:
        calls.append(args)
        return {"value": args["a"] * args["b"],
                "_summary": f"计算 {args['a']}×{args['b']}"}

    tool = Tool(
        name="calculate",
        description="计算两个整数的乘积并返回",
        parameters={"type": "object",
                    "properties": {"a": {"type": "integer"},
                                   "b": {"type": "integer"}},
                    "required": ["a", "b"]},
        handler=calculate,
    )

    events: list[str] = []
    ctx = ToolContext(task_id=0, user_id=1, workspace_id=1,
                      role="analyst", datasets=[])

    from agent_adapter.toolloop.runtime import attach_context

    session = attach_context(
        AgentSession(
            agent_name="main",
            system_prompt="你是计算助手。必须调用 calculate 工具获取结果，然后给出最终回答。",
            messages=[{"role": "user", "content": "6 乘 7 等于多少？"}],
            tools=[tool],
            event_sink=lambda e: events.append(e.type),
            budget=Budget(max_steps=8, max_tool_calls=4, max_tokens=60000),
        ),
        ctx,
    )

    runtime = SwarmFlowRuntime()
    result = await runtime.run(session, model="t2d/deepseek-v4.1-flash-1017")

    all_ok &= check("tool handler executed", len(calls) == 1, f"calls={calls}")
    all_ok &= check("tool_results captured",
                    result.tool_results.get("calculate", {}).get("value") == 42)
    all_ok &= check("status succeeded", result.status == "succeeded", result.status)
    all_ok &= check("answer contains 42", "42" in (result.content or ""))
    all_ok &= check("events mapped", "run_started" in events and "message" in events,
                    str(events))
    all_ok &= check("token usage recorded",
                    result.token_usage.get("total_tokens", 0) > 0,
                    str(result.token_usage))

    print("\n═══ 结果 ═══")
    print("✅ SwarmFlow 适配器集成测试全部通过" if all_ok else "❌ 存在失败项")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
