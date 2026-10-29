"""Thin LLM client over the LiteLLM proxy (OpenAI-compatible).

Hard rule (CLAUDE.md rule 1): only ever the OpenAI-compatible path
(/v1/chat/completions) on the local proxy. The MaaS /anthropic route is
never used for tool calls (53-60% streaming truncation, see /root/bug-reports).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from openai import AsyncOpenAI


@dataclass
class LLMResponse:
    content: str | None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    # [{id, name, arguments(str)}]
    finish_reason: str = ""
    usage: dict[str, int] = field(default_factory=dict)


class LLMClient:
    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout: float | None = None,
    ) -> None:
        self._client = AsyncOpenAI(
            base_url=base_url or os.environ.get("MODEL_API_BASE", "http://localhost:4000/v1"),
            api_key=api_key or os.environ.get("MODEL_API_KEY", "change-me"),
            timeout=timeout or float(os.environ.get("MODEL_TIMEOUT_S", "120")),
            max_retries=1,  # transport-level retries; semantic retries live in retry.py
        )

    async def chat(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.2,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        if max_tokens:
            kwargs["max_tokens"] = max_tokens
        resp = await self._client.chat.completions.create(**kwargs)
        choice = resp.choices[0]
        message = choice.message
        tool_calls: list[dict[str, Any]] = []
        for tc in message.tool_calls or []:
            tool_calls.append(
                {
                    "id": tc.id,
                    "name": tc.function.name,
                    "arguments": tc.function.arguments or "{}",
                }
            )
        usage = {}
        if resp.usage:
            usage = {
                "prompt_tokens": resp.usage.prompt_tokens or 0,
                "completion_tokens": resp.usage.completion_tokens or 0,
                "total_tokens": resp.usage.total_tokens or 0,
            }
        return LLMResponse(
            content=message.content,
            tool_calls=tool_calls,
            finish_reason=choice.finish_reason or "",
            usage=usage,
        )
