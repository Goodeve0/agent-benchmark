"""执行轨迹相关数据模型。

对应 docs/API_SPEC.md 第1.4-1.5节。
"""

from __future__ import annotations

import time
from typing import Any, Literal

from pydantic import BaseModel, Field

ActionType = Literal["tool_call", "response", "thinking"]


class AgentAction(BaseModel):
    """Agent 的一个动作。

    Attributes:
        step: 步骤序号，从 1 开始。
        action_type: 动作类型，tool_call / response / thinking。
        tool_name: 工具名称，action_type=tool_call 时必填。
        parameters: 工具调用参数。
        result: 工具返回结果。
        content: 文本内容（思考或回复）。
        timestamp: Unix 时间戳。
    """

    step: int
    action_type: ActionType
    tool_name: str | None = None
    parameters: dict[str, Any] | None = None
    result: Any | None = None
    content: str | None = None
    timestamp: float = Field(default_factory=time.time)


class AgentTrace(BaseModel):
    """Agent 执行一次任务的完整轨迹。

    Attributes:
        task_id: 对应的任务 ID。
        actions: 按时间排序的动作列表。
        total_tokens: 总 token 消耗。
        total_steps: 总步骤数。
        final_response: Agent 的最终文本回复。
        execution_time: 执行耗时（秒）。
        success: 是否在步数/超时限制内完成。
        error: 错误信息，正常完成时为 None。
        metadata: 附加元数据（如审计日志 audit_log）。
    """

    task_id: str
    actions: list[AgentAction] = Field(default_factory=list)
    total_tokens: int = 0
    total_steps: int = 0
    final_response: str = ""
    execution_time: float = 0.0
    success: bool = True
    error: str | None = None
    metadata: dict[str, Any] | None = Field(default=None)

    def tool_calls(self) -> list[AgentAction]:
        """返回所有工具调用动作。"""
        return [a for a in self.actions if a.action_type == "tool_call"]

    def called_tool_names(self) -> list[str]:
        """按调用顺序返回所有被调用的工具名。"""
        return [a.tool_name for a in self.tool_calls() if a.tool_name is not None]
