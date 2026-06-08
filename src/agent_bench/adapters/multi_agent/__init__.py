"""多 Agent 协作适配器。

支持三种经典多 Agent 拓扑：
1. ManagerWorkerAdapter: Manager 分解任务，Workers 并行执行，Manager 汇总
2. DebateAdapter: 正方 vs 反方辩论，裁判裁决
3. PipelineAdapter: 流水线式顺序处理

每种拓扑都继承自 MultiAgentAdapter 基类，基类提供：
- Agent 管理（注册、获取、通信）
- 共享 Sandbox
- 统一的 AgentTrace 构建
- 协作过程中的审计日志
"""

from agent_bench.adapters.multi_agent.base import MultiAgentAdapter, AgentRole
from agent_bench.adapters.multi_agent.manager_worker import ManagerWorkerAdapter
from agent_bench.adapters.multi_agent.debate import DebateAdapter
from agent_bench.adapters.multi_agent.pipeline import PipelineAdapter

__all__ = [
    "AgentRole",
    "DebateAdapter",
    "ManagerWorkerAdapter",
    "MultiAgentAdapter",
    "PipelineAdapter",
    "get_multi_agent_adapter",
]


def get_multi_agent_adapter(topology: str, **kwargs) -> MultiAgentAdapter:
    """根据拓扑类型创建多 Agent 适配器。

    Args:
        topology: "manager_worker" | "debate" | "pipeline"
        **kwargs: 构造参数。

    Returns:
        MultiAgentAdapter 实例。

    Raises:
        ValueError: 未知的拓扑类型。
    """
    if topology == "manager_worker":
        return ManagerWorkerAdapter(**kwargs)
    if topology == "debate":
        return DebateAdapter(**kwargs)
    if topology == "pipeline":
        return PipelineAdapter(**kwargs)
    raise ValueError(f"未知的多 Agent 拓扑: {topology}（可选: manager_worker, debate, pipeline）")
