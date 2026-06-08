"""LangGraph 节点定义。

每个节点是一个函数，接收 EvalState 并返回状态更新字典。
节点职责单一，通过 state 传递数据。

节点列表：
- load_tasks_node: 加载任务规格
- pick_task_node: 选取下一个待处理任务
- single_turn_node: 执行单轮评测
- multi_turn_node: 执行多轮对话评测
- score_node: 对执行轨迹评分
- collect_node: 收集当前任务结果
- report_node: 生成最终报告
"""

from __future__ import annotations

from typing import Any

from agent_bench.adapters import get_adapter
from agent_bench.adapters.user_agent import UserAgent
from agent_bench.graph.state import EvalState, TaskResult
from agent_bench.loader import TaskLoader
from agent_bench.models import AgentTrace
from agent_bench.runner.eval_runner import EvalRunner
from agent_bench.runner.multi_turn import MultiTurnRunner
from agent_bench.scorer.scorer import Scorer


def load_tasks_node(state: EvalState) -> dict[str, Any]:
    """加载任务规格。

    从 spec_dir 加载所有任务 YAML，可选按 dimension/task_id 过滤。
    """
    spec_dir = state.get("spec_dir", "specs")
    task_filter = state.get("task_filter")

    loader = TaskLoader(spec_dir)
    tasks = loader.load_all_tasks()

    # 过滤
    if task_filter:
        if "dimension" in task_filter:
            dim = task_filter["dimension"]
            tasks = [t for t in tasks if t.dimension == dim]
        if "task_id" in task_filter:
            tid = task_filter["task_id"]
            tasks = [t for t in tasks if t.task_id == tid]

    return {
        "tasks": tasks,
        "current_task_idx": 0,
        "results": [],
        "errors": [],
    }


def pick_task_node(state: EvalState) -> dict[str, Any]:
    """选取下一个待处理任务。"""
    tasks = state.get("tasks", [])
    idx = state.get("current_task_idx", 0)

    if idx < len(tasks):
        return {
            "current_task": tasks[idx],
            "current_traces": [],
            "current_reports": [],
        }
    return {
        "current_task": None,
    }


async def single_turn_node(state: EvalState) -> dict[str, Any]:
    """执行单轮评测。

    对当前任务执行 num_trials 次 trial，收集所有 AgentTrace。
    """
    task = state.get("current_task")
    if task is None:
        return {"errors": state.get("errors", []) + ["single_turn_node: 无当前任务"]}

    adapter_type = state.get("adapter_type", "mock")
    adapter_kwargs = state.get("adapter_kwargs", {})
    num_trials = state.get("num_trials", 1)
    max_steps = state.get("max_steps", 10)
    timeout = state.get("timeout", 60)

    adapter = get_adapter(adapter_type, **adapter_kwargs)
    runner = EvalRunner(
        adapter=adapter,
        max_steps=max_steps,
        timeout=timeout,
        num_trials=num_trials,
    )

    traces = await runner.run_task_trials(task)
    return {"current_traces": traces}


async def multi_turn_node(state: EvalState) -> dict[str, Any]:
    """执行多轮对话评测。

    使用 UserAgent 模拟用户，与被测 Agent 进行多轮交互。
    """
    task = state.get("current_task")
    if task is None:
        return {"errors": state.get("errors", []) + ["multi_turn_node: 无当前任务"]}

    adapter_type = state.get("adapter_type", "mock")
    adapter_kwargs = state.get("adapter_kwargs", {})
    num_trials = state.get("num_trials", 1)
    max_steps = state.get("max_steps", 10)
    timeout = state.get("timeout", 60)
    user_agent_mock = state.get("user_agent_mock", True)

    adapter = get_adapter(adapter_type, **adapter_kwargs)

    traces: list[AgentTrace] = []
    for _ in range(num_trials):
        user_agent = UserAgent.from_task_config(
            task_prompt=task.prompt,
            config=task.user_agent,
            mock_mode=user_agent_mock,
        )
        mt_runner = MultiTurnRunner(
            adapter=adapter,
            user_agent=user_agent,
            max_steps_per_turn=max_steps,
            timeout_per_turn=timeout,
        )
        trace = await mt_runner.run(task)
        traces.append(trace)

    return {"current_traces": traces}


async def score_node(state: EvalState) -> dict[str, Any]:
    """对执行轨迹评分。

    使用 Scorer 对当前任务的所有 traces 进行评分。
    支持规则引擎 + LLM Judge + 自定义 Grader。
    """
    task = state.get("current_task")
    traces = state.get("current_traces", [])
    if task is None or not traces:
        return {"errors": state.get("errors", []) + ["score_node: 无任务或轨迹"]}

    spec_dir = state.get("spec_dir", "specs")
    judge_enabled = state.get("judge_enabled", False)
    judge_model = state.get("judge_model", "gpt-4o")
    judge_mock = state.get("judge_mock", True)

    # 构建 LLM Judge（如果启用）
    llm_judge = None
    if judge_enabled and task.has_judge_rubric:
        from agent_bench.scorer.llm_judge import LLMJudge
        llm_judge = LLMJudge(model=judge_model, mock_mode=judge_mock)

    scorer = Scorer(llm_judge=llm_judge, spec_dir=spec_dir)

    reports = []
    for trace in traces:
        report = await scorer.score_task(trace, task)
        reports.append(report)

    return {"current_reports": reports}


def collect_node(state: EvalState) -> dict[str, Any]:
    """收集当前任务结果，推进到下一个任务。"""
    task = state.get("current_task")
    traces = state.get("current_traces", [])
    reports = state.get("current_reports", [])
    results = list(state.get("results", []))
    idx = state.get("current_task_idx", 0)

    if task is not None:
        results.append(TaskResult(
            task=task,
            traces=traces,
            reports=reports,
        ))

    return {
        "results": results,
        "current_task_idx": idx + 1,
    }


def report_node(state: EvalState) -> dict[str, Any]:
    """生成最终汇总报告。"""
    results = state.get("results", [])
    errors = state.get("errors", [])

    total_tasks = len(results)
    total_passed = 0
    total_score = 0.0
    total_max_score = 0.0
    task_summaries = []

    for r in results:
        task = r["task"]
        reports = r["reports"]

        if reports:
            # 取最佳报告
            best = max(reports, key=lambda rp: rp.percentage)
            passed = best.passed
            if passed:
                total_passed += 1
            total_score += best.total_score
            total_max_score += best.max_score

            task_summaries.append({
                "task_id": task.task_id,
                "dimension": task.dimension,
                "mode": task.mode,
                "score": best.total_score,
                "max_score": best.max_score,
                "percentage": best.percentage,
                "passed": passed,
                "num_trials": len(reports),
            })

    summary = {
        "total_tasks": total_tasks,
        "total_passed": total_passed,
        "pass_rate": total_passed / total_tasks if total_tasks > 0 else 0.0,
        "total_score": total_score,
        "total_max_score": total_max_score,
        "overall_percentage": (
            total_score / total_max_score * 100 if total_max_score > 0 else 0.0
        ),
        "task_summaries": task_summaries,
        "errors": errors,
    }

    return {"summary": summary}


# ------------------------------------------------------------------ #
# 路由函数（条件边）
# ------------------------------------------------------------------ #

def route_task_mode(state: EvalState) -> str:
    """根据当前任务模式路由到不同的执行节点。

    Returns:
        "single_turn" | "multi_turn" | "done"
    """
    task = state.get("current_task")
    if task is None:
        return "done"
    if task.is_multi_turn:
        return "multi_turn"
    return "single_turn"


def should_continue(state: EvalState) -> str:
    """判断是否还有待处理的任务。

    Returns:
        "continue" | "finish"
    """
    tasks = state.get("tasks", [])
    idx = state.get("current_task_idx", 0)
    if idx < len(tasks):
        return "continue"
    return "finish"
