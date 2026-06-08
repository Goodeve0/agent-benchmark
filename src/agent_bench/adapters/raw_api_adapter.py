"""Raw API 适配器：直接调用 OpenAI ChatCompletion + Function Calling。

对应 docs/SDD.md 内置适配器。

依赖 openai（可选）。未安装时实例化会抛出友好提示。
所有工具调用通过 Sandbox 路由，不触达真实外部 API。
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from agent_bench.adapters.base import BaseAdapter
from agent_bench.exceptions import AgentStepLimitError, AgentTimeoutError
from agent_bench.models import AgentAction, AgentTrace, ToolDef
from agent_bench.sandbox import Sandbox

_SYSTEM_PROMPT = (
    "你是一个能够使用工具的智能助手。请根据用户任务，按需调用提供的工具，"
    "并在获得足够信息后给出简洁明确的最终答复。"
)


class RawAPIAdapter(BaseAdapter):
    """基于 OpenAI 原生 Function Calling 的 Agent 适配器。"""

    def __init__(
        self,
        model: str = "gpt-4o",
        name: str = "raw-api-agent",
        api_key: str | None = None,
        base_url: str | None = None,
    ) -> None:
        """
        Args:
            model: 使用的模型名。
            name: Agent 名称。
            api_key: OpenAI API Key，None 时从环境变量读取。
            base_url: 自定义 API 端点（可选）。

        Raises:
            ImportError: 未安装 openai 依赖。
        """
        try:
            from openai import AsyncOpenAI
        except ImportError as e:  # pragma: no cover - 取决于环境
            raise ImportError(
                "RawAPIAdapter 需要 openai 依赖，请安装: pip install 'agent-bench[openai]'"
            ) from e

        self.model = model
        self.name = name
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)

    async def run_task(
        self,
        task_prompt: str,
        tools: list[ToolDef],
        sandbox: Sandbox,
        max_steps: int = 10,
        timeout: int = 60,
    ) -> AgentTrace:
        try:
            return await asyncio.wait_for(
                self._run_loop(task_prompt, tools, sandbox, max_steps),
                timeout=timeout,
            )
        except asyncio.TimeoutError as e:
            raise AgentTimeoutError(f"Agent 执行超过 {timeout}s") from e

    def get_agent_info(self) -> dict:
        return {"name": self.name, "model": self.model, "framework": "raw_openai"}

    # ---- 内部方法 ----

    async def _run_loop(
        self,
        task_prompt: str,
        tools: list[ToolDef],
        sandbox: Sandbox,
        max_steps: int,
    ) -> AgentTrace:
        start = time.time()
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": task_prompt},
        ]
        openai_tools = [self._to_openai_tool(t) for t in tools]

        actions: list[AgentAction] = []
        total_tokens = 0
        step = 0

        while step < max_steps:
            step += 1
            resp = await self._client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=openai_tools or None,
                tool_choice="auto" if openai_tools else None,
            )
            total_tokens += self._extract_tokens(resp)
            message = resp.choices[0].message

            tool_calls = getattr(message, "tool_calls", None)
            if not tool_calls:
                # 没有工具调用 → 最终回复
                final = message.content or ""
                actions.append(
                    AgentAction(step=step, action_type="response", content=final)
                )
                return AgentTrace(
                    task_id="",
                    actions=actions,
                    total_tokens=total_tokens,
                    total_steps=step,
                    final_response=final,
                    execution_time=round(time.time() - start, 4),
                    success=True,
                )

            # 处理工具调用（可能并行多个）
            messages.append(message.model_dump())
            for call in tool_calls:
                tool_name = call.function.name
                params = self._parse_args(call.function.arguments)
                result = await sandbox.execute_tool(tool_name, params)
                actions.append(
                    AgentAction(
                        step=step,
                        action_type="tool_call",
                        tool_name=tool_name,
                        parameters=params,
                        result=result,
                    )
                )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )

        # 超出步数限制
        raise AgentStepLimitError(f"Agent 超过最大步数 {max_steps}")

    @staticmethod
    def _to_openai_tool(tool: ToolDef) -> dict[str, Any]:
        """将 ToolDef 转为 OpenAI tools 格式。"""
        return {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters or {"type": "object", "properties": {}},
            },
        }

    @staticmethod
    def _parse_args(raw: str | None) -> dict[str, Any]:
        """解析工具调用参数 JSON，失败时返回空字典。"""
        if not raw:
            return {}
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}

    @staticmethod
    def _extract_tokens(resp: Any) -> int:
        """从响应中提取 token 用量。"""
        usage = getattr(resp, "usage", None)
        if usage is None:
            return 0
        return getattr(usage, "total_tokens", 0) or 0
