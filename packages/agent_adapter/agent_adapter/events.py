"""AgentEvent → SSE event mapping.

The worker translates normalized agent events into run_events rows; this map
defines the SSE `event:` names. Tool events carry only the tool name and a
summary — never raw inputs or model reasoning (CLAUDE.md rule 6).
"""

from __future__ import annotations

import json

# agent event type -> (SSE event name, include_in_sse)
SSE_EVENT_MAP: dict[str, tuple[str, bool]] = {
    "run_started": ("phase.started", True),
    "step": ("phase.completed", True),
    "tool_call": ("tool.started", True),
    "tool_result": ("tool.completed", True),
    "message": ("agent.message", True),
    "subagent_started": ("phase.started", True),
    "subagent_completed": ("phase.completed", True),
    "clarification": ("clarification.requested", True),
    "error": ("task.failed", True),
    "cancelled": ("task.cancelled", True),
}


def to_sse(event_type: str, data: dict) -> tuple[str, str] | None:
    """Return (sse_event_name, payload) or None if not SSE-visible."""
    entry = SSE_EVENT_MAP.get(event_type)
    if not entry or not entry[1]:
        return None
    name = entry[0]
    payload = dict(data)
    # Tool events: strip everything but the name + human summary.
    if event_type in ("tool_call", "tool_result"):
        payload = {
            "tool": data.get("tool"),
            "agent": data.get("agent"),
            "summary": data.get("summary"),
        }
    return name, json.dumps(payload, ensure_ascii=False, default=str)
