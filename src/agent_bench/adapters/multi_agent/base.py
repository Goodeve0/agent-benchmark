"""多 Agent 协作适配器基类。

定义多 Agent 协作的通用抽象：
- AgentRole: Agent 角色定义
- MultiAgentAdapter: 多 Agent 适配器基类

设计要点：
- 每个 Agent 都是独立的 BaseAdapter 实例，通过 role 区分职责
- Agent 间通过消息传递协作（Message）
- 共享同一个 Sandbox（工具状态跨 Agent 保持）
- 最终合并所有 Agent 的执行轨迹为统一的 AgentTrace
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from agent_bench.adapters.base import BaseAdapter
from agent_bench.models import AgentAction, AgentTrace, ToolDef
from agent_bench.sandbox.sandbox import Sandbox


class TopologyType(str, Enum):
    """多 Agent 拓扑类型。"""
    MANAGER_WORKER = "manager_worker"
    DEBATE = "debate"
    PIPELINE = "pipeline"


@dataclass
class AgentRole:
    """Agent 角色定义。

    Attributes:
        name: 角色名称（如 manager, worker_1, affirmative, judge）。
        adapter: 对应的适配器实例。
        description: 角色描述（用于系统 prompt）。
    """
    name: str
    adapter: BaseAdapter
    description: str = ""


@dataclass
class Message:
    """Agent 间的消息。

    Attributes:
        sender: 发送者角色名。
        receiver: 接收者角色名（空字符串表示广播）。
        content: 消息内容。
        metadata: 附加元数据。
        timestamp: 消息时间戳。
    """
    sender: str
    receiver: str
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


class MultiAgentAdapter(BaseAdapter, ABC):
    """多 Agent 协作适配器基类。

    子类需要实现 run_task() 方法，定义具体的协作流程。
    基类提供：
    - Agent 注册和管理
    - 消息传递
    - 统一的 AgentTrace 构建
    """

    def __init__(
        self,
        roles: list[AgentRole],
        name: str = "multi-agent",
        topology: TopologyType = TopologyType.MANAGER_WORKER,
    ) -> None:
        """
        Args:
            roles: Agent 角色列表。
            name: 适配器名称。
            topology: 拓扑类型。
        """
        self._roles = {role.name: role for role in roles}
        self._name = name
        self._topology = topology
        self._message_history: list[Message] = []

    @property
    def roles(self) -> dict[str, AgentRole]:
        """所有注册的角色。"""
        return self._roles

    @property
    def message_history(self) -> list[Message]:
        """消息传递历史。"""
        return list(self._message_history)

    def get_role(self, name: str) -> AgentRole:
        """获取指定角色。"""
        if name not in self._roles:
            raise KeyError(f"角色 {name} 未注册，可用: {list(self._roles.keys())}")
        return self._roles[name]

    def send_message(self, message: Message) -> None:
        """发送消息并记录到历史。"""
        self._message_history.append(message)

    def get_messages_for(self, role_name: str) -> list[Message]:
        """获取发给指定角色的所有消息。"""
        return [
            m for m in self._message_history
            if m.receiver == role_name or m.receiver == ""
        ]

    def get_agent_info(self) -> dict:
        return {
            "name": self._name,
            "model": "multi-agent",
            "framework": f"multi_agent_{self._topology.value}",
            "roles": {name: role.description for name, role in self._roles.items()},
        }

    def build_multi_agent_trace(
        self,
        task_id: str,
        all_actions: list[AgentAction],
        total_tokens: int,
        final_response: str,
        execution_time: float,
        success: bool = True,
        error: str | None = None,
    ) -> AgentTrace:
        """构建多 Agent 协作的统一 AgentTrace。

        在 metadata 中保存：
        - topology: 拓扑类型
        - roles: 参与角色
        - messages: 消息传递历史
        - per_agent_steps: 每个 Agent 的步数统计
        """
        # 统计每个 Agent 的步数
        per_agent_steps: dict[str, int] = {}
        for action in all_actions:
            agent_name = action.metadata.get("agent", "unknown") if action.metadata else "unknown"
            per_agent_steps[agent_name] = per_agent_steps.get(agent_name, 0) + 1

        return AgentTrace(
            task_id=task_id,
            actions=all_actions,
            total_tokens=total_tokens,
            total_steps=len(all_actions),
            final_response=final_response,
            execution_time=round(execution_time, 4),
            success=success,
            error=error,
            metadata={
                "topology": self._topology.value,
                "roles": list(self._roles.keys()),
                "messages": [
                    {
                        "sender": m.sender,
                        "receiver": m.receiver,
                        "content": m.content[:500],
                        "timestamp": m.timestamp,
                    }
                    for m in self._message_history
                ],
                "per_agent_steps": per_agent_steps,
                "multi_agent": True,
            },
        )
