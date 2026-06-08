"""AgentBench Trace 上报 SDK。

轻量级 Agent 运行数据采集与上报，支持:
- 上下文管理器 (with client.trace())
- 装饰器 (@trace_action)
- OpenAI / LangChain 回调集成
- 异步批量上报，不阻塞主流程
- 链式哈希防篡改
"""

from agentbench_sdk.client import TraceClient
from agentbench_sdk.context import trace_context

__all__ = ["TraceClient", "trace_context"]
