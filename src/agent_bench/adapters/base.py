"""Agent 适配器基类。

对应 docs/API_SPEC.md 第2.2节。

所有适配器必须继承 BaseAdapter，将各自框架的执行过程统一转换为 AgentTrace。
适配器只负责"对接框架"，通用编排逻辑在 EvalRunner 中。
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from agent_bench.models import AgentTrace, ToolDef
from agent_bench.sandbox import Sandbox


class BaseAdapter(ABC):
    """Agent 适配器抽象基类。"""

    @abstractmethod
    async def run_task(
        self,
        task_prompt: str,
        tools: list[ToolDef],
        sandbox: Sandbox,
        max_steps: int = 10,
        timeout: int = 60,
    ) -> AgentTrace:
        """运行一个评测任务，返回执行轨迹。

        Args:
            task_prompt: 任务描述，直接传给 Agent。
            tools: 可用工具定义列表。
            sandbox: 沙箱实例，Agent 调用工具时必须通过 sandbox.execute_tool。
            max_steps: 最大步数限制。
            timeout: 超时秒数。

        Returns:
            AgentTrace: 完整执行轨迹。

        Raises:
            AgentTimeoutError: 执行超过 timeout 秒。
            AgentStepLimitError: 执行超过 max_steps 步。
        """
        ...

    @abstractmethod
    def get_agent_info(self) -> dict:
        """返回 Agent 元信息。

        Returns:
            {"name": str, "model": str, "framework": str}
        """
        ...
