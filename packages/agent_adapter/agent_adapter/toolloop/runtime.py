"""ToolLoopRuntime — the baseline agent runtime.

Loop: chat → tool_calls? → execute each handler with the server-built
ToolContext → append results → repeat. Cancellation is cooperative at every
step boundary and every tool entry. Budget (steps / tool calls / tokens) is
enforced locally; exceeding it ends the run with an explained failure.
"""

from __future__ import annotations

import json

from ..base import (
    AgentEvent,
    AgentResult,
    AgentRuntime,
    AgentSession,
    RuntimeCapabilities,
    ToolContext,
    ToolError,
)
from ..llm import LLMClient, LLMResponse
from .retry import NUDGE_MESSAGE, NudgeState, needs_nudge


class BudgetExceeded(ToolError):
    def __init__(self, what: str):
        super().__init__(
            code="budget_exceeded",
            message=f"任务预算已用尽（{what}），按配置终止并说明原因",
            retryable=False,
        )


class ToolLoopRuntime(AgentRuntime):
    name = "toolloop"
    capabilities = RuntimeCapabilities(
        streaming=False,
        parallel_subagents=False,
        step_level_cancel=True,
        budget_control=True,
        human_in_loop=False,
    )

    def __init__(self, client: LLMClient | None = None) -> None:
        self.client = client or LLMClient()

    async def run(self, session: AgentSession, *, model: str) -> AgentResult:
        sink = session.event_sink or (lambda _e: None)
        cancel = session.cancel_token
        budget = session.budget
        nudges = NudgeState()
        usage_total: dict[str, int] = {}
        tool_calls_used = 0
        messages = [ {"role": "system", "content": session.system_prompt},
                     *session.messages ]
        tool_schemas = [t.openai_schema() for t in session.tools]

        sink(AgentEvent("run_started", {"agent": session.agent_name, "model": model}))

        for step in range(1, budget.max_steps + 1):
            if cancel.cancelled:
                sink(AgentEvent("cancelled", {"agent": session.agent_name, "at_step": step}))
                return AgentResult(status="cancelled", steps=step - 1,
                                   tool_calls=tool_calls_used, token_usage=usage_total)

            response: LLMResponse = await self.client.chat(
                model=model, messages=messages, tools=tool_schemas or None
            )
            for key, value in response.usage.items():
                usage_total[key] = usage_total.get(key, 0) + value
            if usage_total.get("total_tokens", 0) > budget.max_tokens:
                sink(AgentEvent("error", {"code": "budget_exceeded", "what": "tokens"}))
                return AgentResult(
                    status="failed",
                    error=BudgetExceeded("模型 token").as_payload(),
                    steps=step, tool_calls=tool_calls_used, token_usage=usage_total,
                )

            # ── tool calls ────────────────────────────────────────────
            if response.tool_calls:
                messages.append({
                    "role": "assistant",
                    "content": response.content or "",
                    "tool_calls": [
                        {
                            "id": tc["id"],
                            "type": "function",
                            "function": {"name": tc["name"], "arguments": tc["arguments"]},
                        }
                        for tc in response.tool_calls
                    ],
                })
                for tc in response.tool_calls:
                    tool_calls_used += 1
                    if tool_calls_used > budget.max_tool_calls:
                        sink(AgentEvent("error", {"code": "budget_exceeded", "what": "tool calls"}))
                        return AgentResult(
                            status="failed",
                            error=BudgetExceeded("工具调用次数").as_payload(),
                            steps=step, tool_calls=tool_calls_used - 1,
                            token_usage=usage_total,
                        )
                    result_payload = await self._execute_tool(
                        session, sink, cancel, tc
                    )
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": json.dumps(result_payload, ensure_ascii=False, default=str),
                    })
                continue

            # ── no tool calls ─────────────────────────────────────────
            if needs_nudge(response) and tool_schemas and nudges.consume():
                messages.append(NUDGE_MESSAGE)
                continue
            if needs_nudge(response):
                sink(AgentEvent("error", {
                    "code": "empty_response",
                    "message": "模型连续返回空结果且重试预算用尽",
                }))
                return AgentResult(
                    status="failed",
                    error={"code": "empty_response",
                           "message": "模型连续返回空结果且重试预算用尽"},
                    steps=step, tool_calls=tool_calls_used, token_usage=usage_total,
                )

            # Final answer.
            sink(AgentEvent("message", {"agent": session.agent_name,
                                        "content": response.content or ""}))
            structured = None
            if session.expect_structured:
                structured = self._try_parse_structured(response.content or "")
            return AgentResult(
                status="succeeded",
                content=response.content,
                structured=structured,
                steps=step,
                tool_calls=tool_calls_used,
                token_usage=usage_total,
            )

        sink(AgentEvent("error", {"code": "budget_exceeded", "what": "steps"}))
        return AgentResult(
            status="failed",
            error=BudgetExceeded("推理步数").as_payload(),
            steps=budget.max_steps, tool_calls=tool_calls_used, token_usage=usage_total,
        )

    async def _execute_tool(
        self,
        session: AgentSession,
        sink,
        cancel,
        tc: dict,
    ) -> dict:
        """Execute one tool call with the server-built ToolContext."""
        tool = next((t for t in session.tools if t.name == tc["name"]), None)
        if tool is None:
            return {"error": {"code": "unknown_tool",
                              "message": f"工具 {tc['name']} 不存在",
                              "retryable": False}}
        if cancel.cancelled:
            return {"error": {"code": "cancelled",
                              "message": "任务已取消", "retryable": False}}
        try:
            args = json.loads(tc["arguments"] or "{}")
            if not isinstance(args, dict):
                raise ToolError("bad_arguments", "工具参数必须是 JSON 对象")
        except json.JSONDecodeError as exc:
            return {"error": {"code": "bad_arguments",
                              "message": f"工具参数不是合法 JSON: {exc}",
                              "retryable": True}}

        sink(AgentEvent("tool_call", {"agent": session.agent_name, "tool": tool.name}))
        try:
            # ToolContext comes from the session (built server-side from the
            # task row) — never from model-supplied arguments.
            result = await tool.handler(session_ctx(session), args)
            summary = result.get("_summary") or "完成"
            payload = {k: v for k, v in result.items() if k != "_summary"}
            sink(AgentEvent("tool_result", {"agent": session.agent_name,
                                            "tool": tool.name, "summary": summary}))
            return payload
        except ToolError as exc:
            sink(AgentEvent("tool_result", {"agent": session.agent_name,
                                            "tool": tool.name,
                                            "summary": f"失败: {exc.message}"}))
            return exc.as_payload()

    @staticmethod
    def _try_parse_structured(text: str) -> dict | None:
        """Extract the first JSON object from a final answer (sub-agents)."""
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end <= start:
            return None
        try:
            parsed = json.loads(text[start : end + 1])
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            return None


# ToolContext travels on the session via a private attribute set by the
# worker when it builds the session — keeps the runtime signature simple.
_SESSION_CTX_KEY = "_tool_context"


def session_ctx(session: AgentSession) -> ToolContext:
    ctx = getattr(session, _SESSION_CTX_KEY, None)
    if ctx is None:
        raise RuntimeError(
            "AgentSession 缺少服务端注入的 ToolContext（worker 构建会话时必须设置）"
        )
    return ctx


def attach_context(session: AgentSession, ctx: ToolContext) -> AgentSession:
    setattr(session, _SESSION_CTX_KEY, ctx)
    return session
