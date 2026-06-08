"""数据分析 Agent 适配器。

面向真实业务场景的 Agent：自然语言 → 理解意图 → 生成 SQL → 执行查询 → 分析结果。
这是 AgentBench 中第一个"真正会干活"的 Agent，展示完整的工具链组合能力。

工具链：
1. list_tables → 了解数据库有哪些表
2. describe_table → 获取表结构
3. query_database → 执行 SQL 查询
4. run_python → 分析查询结果（计算统计量、生成图表描述）

特点：
- 使用真实 OpenAI Function Calling
- 支持 RealSandbox（真实数据库查询）和 MockSandbox
- 自动注入数据库探索策略（先 list_tables 再 describe_table 再 query）
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from agent_bench.adapters.base import BaseAdapter
from agent_bench.exceptions import AgentStepLimitError, AgentTimeoutError
from agent_bench.models import AgentAction, AgentTrace, ToolDef
from agent_bench.sandbox.sandbox import Sandbox

_SYSTEM_PROMPT = """你是一个专业的数据分析师 Agent。你的任务是：
1. 首先使用 list_tables 了解数据库中有哪些表
2. 使用 describe_table 查看相关表的结构
3. 根据用户需求编写 SQL 查询（仅 SELECT 语句）
4. 使用 query_database 执行查询
5. 如果需要，使用 run_python 对查询结果进行分析和计算
6. 给出清晰、专业的分析结论

注意事项：
- SQL 查询仅支持 SELECT，不要尝试修改数据
- 先了解表结构再写 SQL，避免猜测列名
- 查询结果可能需要进一步分析，使用 run_python 计算
- 最终回复要包含关键数据洞察，而不仅仅是原始查询结果
"""


class DataAnalystAdapter(BaseAdapter):
    """数据分析 Agent — 自然语言查询数据库 + 分析结果。

    使用 OpenAI Function Calling 驱动，工具链覆盖从数据库探索到结果分析的全流程。
    """

    def __init__(
        self,
        model: str = "gpt-4o",
        name: str = "data-analyst",
        api_key: str | None = None,
        base_url: str | None = None,
    ) -> None:
        """
        Args:
            model: 使用的模型名。
            name: Agent 名称。
            api_key: OpenAI API Key。
            base_url: 自定义 API 端点。

        Raises:
            ImportError: 未安装 openai 依赖。
        """
        try:
            from openai import AsyncOpenAI
        except ImportError as e:
            raise ImportError(
                "DataAnalystAdapter 需要 openai 依赖，请安装: pip install 'agent-bench[openai]'"
            ) from e

        self.model = model
        self.name = name
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)

        # 内置数据分析工具定义
        self._builtin_tools = self._define_tools()

    async def run_task(
        self,
        task_prompt: str,
        tools: list[ToolDef],
        sandbox: Sandbox,
        max_steps: int = 10,
        timeout: int = 60,
        task_id: str = "",
    ) -> AgentTrace:
        try:
            trace = await asyncio.wait_for(
                self._run_loop(task_prompt, tools, sandbox, max_steps),
                timeout=timeout,
            )
            trace.task_id = task_id
            return trace
        except asyncio.TimeoutError as e:
            raise AgentTimeoutError(f"DataAnalyst 执行超过 {timeout}s") from e

    def get_agent_info(self) -> dict:
        return {
            "name": self.name,
            "model": self.model,
            "framework": "data_analyst",
            "tools": ["list_tables", "describe_table", "query_database", "run_python"],
        }

    def _define_tools(self) -> list[dict]:
        """定义数据分析工具（OpenAI Function Calling 格式）。"""
        return [
            {
                "type": "function",
                "function": {
                    "name": "list_tables",
                    "description": "列出数据库中所有可用的表名",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "describe_table",
                    "description": "获取指定表的结构信息，包括列名、类型等",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "table_name": {"type": "string", "description": "表名"},
                        },
                        "required": ["table_name"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "query_database",
                    "description": "执行 SQL 查询并返回结果。仅支持 SELECT 语句，禁止修改数据。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "sql": {"type": "string", "description": "SQL 查询语句（仅 SELECT）"},
                        },
                        "required": ["sql"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "run_python",
                    "description": "执行 Python 代码分析查询结果。支持 math, json, statistics, numpy, pandas。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "code": {"type": "string", "description": "要执行的 Python 代码"},
                        },
                        "required": ["code"],
                    },
                },
            },
        ]

    async def _run_loop(
        self,
        task_prompt: str,
        tools: list[ToolDef],
        sandbox: Sandbox,
        max_steps: int,
    ) -> AgentTrace:
        """执行数据分析循环。"""
        start = time.time()
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": task_prompt},
        ]

        # 合并外部工具和内置工具
        openai_tools = self._builtin_tools + [self._to_openai_tool(t) for t in tools]

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
                        "content": json.dumps(result, ensure_ascii=False, default=str),
                    }
                )

        raise AgentStepLimitError(f"DataAnalyst 超过最大步数 {max_steps}")

    @staticmethod
    def _to_openai_tool(tool_def: ToolDef) -> dict:
        """将 ToolDef 转为 OpenAI Function Calling 格式。"""
        return {
            "type": "function",
            "function": {
                "name": tool_def.name,
                "description": tool_def.description,
                "parameters": tool_def.parameters,
            },
        }

    @staticmethod
    def _parse_args(args_str: str | None) -> dict:
        """解析工具调用参数。"""
        if not args_str:
            return {}
        try:
            return json.loads(args_str)
        except json.JSONDecodeError:
            return {}

    @staticmethod
    def _extract_tokens(resp: Any) -> int:
        """从 OpenAI 响应中提取 token 使用量。"""
        try:
            return resp.usage.total_tokens if resp.usage else 0
        except (AttributeError, TypeError):
            return 0
