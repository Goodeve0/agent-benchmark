"""LangGraph 状态定义。

EvalState 是整个评测图的共享状态，所有节点通过读写 state 来传递数据。
使用 TypedDict 定义，兼容 LangGraph 的 StateGraph。

状态流转：
  load_tasks → (for each task) → route_task
    → single_turn_node → score_node → report_node
    → multi_turn_node → score_node → report_node
"""

from __future__ import annotations

from typing import Any, TypedDict

from agent_bench.models.score import ScoreReport
from agent_bench.models.task import Task
from agent_bench.models.trace import AgentTrace


class TaskResult(TypedDict):
    """单个任务的执行结果。"""

    task: Task
    traces: list[AgentTrace]
    reports: list[ScoreReport]


class EvalState(TypedDict, total=False):
    """评测图的全局状态。

    Attributes:
        # ---- 输入 ----
        spec_dir: 任务规格目录路径。
        adapter_type: Agent 适配器类型（mock / raw_api）。
        adapter_kwargs: 适配器构造参数。
        num_trials: 每个任务的 trial 次数。
        max_steps: 单任务最大步数。
        timeout: 单任务超时秒数。
        max_parallel: 最大并行数。
        task_filter: 任务过滤条件（dimension / task_id）。
        judge_enabled: 是否启用 LLM Judge。
        judge_model: LLM Judge 模型名。
        judge_mock: LLM Judge 是否使用 mock 模式。
        user_agent_mock: 多轮对话 UserAgent 是否使用 mock 模式。

        # ---- 中间状态 ----
        tasks: 加载后的任务列表。
        current_task_idx: 当前处理的任务索引。
        current_task: 当前正在处理的任务。
        current_traces: 当前任务的执行轨迹列表。
        current_reports: 当前任务的评分报告列表。
        conversation_history: 多轮对话历史（仅多轮任务）。

        # ---- 输出 ----
        results: 所有任务的结果列表。
        summary: 最终汇总信息。
        errors: 执行过程中的错误列表。
    """

    # 输入
    spec_dir: str
    adapter_type: str
    adapter_kwargs: dict[str, Any]
    num_trials: int
    max_steps: int
    timeout: int
    max_parallel: int
    task_filter: dict[str, str] | None
    judge_enabled: bool
    judge_model: str
    judge_mock: bool
    user_agent_mock: bool

    # 中间状态
    tasks: list[Task]
    current_task_idx: int
    current_task: Task | None
    current_traces: list[AgentTrace]
    current_reports: list[ScoreReport]
    conversation_history: list[dict[str, str]]

    # 输出
    results: list[TaskResult]
    summary: dict[str, Any]
    errors: list[str]
