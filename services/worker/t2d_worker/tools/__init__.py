"""Tool registry: the 9 tools bound to a per-task ToolContext."""

from __future__ import annotations

from agent_adapter import Tool, ToolContext

from .analysis_tools import build_analysis_tools
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
    - analysis: query pipeline + run_analysis (sandbox)
    """
    tools: list[Tool] = []
    if agent_name in ("main", "query", "analysis"):
        tools += build_semantics_tools(ctx, deps)
    if agent_name in ("query", "analysis"):
        tools += build_query_tools(ctx, deps, cancel_check=cancel_check)
    if agent_name in ("main", "analysis"):
        tools += build_dashboard_tools(ctx, deps)
    if agent_name == "analysis":
        tools += build_analysis_tools(ctx, deps, cancel_check=cancel_check)
    return tools


__all__ = ["build_tools_for"]
