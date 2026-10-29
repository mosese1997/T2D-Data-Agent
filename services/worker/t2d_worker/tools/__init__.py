"""Tool registry: the 9 tools bound to a per-task ToolContext.

run_analysis is registered in phase 5 (analysis sub-agent + sandbox) —
until then it is NOT offered to the model (no fake capability entries,
CLAUDE.md rule 3).
"""

from __future__ import annotations

from agent_adapter import Tool, ToolContext

from .dashboard_tools import build_dashboard_tools
from .query_tools import build_query_tools
from .semantics_tools import build_semantics_tools


def build_tools_for(
    agent_name: str,
    ctx: ToolContext,
    deps,
    *,
    cancel_check=None,
) -> list[Tool]:
    """Tool set per agent role (task book §9):
    - main: semantics + patch (simple edits direct; delegation via runner)
    - query: semantics + query pipeline
    - analysis: + run_analysis (phase 5)
    """
    tools: list[Tool] = []
    if agent_name in ("main", "query", "analysis"):
        tools += build_semantics_tools(ctx, deps)
    if agent_name in ("query", "analysis"):
        tools += build_query_tools(ctx, deps, cancel_check=cancel_check)
    if agent_name in ("main", "analysis"):
        tools += build_dashboard_tools(ctx, deps)
    # phase 5: if agent_name == "analysis": tools += build_analysis_tools(...)
    return tools


__all__ = ["build_tools_for"]
