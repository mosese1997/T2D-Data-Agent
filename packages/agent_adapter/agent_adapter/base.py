"""Agent runtime contract: sessions, tools, events, budgets, cancellation.

Security invariant (CLAUDE.md rule 2): tool JSON schemas are model-visible
and MUST NOT contain identity fields. The ToolContext (user / task /
workspace / role / authorized datasets) is constructed server-side from the
task row and passed to handlers directly — the model has no identity
parameter it could forge.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable


def utcnow() -> datetime:
    """Naive UTC now — matches the state DB clock."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


@dataclass
class ToolContext:
    """Server-injected identity & permission scope for one task run."""

    task_id: int | None  # None = 无关联任务（MCP 直连等场景）
    user_id: int
    workspace_id: int
    role: str  # admin | analyst | viewer
    datasets: list[str]  # authorized dataset whitelist
    demo_mode: bool = True


class ToolError(Exception):
    """Tool failure with a structured, model-safe error payload."""

    def __init__(self, code: str, message: str, *, retryable: bool = False, hint: str | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.hint = hint

    def as_payload(self) -> dict:
        return {"error": {"code": self.code, "message": self.message,
                          "retryable": self.retryable, "hint": self.hint}}


@dataclass
class Tool:
    """A model-callable tool. `parameters` is a JSON Schema (no identity!)."""

    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[[ToolContext, dict[str, Any]], Awaitable[dict[str, Any]]]

    def openai_schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


# Normalized agent event types → SSE event names (events.py has the map).
EVENT_TYPES = (
    "run_started", "step", "tool_call", "tool_result", "message",
    "subagent_started", "subagent_completed", "clarification", "error",
    "cancelled",
)


@dataclass
class AgentEvent:
    type: str  # one of EVENT_TYPES
    data: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=utcnow)


@dataclass
class Budget:
    max_steps: int = 40
    max_tool_calls: int = 30
    max_tokens: int = 500_000


class CancelToken:
    """Cooperative cancellation, checked at step & tool boundaries."""

    def __init__(self) -> None:
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    @property
    def cancelled(self) -> bool:
        return self._cancelled


EventSink = Callable[[AgentEvent], None]
TraceHook = Callable[[str, dict, dict | None, int, str], None]
# (tool_name, input_args, output_payload | None, latency_ms, status)


@dataclass
class AgentSession:
    """Everything one agent run needs. One session per task/agent — no
    cross-task global state in either runtime."""

    agent_name: str  # main | query | analysis
    system_prompt: str
    messages: list[dict[str, Any]]  # OpenAI-format chat messages
    tools: list[Tool] = field(default_factory=list)
    event_sink: EventSink | None = None
    cancel_token: CancelToken = field(default_factory=CancelToken)
    budget: Budget = field(default_factory=Budget)
    expect_structured: bool = False  # sub-agents return structured payloads
    parent_run_id: int | None = None
    # Trace detail (tool_calls rows for the admin Trace page). Raw inputs/
    # outputs go HERE, never into event_sink (SSE carries summaries only).
    trace_hook: TraceHook | None = None


@dataclass
class AgentResult:
    status: str  # succeeded | failed | cancelled
    content: str | None = None  # final assistant text
    structured: dict[str, Any] | None = None  # parsed structured payload
    token_usage: dict[str, int] = field(default_factory=dict)
    steps: int = 0
    tool_calls: int = 0
    error: dict[str, Any] | None = None
    # Last result per tool name — the runner reads source_id / patch_id from
    # here instead of trusting the model to echo them back.
    tool_results: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass
class RuntimeCapabilities:
    streaming: bool = False
    parallel_subagents: bool = False
    step_level_cancel: bool = False  # False = task-level cancel only
    budget_control: bool = False
    human_in_loop: bool = False


class AgentRuntime(ABC):
    """Abstract runtime. `run` drives one session to completion; `spawn`
    convenience-wraps run() for sub-agents with subagent events."""

    name: str = "abstract"
    capabilities: RuntimeCapabilities = RuntimeCapabilities()

    @abstractmethod
    async def run(self, session: AgentSession, *, model: str) -> AgentResult:
        ...

    async def spawn(
        self, session: AgentSession, *, model: str
    ) -> AgentResult:
        """Run a sub-agent session, emitting subagent_* events upstream."""
        sink = session.event_sink

        def wrapped(event: AgentEvent) -> None:
            if sink:
                sink(event)

        session.event_sink = wrapped
        if sink:
            sink(AgentEvent("subagent_started", {"agent": session.agent_name}))
        result = await self.run(session, model=model)
        if sink:
            sink(AgentEvent(
                "subagent_completed",
                {"agent": session.agent_name, "status": result.status},
            ))
        return result
