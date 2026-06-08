"""Mock 适配器：无需真实 LLM / API Key 即可运行。

用途：
1. 现场演示整条评测链路（面试时无需联网/密钥即可跑通）。
2. 作为基线对照（baseline）。
3. 支持端到端测试。

行为可通过 behavior 参数配置:
- "good": 依次调用全部可用工具一次，并基于结果给出最终回复（较高分基线）。
- "lazy": 不调用任何工具，直接给出回复（低分基线，用于对照）。
"""

from __future__ import annotations

import time
from typing import Any, Literal

from agent_bench.adapters.base import BaseAdapter
from agent_bench.models import AgentAction, AgentTrace, ToolDef
from agent_bench.sandbox import Sandbox

Behavior = Literal["good", "lazy"]


class MockAdapter(BaseAdapter):
    """确定性 Mock Agent，不依赖任何外部服务。"""

    def __init__(
        self,
        name: str = "mock-agent",
        model: str = "mock-model",
        behavior: Behavior = "good",
        tokens_per_step: int = 50,
    ) -> None:
        """
        Args:
            name: Agent 名称。
            model: 模型标识。
            behavior: 行为模式，good / lazy。
            tokens_per_step: 每步模拟消耗的 token 数。
        """
        self.name = name
        self.model = model
        self.behavior = behavior
        self.tokens_per_step = tokens_per_step

    async def run_task(
        self,
        task_prompt: str,
        tools: list[ToolDef],
        sandbox: Sandbox,
        max_steps: int = 10,
        timeout: int = 60,
    ) -> AgentTrace:
        start = time.time()
        actions: list[AgentAction] = []
        step = 0

        if self.behavior == "good":
            # 依次调用每个工具一次（不超过 max_steps - 1，留一步给最终回复）
            for tool in tools:
                if step >= max_steps - 1:
                    break
                step += 1
                params = self._default_params(tool)
                result = await sandbox.execute_tool(tool.name, params)
                actions.append(
                    AgentAction(
                        step=step,
                        action_type="tool_call",
                        tool_name=tool.name,
                        parameters=params,
                        result=result,
                    )
                )

        # 最终回复
        step += 1
        final = self._build_response(task_prompt, actions)
        actions.append(
            AgentAction(
                step=step,
                action_type="response",
                content=final,
            )
        )

        return AgentTrace(
            task_id="",  # 由 EvalRunner 回填
            actions=actions,
            total_tokens=step * self.tokens_per_step,
            total_steps=step,
            final_response=final,
            execution_time=round(time.time() - start, 4),
            success=True,
            error=None,
        )

    def get_agent_info(self) -> dict:
        return {
            "name": self.name,
            "model": self.model,
            "framework": f"mock({self.behavior})",
        }

    # ---- 内部方法 ----

    @staticmethod
    def _default_params(tool: ToolDef) -> dict[str, Any]:
        """根据工具的参数 Schema 生成简单的默认参数。"""
        params: dict[str, Any] = {}
        properties = tool.parameters.get("properties", {})
        for key, spec in properties.items():
            if "default" in spec:
                params[key] = spec["default"]
            elif "example" in spec:
                params[key] = spec["example"]
            else:
                params[key] = _placeholder_for_type(spec.get("type", "string"))
        return params

    @staticmethod
    def _build_response(task_prompt: str, actions: list[AgentAction]) -> str:
        """基于工具结果构造最终回复。"""
        tool_results = [
            f"{a.tool_name}={a.result}" for a in actions if a.action_type == "tool_call"
        ]
        if tool_results:
            return f"已完成任务。依据工具结果: {'; '.join(tool_results)}"
        return "已完成任务（未使用工具）。"


def _placeholder_for_type(json_type: str) -> Any:
    """为不同 JSON 类型提供占位默认值。"""
    return {
        "string": "test",
        "integer": 1,
        "number": 1.0,
        "boolean": True,
        "array": [],
        "object": {},
    }.get(json_type, "test")
