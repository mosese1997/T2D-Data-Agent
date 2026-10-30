"""SwarmFlowRuntime — AgentRuntime over JiuwenSwarm's SwarmFlow engine.

Integration recipe (probe-verified, see docs/phase-notes/swarmflow-probe.md
and boundaries.md):
- entry: openjiuwen.agent_teams.workflow.engine.run_workflow()
- backend: TeamWorkerBackend + programmatic DeepAgentSpec (OpenAI-compatible
  ModelClientConfig → the LiteLLM proxy; enable_sys_operation=False;
  enable_read_image_multimodal=False to skip the per-worker probe call)
- tools: our Tool JSON Schemas passed via @tool(input_params=…, auto_extract=False)
  and injected with spec.model_copy(update={"tools": [...]}) — the same
  internal pattern the framework uses for StructuredOutputTool
- events: progress_sink → AgentEvent (map in boundaries.md §3)
- cancel: AbortSignal.set("stop") driven by the session's CancelToken
  (cooperative; in-flight calls complete — task-level granularity)
- budget: two-layer BudgetLedger (session budget= + META.workflow_token_limit)

Dependency note (honest boundary): openjiuwen/workswarm is NOT installed in
the system python or the worker image by default (heavy deps: google-adk
etc.). Imports are lazy; instantiating without the package raises a clear
error. Verified against the real engine under var/probe-venv via
scripts/test_swarmflow_adapter.py.
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

from ..base import (
    AgentEvent,
    AgentResult,
    AgentRuntime,
    AgentSession,
    RuntimeCapabilities,
)

# progress-event kind → AgentEvent type (boundaries.md §3; human_* dropped)
_EVENT_MAP = {
    "workflow_started": ("run_started", None),
    "phase": ("step", None),
    "log": ("step", None),
    "agent_started": ("subagent_started", None),
    "agent_completed": ("subagent_completed", None),
    "agent_failed": ("error", None),
    "workflow_completed": ("message", None),
    "workflow_failed": ("error", None),
    "workflow_paused": ("cancelled", None),
    "workflow_stopped": ("cancelled", None),
}


def _require_openjiuwen():
    try:
        from openjiuwen.agent_teams.workflow.backends.team_worker_backend import (
            TeamWorkerBackend,
        )
        from openjiuwen.agent_teams.workflow.engine import run_workflow
        from openjiuwen.core.foundation.tool import tool as oj_tool
        from openjiuwen.harness.schema.deep_agent_spec import (
            DeepAgentSpec,
            TeamModelConfig,
            WorkspaceSpec,
        )
        from openjiuwen.core.foundation.llm.schema.config import (
            ModelClientConfig,
            ModelRequestConfig,
        )
        from openjiuwen.core.single_agent.schema.agent_card import AgentCard
    except ImportError as exc:
        raise RuntimeError(
            "swarmflow 运行时需要 openjiuwen/workswarm（当前环境未安装）。"
            "安装方式与验证脚本见 packages/agent_adapter/agent_adapter/boundaries.md"
        ) from exc
    return {
        "TeamWorkerBackend": TeamWorkerBackend,
        "run_workflow": run_workflow,
        "tool": oj_tool,
        "DeepAgentSpec": DeepAgentSpec,
        "TeamModelConfig": TeamModelConfig,
        "WorkspaceSpec": WorkspaceSpec,
        "ModelClientConfig": ModelClientConfig,
        "ModelRequestConfig": ModelRequestConfig,
        "AgentCard": AgentCard,
    }


def available() -> bool:
    """True when the swarmflow engine is importable in this environment."""
    try:
        _require_openjiuwen()
        return True
    except RuntimeError:
        return False


class SwarmFlowRuntime(AgentRuntime):
    name = "swarmflow"
    capabilities = RuntimeCapabilities(
        streaming=False,
        parallel_subagents=True,
        step_level_cancel=False,  # task-level: in-flight calls complete
        budget_control=True,
        human_in_loop=False,
    )

    def __init__(self, *, api_base: str | None = None, api_key: str | None = None):
        self.api_base = api_base or os.environ.get("MODEL_API_BASE", "http://localhost:4000/v1")
        self.api_key = api_key or os.environ.get("MODEL_API_KEY", "change-me")

    async def run(self, session: AgentSession, *, model: str) -> AgentResult:
        oj = _require_openjiuwen()
        sink = session.event_sink or (lambda _e: None)
        tool_results: dict[str, dict] = {}
        usage_total: dict[str, int] = {}

        # ── wrap our Tools as openjiuwen LocalFunctions ──────────────
        # JSON Schema passed directly (auto_extract=False); the handler
        # closes over the server-built ToolContext — identity never comes
        # from the model (CLAUDE.md rule 2, same as toolloop).
        from ..toolloop.runtime import session_ctx

        ctx = session_ctx(session)
        oj_tools = []
        for t in session.tools:
            results_sink = tool_results

            async def _handler(args, _t=t):
                import time as _time

                started = _time.monotonic()
                if session.trace_hook:
                    session.trace_hook(_t.name, args, None, 0, "started")
                try:
                    result = await _t.handler(ctx, args)
                    payload = {k: v for k, v in result.items() if k != "_summary"}
                    summary = result.get("_summary") or "完成"
                except Exception as exc:  # ToolError or anything else
                    payload = {"error": {"code": type(exc).__name__,
                                         "message": str(exc)[:300],
                                         "retryable": False}}
                    summary = f"失败: {str(exc)[:80]}"
                if session.trace_hook:
                    session.trace_hook(_t.name, args, payload,
                                       int((_time.monotonic() - started) * 1000),
                                       "ok" if "error" not in payload else "error")
                sink(AgentEvent("tool_call", {"agent": session.agent_name,
                                              "tool": _t.name}))
                sink(AgentEvent("tool_result", {"agent": session.agent_name,
                                                "tool": _t.name, "summary": summary}))
                results_sink[_t.name] = payload
                return json.dumps(payload, ensure_ascii=False, default=str)

            def _make(tool_def, handler):
                # one handler per tool (late-binding safe)
                async def _call(**kwargs):
                    return await handler(kwargs)
                _call.__name__ = tool_def.name
                _call.__doc__ = tool_def.description
                return oj["tool"](
                    name=tool_def.name,
                    description=tool_def.description,
                    input_params=tool_def.parameters,
                    auto_extract=False,
                    stateless=True,
                )(_call)

            oj_tools.append(_make(t, _handler))

        # ── worker spec (probe recipe) ───────────────────────────────
        spec = oj["DeepAgentSpec"](
            model=oj["TeamModelConfig"](
                model_client_config=oj["ModelClientConfig"](
                    client_provider="OpenAI",
                    api_key=self.api_key,
                    api_base=self.api_base,
                ),
                model_request_config=oj["ModelRequestConfig"](
                    model=model, temperature=0.2),
            ),
            card=oj["AgentCard"](id=f"t2d_{session.agent_name}",
                                 name=f"t2d_{session.agent_name}",
                                 description=f"t2d {session.agent_name} worker"),
            system_prompt=session.system_prompt,
            tools=[],
            enable_sys_operation=False,
            enable_task_loop=False,
            enable_task_planning=False,
            enable_skill_discovery=False,
            enable_read_image_multimodal=False,  # skip per-worker probe call
            workspace=oj["WorkspaceSpec"](
                root_path=tempfile.mkdtemp(prefix="t2d_swarmflow_"),
                language="en", stable_base=False,
            ),
        )
        spec = spec.model_copy(update={"tools": oj_tools})

        backend = oj["TeamWorkerBackend"](
            model=None, team_name="t2d", language="en", worker_base_spec=spec)

        # ── workflow script: one agent() carrying the conversation ──
        conversation = []
        for message in session.messages:
            role = message.get("role", "user")
            content = message.get("content", "")
            if role == "tool":
                content = f"[工具结果] {message.get('content', '')[:2000]}"
            conversation.append(f"[{role}] {content}")
        prompt = "\n".join(conversation)
        if session.expect_structured:
            agent_call = (
                '    result = await agent(prompt, schema={"type": "object"}, '
                'label="answer", phase="Answer")\n'
            )
        else:
            agent_call = (
                '    result = await agent(prompt, label="answer", phase="Answer")\n'
            )
        script = (
            "META = {\n"
            f'    "name": "t2d_{session.agent_name}_{uuid.uuid4().hex[:8]}",\n'
            '    "description": "t2d agent session",\n'
            '    "phases": ["Answer"],\n'
            f'    "workflow_token_limit": {int(session.budget.max_tokens)},\n'
            "}\n\n"
            "from swarmflow import agent, phase\n\n"
            "async def run(args):\n"
            '    phase("Answer")\n'
            '    prompt = args["prompt"]\n'
            + agent_call +
            '    return {"answer": result}\n'
        )
        script_path = Path(tempfile.mkdtemp(prefix="t2d_wf_")) / "workflow.py"
        script_path.write_text(script, encoding="utf-8")

        # ── events / cancel / budget plumbing ────────────────────────
        from openjiuwen.agent_teams.workflow.engine.budget import BudgetLedger
        from openjiuwen.agent_teams.workflow.engine.runtime import AbortSignal

        abort = AbortSignal()

        async def _cancel_watcher():
            while True:
                if session.cancel_token.cancelled:
                    abort.set("stop")
                    return
                await asyncio.sleep(0.5)

        watcher = asyncio.create_task(_cancel_watcher())

        def progress_sink(event) -> None:
            mapped = _EVENT_MAP.get(event.kind)
            if mapped is None:
                return  # human_* dropped (boundaries.md §3)
            agent_event_type, _ = mapped
            data = {}
            # WorkflowProgressEvent.tokens is an int (total) or None.
            tokens = getattr(event, "tokens", None)
            if isinstance(tokens, int) and tokens > 0:
                usage_total["total_tokens"] = usage_total.get("total_tokens", 0) + tokens
            if event.kind in ("agent_completed", "agent_failed"):
                data["agent"] = session.agent_name
                data["label"] = getattr(event, "label", None)
                outcome = getattr(event, "outcome", None)
                if outcome:
                    data["summary"] = str(outcome)[:200]
            elif event.kind == "workflow_completed":
                data["content"] = ""
            sink(AgentEvent(agent_event_type, data))

        budget = BudgetLedger(total=int(session.budget.max_tokens))
        try:
            result = await oj["run_workflow"](
                str(script_path),
                args={"prompt": prompt},
                backend=backend,
                progress_sink=progress_sink,
                budget=budget,
                abort_event=abort,
                cap=4,
            )
        except Exception as exc:  # WorkflowAborted / BudgetExhausted / engine errors
            name = type(exc).__name__
            if name == "WorkflowAborted" or session.cancel_token.cancelled:
                sink(AgentEvent("cancelled", {"agent": session.agent_name}))
                return AgentResult(status="cancelled",
                                   tool_results=tool_results,
                                   token_usage=usage_total)
            sink(AgentEvent("error", {"code": name, "message": str(exc)[:300]}))
            return AgentResult(status="failed",
                               error={"code": name, "message": str(exc)[:300]},
                               tool_results=tool_results, token_usage=usage_total)
        finally:
            watcher.cancel()

        answer = None
        if isinstance(result, dict):
            answer = result.get("answer")
        if isinstance(answer, dict):  # structured schema path returns dict
            structured = answer
            content = json.dumps(answer, ensure_ascii=False)
        else:
            structured = None
            content = answer if isinstance(answer, str) else (
                json.dumps(result, ensure_ascii=False, default=str)
                if result is not None else None)
        if content:
            sink(AgentEvent("message", {"agent": session.agent_name, "content": content}))
        return AgentResult(status="succeeded", content=content,
                           structured=structured, tool_results=tool_results,
                           token_usage=usage_total)
