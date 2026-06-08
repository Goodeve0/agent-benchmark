"""项目统一异常定义。

对应 docs/API_SPEC.md 第5节。除此之外不得新增异常类型。
"""


class AgentBenchError(Exception):
    """所有 AgentBench 异常的基类。"""


class TaskLoadError(AgentBenchError):
    """任务加载失败（YAML 格式错误 / 必填字段缺失等）。"""


class TaskNotFoundError(AgentBenchError):
    """指定的 task_id 不存在。"""


class AgentTimeoutError(AgentBenchError):
    """Agent 执行超时。"""


class AgentStepLimitError(AgentBenchError):
    """Agent 超出最大步数限制。"""


class SandboxError(AgentBenchError):
    """沙箱执行错误。"""


class ToolNotFoundError(SandboxError):
    """工具未在沙箱中注册。"""


class BudgetExceededError(SandboxError):
    """工具调用次数超过预算上限。"""


class ToolExecutionError(SandboxError):
    """工具执行出错（真实 API 调用失败）。"""


class MultiAgentError(AgentBenchError):
    """多 Agent 协作相关错误。"""


class ScoringError(AgentBenchError):
    """评分错误。"""
