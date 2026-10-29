"""Semantic retry: handle "should have called a tool but returned stop".

Observed upstream failure mode (GLM-5.2 with thinking disabled returns
finish_reason=stop instead of a tool call ~10% of the time; tracked in
vllm-ascend#11486). deepseek-v4.1-flash-1017 is the t2d route, but the same
defense applies: when tools were offered and the model returns neither tool
calls nor usable content, append a nudge message and retry — at most
MODEL_MAX_RETRIES times, then surface a real error (never silently degrade).
"""

from __future__ import annotations

import os

MAX_NUDGES = int(os.environ.get("MODEL_MAX_RETRIES", "2"))

NUDGE_MESSAGE = {
    "role": "user",
    "content": (
        "你刚才没有调用任何工具，也没有给出最终回答。"
        "如果需要数据或定义，请调用可用工具；如果已有足够信息，请给出最终回答。"
    ),
}


def needs_nudge(response) -> bool:
    """True when the model returned an empty stop with tools on the table."""
    has_content = bool((response.content or "").strip())
    return not response.tool_calls and not has_content


class NudgeState:
    """Tracks nudge budget across one agent run."""

    def __init__(self, max_nudges: int = MAX_NUDGES) -> None:
        self.max_nudges = max_nudges
        self.used = 0

    def consume(self) -> bool:
        """Try to consume a nudge; False when the budget is exhausted."""
        if self.used >= self.max_nudges:
            return False
        self.used += 1
        return True
