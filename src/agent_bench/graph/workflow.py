"""LangGraph 工作流组装。

将各节点组装为 StateGraph，定义边和条件路由。

图结构：
  START → load_tasks → pick_task → route_task_mode
    → single_turn → score → collect → should_continue
    → multi_turn  → score → collect → should_continue
      → continue: pick_task
      → finish: report → END

支持两种运行模式：
1. build_eval_graph(): 返回编译后的 CompiledGraph，可自行控制执行。
2. run_eval_graph(): 一键运行，返回最终状态。
"""

from __future__ import annotations

from typing import Any


def build_eval_graph(checkpointer: Any = None) -> Any:
    """构建评测工作流图。

    Args:
        checkpointer: LangGraph checkpointer 实例（可选，用于断点续跑）。

    Returns:
        编译后的 CompiledStateGraph。

    Raises:
        ImportError: 未安装 langgraph。
    """
    try:
        from langgraph.graph import END, START, StateGraph
    except ImportError as e:
        raise ImportError(
            "LangGraph 编排引擎需要安装 langgraph: "
            "pip install langgraph langchain-core"
        ) from e

    from agent_bench.graph.nodes import (
        collect_node,
        load_tasks_node,
        multi_turn_node,
        pick_task_node,
        report_node,
        route_task_mode,
        score_node,
        should_continue,
        single_turn_node,
    )
    from agent_bench.graph.state import EvalState

    # 构建图
    graph = StateGraph(EvalState)

    # 添加节点
    graph.add_node("load_tasks", load_tasks_node)
    graph.add_node("pick_task", pick_task_node)
    graph.add_node("single_turn", single_turn_node)
    graph.add_node("multi_turn", multi_turn_node)
    graph.add_node("score", score_node)
    graph.add_node("collect", collect_node)
    graph.add_node("report", report_node)

    # 定义边
    graph.add_edge(START, "load_tasks")
    graph.add_edge("load_tasks", "pick_task")

    # 条件路由：根据任务模式选择执行路径
    graph.add_conditional_edges(
        "pick_task",
        route_task_mode,
        {
            "single_turn": "single_turn",
            "multi_turn": "multi_turn",
            "done": "report",
        },
    )

    # 执行完成后都进入评分
    graph.add_edge("single_turn", "score")
    graph.add_edge("multi_turn", "score")

    # 评分后收集结果
    graph.add_edge("score", "collect")

    # 收集后判断是否继续
    graph.add_conditional_edges(
        "collect",
        should_continue,
        {
            "continue": "pick_task",
            "finish": "report",
        },
    )

    # 报告后结束
    graph.add_edge("report", END)

    # 编译
    compile_kwargs: dict[str, Any] = {}
    if checkpointer is not None:
        compile_kwargs["checkpointer"] = checkpointer

    return graph.compile(**compile_kwargs)


async def run_eval_graph(
    spec_dir: str = "specs",
    adapter_type: str = "mock",
    adapter_kwargs: dict[str, Any] | None = None,
    num_trials: int = 1,
    max_steps: int = 10,
    timeout: int = 60,
    max_parallel: int = 4,
    task_filter: dict[str, str] | None = None,
    judge_enabled: bool = False,
    judge_model: str = "gpt-4o",
    judge_mock: bool = True,
    user_agent_mock: bool = True,
    checkpointer: Any = None,
    thread_id: str = "default",
) -> dict[str, Any]:
    """一键运行评测工作流。

    Args:
        spec_dir: 任务规格目录。
        adapter_type: Agent 适配器类型。
        adapter_kwargs: 适配器构造参数。
        num_trials: 每个任务的 trial 次数。
        max_steps: 单任务最大步数。
        timeout: 单任务超时秒数。
        max_parallel: 最大并行数。
        task_filter: 任务过滤条件。
        judge_enabled: 是否启用 LLM Judge。
        judge_model: LLM Judge 模型名。
        judge_mock: LLM Judge 是否使用 mock 模式。
        user_agent_mock: 多轮对话 UserAgent 是否使用 mock 模式。
        checkpointer: LangGraph checkpointer（可选）。
        thread_id: 线程 ID（用于 checkpoint）。

    Returns:
        最终状态字典（包含 summary）。
    """
    compiled = build_eval_graph(checkpointer=checkpointer)

    initial_state = {
        "spec_dir": spec_dir,
        "adapter_type": adapter_type,
        "adapter_kwargs": adapter_kwargs or {},
        "num_trials": num_trials,
        "max_steps": max_steps,
        "timeout": timeout,
        "max_parallel": max_parallel,
        "task_filter": task_filter,
        "judge_enabled": judge_enabled,
        "judge_model": judge_model,
        "judge_mock": judge_mock,
        "user_agent_mock": user_agent_mock,
    }

    config = {"configurable": {"thread_id": thread_id}}

    # 运行图
    final_state = await compiled.ainvoke(initial_state, config=config)
    return final_state
