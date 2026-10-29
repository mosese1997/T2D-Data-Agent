"""agent_adapter — swappable agent runtimes for t2d.

Two implementations behind one contract (see CLAUDE.md):
- toolloop: self-built OpenAI tool loop against the LiteLLM proxy. This is
  the P1 baseline AND the fallback if SwarmFlow verification fails.
- swarmflow: adapter over JiuwenSwarm's SwarmFlow engine, completed only
  after the phase-1 probe; gaps recorded in boundaries.md.

Upper layers (services/worker/t2d_worker/agents/*) only ever see
AgentRuntime / AgentSession / Tool — switching runtimes is a config change.
"""

from .base import (
    AgentEvent,
    AgentResult,
    AgentRuntime,
    AgentSession,
    Budget,
    CancelToken,
    RuntimeCapabilities,
    Tool,
    ToolContext,
    ToolError,
)
from .events import SSE_EVENT_MAP

__all__ = [
    "AgentEvent",
    "AgentResult",
    "AgentRuntime",
    "AgentSession",
    "Budget",
    "CancelToken",
    "RuntimeCapabilities",
    "Tool",
    "ToolContext",
    "ToolError",
    "SSE_EVENT_MAP",
]
