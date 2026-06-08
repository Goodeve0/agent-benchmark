"""Agent 适配器统一导出。

RawAPIAdapter / DataAnalystAdapter 依赖可选的 openai 包，采用懒加载，
未安装时不影响其他适配器使用。
"""

from agent_bench.adapters.base import BaseAdapter
from agent_bench.adapters.mock_adapter import MockAdapter
from agent_bench.adapters.user_agent import ConversationTurn, UserAgent

__all__ = [
    "BaseAdapter",
    "ConversationTurn",
    "DataAnalystAdapter",
    "MockAdapter",
    "RawAPIAdapter",
    "UserAgent",
    "get_adapter",
]


def __getattr__(name: str):
    if name == "RawAPIAdapter":
        from agent_bench.adapters.raw_api_adapter import RawAPIAdapter
        return RawAPIAdapter
    if name == "DataAnalystAdapter":
        from agent_bench.adapters.data_analyst_adapter import DataAnalystAdapter
        return DataAnalystAdapter
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def get_adapter(adapter_type: str, **kwargs):
    """根据类型名创建适配器实例。

    Args:
        adapter_type: "mock" | "raw_api" | "data_analyst"
        **kwargs: 传给对应适配器构造函数的参数。

    Returns:
        BaseAdapter 实例。

    Raises:
        ValueError: 未知的适配器类型。
    """
    if adapter_type == "mock":
        return MockAdapter(**kwargs)
    if adapter_type == "raw_api":
        from agent_bench.adapters.raw_api_adapter import RawAPIAdapter
        return RawAPIAdapter(**kwargs)
    if adapter_type == "data_analyst":
        from agent_bench.adapters.data_analyst_adapter import DataAnalystAdapter
        return DataAnalystAdapter(**kwargs)
    raise ValueError(f"未知的适配器类型: {adapter_type}（可选: mock, raw_api, data_analyst）")
