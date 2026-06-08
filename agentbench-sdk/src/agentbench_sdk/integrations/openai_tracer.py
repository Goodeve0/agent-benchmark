"""OpenAI SDK 回调集成 — 自动捕获 ChatCompletion 调用。"""

from __future__ import annotations

import json
import time
from typing import Any

from agentbench_sdk.client import TraceClient
from agentbench_sdk.context import get_current


class OpenAITracer:
    """OpenAI SDK 自动追踪器。

    用法::

        from agentbench_sdk import TraceClient
        from agentbench_sdk.integrations import OpenAITracer

        client = TraceClient(endpoint="...", agent_name="my-agent")
        tracer = OpenAITracer(client)

        with client.trace(task_id="task_001") as t:
            # OpenAI 调用会被自动记录
            response = openai.ChatCompletion.create(
                model="gpt-4o", messages=[...], tools=[...]
            )
    """

    def __init__(self, client: TraceClient) -> None:
        self._client = client
        self._original_create: Any = None
        self._wrapped = False

    def wrap(self) -> None:
        """Monkey-patch openai.ChatCompletion.create 以自动追踪。"""
        if self._wrapped:
            return

        try:
            import openai
        except ImportError:
            raise ImportError(
                "openai 包未安装。请运行: pip install agentbench-sdk[openai]"
            ) from None

        client_ref = self._client
        original_create = openai.resources.chat.completions.Completions.create

        async def wrapped_create(self_completions, *args, **kwargs):
            """包装后的 create 方法。"""
            ctx = get_current()
            start = time.time()

            # 调用原始方法
            response = await original_create(self_completions, *args, **kwargs)

            duration = (time.time() - start) * 1000

            # 如果有活跃的 TraceContext，自动记录
            if ctx is not None:
                # 提取信息
                model = kwargs.get("model", "unknown")
                message = response.choices[0].message if response.choices else None

                # 记录工具调用
                tool_calls = getattr(message, "tool_calls", None) if message else None
                if tool_calls:
                    for call in tool_calls:
                        ctx.action(
                            action_type="tool_call",
                            tool_name=call.function.name,
                            parameters=json.loads(call.function.arguments) if call.function.arguments else {},
                            duration_ms=duration / max(len(tool_calls), 1),
                        )
                else:
                    # 记录文本回复
                    content = message.content if message else ""
                    ctx.action(
                        action_type="response",
                        content=content or "",
                        duration_ms=duration,
                    )

                # 更新 token 统计
                if hasattr(response, "usage") and response.usage:
                    current_tokens = ctx._payload.total_tokens
                    ctx.set_summary(
                        total_tokens=current_tokens + (response.usage.total_tokens or 0)
                    )

            return response

        openai.resources.chat.completions.Completions.create = wrapped_create
        self._original_create = original_create
        self._wrapped = True

    def unwrap(self) -> None:
        """恢复原始的 openai.ChatCompletion.create。"""
        if not self._wrapped or self._original_create is None:
            return

        try:
            import openai
            openai.resources.chat.completions.Completions.create = self._original_create
        except ImportError:
            pass

        self._wrapped = False
        self._original_create = None
