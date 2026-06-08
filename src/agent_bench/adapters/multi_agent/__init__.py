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

from agent_bench.adapters.multi_agent.base import AgentRole, MultiAgentAdapter
from agent_bench.adapters.multi_agent.debate import DebateAdapter
from agent_bench.adapters.multi_agent.manager_worker import ManagerWorkerAdapter
from agent_bench.adapters.multi_agent.pipeline import PipelineAdapter

__all__ = [
    "AgentRole",
    "DebateAdapter",
    "ManagerWorkerAdapter",
    "MultiAgentAdapter",
    "PipelineAdapter",
    "get_multi_agent_adapter",
]


def _make_adapter(model: str = "gpt-4o"):
    """创建一个基础适配器实例（用于多 Agent 内部角色）。

    优先使用 RawAPIAdapter（真实 LLM 调用），若 openai 未安装则降级到 MockAdapter。
    """
    try:
        from agent_bench.adapters.raw_api_adapter import RawAPIAdapter
        return RawAPIAdapter(model=model)
    except ImportError:
        from agent_bench.adapters.mock_adapter import MockAdapter
        return MockAdapter()


def get_multi_agent_adapter(topology: str, **kwargs) -> MultiAgentAdapter:
    """根据拓扑类型创建多 Agent 适配器。

    当 kwargs 中包含 ``model`` 时，会自动为每个角色创建对应的适配器实例。
    也可以显式传入已构造好的适配器（manager/workers/affirmative/negative/judge/stages）。

    Args:
        topology: "manager_worker" | "debate" | "pipeline"
        **kwargs: 构造参数。支持 ``model`` 键用于自动创建内部适配器。

    Returns:
        MultiAgentAdapter 实例。

    Raises:
        ValueError: 未知的拓扑类型。
    """
    model = kwargs.pop("model", "gpt-4o")

    if topology == "manager_worker":
        manager = kwargs.pop("manager", None) or _make_adapter(model)
        workers = kwargs.pop("workers", None) or [_make_adapter(model) for _ in range(3)]
        return ManagerWorkerAdapter(manager=manager, workers=workers, **kwargs)

    if topology == "debate":
        affirmative = kwargs.pop("affirmative", None) or _make_adapter(model)
        negative = kwargs.pop("negative", None) or _make_adapter(model)
        judge = kwargs.pop("judge", None) or _make_adapter(model)
        return DebateAdapter(
            affirmative=affirmative, negative=negative, judge=judge, **kwargs
        )

    if topology == "pipeline":
        stages = kwargs.pop("stages", None)
        if stages is None:
            # 默认 3 阶段流水线: researcher → writer → reviewer
            stages = [
                ("researcher", _make_adapter(model), "负责信息搜集和整理"),
                ("writer", _make_adapter(model), "负责撰写初稿"),
                ("reviewer", _make_adapter(model), "负责审核修改"),
            ]
        return PipelineAdapter(stages=stages, **kwargs)

    raise ValueError(f"未知的多 Agent 拓扑: {topology}（可选: manager_worker, debate, pipeline）")
