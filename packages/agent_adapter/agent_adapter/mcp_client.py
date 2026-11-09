"""MCP client for the toolloop: load remote MCP tools as local Tool objects.

Design (evolution plan E1): each task opens one MCP connection carrying the
task's identity headers (X-T2D-*), lists the remote tools, and wraps each
as an agent_adapter.Tool — the SAME contract the inline tools use. The
toolloop is completely unaware of the transport.

Governance note: the MCP server validates the identity headers against the
state DB on every call (see services/dws-mcp-server/t2d_mcp_server/context.py).
The headers are injected here from the server-side ToolContext — the model
never touches them.
"""

from __future__ import annotations

import json
from typing import Any

from .base import Tool, ToolContext, ToolError


class McpToolSession:
    """One MCP connection bound to one task's identity.

    Usage:
        session = McpToolSession("http://localhost:9100/mcp", ctx)
        tools = await session.load_tools()
        ... toolloop runs with tools ...
        await session.close()
    """

    def __init__(self, server_url: str, ctx: ToolContext) -> None:
        self.server_url = server_url
        self.ctx = ctx
        self._transport_cm = None
        self._session_cm = None
        self._session = None

    async def _connect(self):
        if self._session is not None:
            return self._session
        from mcp import ClientSession
        from mcp.client.streamable_http import (
            create_mcp_http_client,
            streamable_http_client,
        )

        headers = {
            "X-T2D-User": str(self.ctx.user_id),
            "X-T2D-Workspace": str(self.ctx.workspace_id),
            "X-T2D-Task": str(self.ctx.task_id),
        }
        http_client = create_mcp_http_client(headers=headers)
        self._transport_cm = streamable_http_client(self.server_url, http_client=http_client)
        read, write = await self._transport_cm.__aenter__()
        self._session_cm = ClientSession(read, write)
        self._session = await self._session_cm.__aenter__()
        await self._session.initialize()
        return self._session

    async def load_tools(self) -> list[Tool]:
        """List remote tools and wrap each as an agent_adapter.Tool."""
        session = await self._connect()
        result = await session.list_tools()
        tools: list[Tool] = []
        for remote in result.tools:
            tools.append(self._wrap(remote))
        return tools

    def _wrap(self, remote) -> Tool:
        """Wrap one MCP remote tool as a local Tool (same contract)."""
        # MCP Tool field is `input_schema` (snake_case in the SDK types).
        parameters = getattr(remote, "input_schema", None) or {
            "type": "object", "properties": {},
        }
        name = remote.name
        description = remote.description or ""

        async def handler(ctx: ToolContext, args: dict) -> dict:
            session = await self._connect()
            result = await session.call_tool(name, args)
            if result.is_error:
                # The server returns structured errors as text; surface them.
                text = result.content[0].text if result.content else ""
                try:
                    payload = json.loads(text)
                    if "error" in payload:
                        return payload
                except json.JSONDecodeError:
                    pass
                raise ToolError("mcp_tool_error", text[:300] or "MCP 工具执行失败")
            if not result.content:
                return {}
            text = result.content[0].text
            try:
                payload = json.loads(text)
                return payload if isinstance(payload, dict) else {"value": payload}
            except json.JSONDecodeError:
                return {"value": text}

        return Tool(name=name, description=description,
                    parameters=parameters, handler=handler)

    async def close(self) -> None:
        if self._session_cm is not None:
            await self._session_cm.__aexit__(None, None, None)
            self._session_cm = None
            self._session = None
        if self._transport_cm is not None:
            await self._transport_cm.__aexit__(None, None, None)
            self._transport_cm = None
