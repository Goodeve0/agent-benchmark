"""评测执行器。

对应 docs/API_SPEC.md 第2.4节。

v2: 支持多 trial 执行 + asyncio.gather 并行调度 + Semaphore 并发控制。
v3: 自动识别多轮任务，委托 MultiTurnRunner 执行。

职责：编排执行流程；超时控制；步数上限；错误处理；进度展示；多 trial 支持。
不做：具体评分规则；Agent 内部实现。
"""

from __future__ import annotations

import asyncio

from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)

from agent_bench.adapters.base import BaseAdapter
from agent_bench.adapters.user_agent import UserAgent
from agent_bench.exceptions import AgentStepLimitError, AgentTimeoutError
from agent_bench.models import AgentTrace, Task
from agent_bench.sandbox import Sandbox


class EvalRunner:
    """评测执行器，支持并行 + 多 trial + 多轮对话。"""

    def __init__(
        self,
        adapter: BaseAdapter,
        max_steps: int = 10,
        timeout: int = 60,
        retry_on_error: bool = False,
        num_trials: int = 1,
        max_parallel: int = 4,
        user_agent_mock: bool = True,
        user_agent_model: str = "gpt-4o",
    ) -> None:
        """
        Args:
            adapter: Agent 适配器实例。
            max_steps: 单任务最大步数。
            timeout: 单任务超时秒数。
            retry_on_error: 出错时是否重试一次。
            num_trials: 每个任务执行的 trial 次数（Pass^k 需要 k >= 3）。
            max_parallel: 最大并行任务数。
            user_agent_mock: 多轮对话中 UserAgent 是否使用 mock 模式。
            user_agent_model: 多轮对话中 UserAgent 使用的 LLM 模型。
        """
        self.adapter = adapter
        self.max_steps = max_steps
        self.timeout = timeout
        self.retry_on_error = retry_on_error
        self.num_trials = num_trials
        self.max_parallel = max_parallel
        self.user_agent_mock = user_agent_mock
        self.user_agent_model = user_agent_model

    # ------------------------------------------------------------------ #
    # 单次执行
    # ------------------------------------------------------------------ #

    async def run_single_task(self, task: Task) -> AgentTrace:
        """运行单个评测任务（单次 trial）。

        流程:
        1. 自动识别多轮任务，委托 MultiTurnRunner。
        2. 单轮任务：创建独立 Sandbox -> adapter.run_task()。
        3. 捕获超时/步数超限/异常，写入 trace.error。
        4. 回填 task_id + 审计日志。

        Returns:
            AgentTrace（无论成功与否都返回，失败时 success=False）。
        """
        trace = await self._attempt(task)
        if trace.error is not None and self.retry_on_error:
            retry_trace = await self._attempt(task)
            if retry_trace.error is None:
                return retry_trace
        return trace

    # ------------------------------------------------------------------ #
    # 多 trial 执行（单任务）
    # ------------------------------------------------------------------ #

    async def run_task_trials(self, task: Task) -> list[AgentTrace]:
        """对同一任务执行 num_trials 次 trial。

        Args:
            task: 评测任务。

        Returns:
            N 条 AgentTrace（每次 trial 独立的 Sandbox）。
        """
        traces: list[AgentTrace] = []
        for _ in range(self.num_trials):
            trace = await self.run_single_task(task)
            traces.append(trace)
        return traces

    # ------------------------------------------------------------------ #
    # 批量执行（串行，向后兼容）
    # ------------------------------------------------------------------ #

    async def run_evaluation(self, tasks: list[Task]) -> list[AgentTrace]:
        """串行运行一批评测任务（单 trial），带进度展示。

        某个任务失败不会中断整体流程。向后兼容旧接口。
        """
        traces: list[AgentTrace] = []
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("{task.completed}/{task.total}"),
            TimeElapsedColumn(),
        ) as progress:
            bar = progress.add_task("评测进行中", total=len(tasks))
            for task in tasks:
                progress.update(bar, description=f"评测 {task.task_id}")
                trace = await self.run_single_task(task)
                traces.append(trace)
                progress.advance(bar)
        return traces

    # ------------------------------------------------------------------ #
    # 并行 + 多 trial 批量执行
    # ------------------------------------------------------------------ #

    async def run_evaluation_parallel(
        self,
        tasks: list[Task],
    ) -> dict[str, list[AgentTrace]]:
        """并行运行评测任务，每个任务执行 num_trials 次。

        使用 asyncio.Semaphore 控制并发数。

        Args:
            tasks: 评测任务列表。

        Returns:
            {task_id: [AgentTrace * num_trials]} 映射。
        """
        semaphore = asyncio.Semaphore(self.max_parallel)
        results: dict[str, list[AgentTrace]] = {}

        total_work = len(tasks) * self.num_trials

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("{task.completed}/{task.total}"),
            TimeElapsedColumn(),
        ) as progress:
            bar = progress.add_task(
                f"评测进行中 (trials={self.num_trials}, parallel={self.max_parallel})",
                total=total_work,
            )

            async def _run_one_trial(task: Task, trial_idx: int) -> tuple[str, int, AgentTrace]:
                async with semaphore:
                    progress.update(
                        bar,
                        description=f"评测 {task.task_id} trial#{trial_idx}",
                    )
                    trace = await self.run_single_task(task)
                    progress.advance(bar)
                    return task.task_id, trial_idx, trace

            # 创建所有 trial 的协程
            coros = []
            for task in tasks:
                for trial_idx in range(1, self.num_trials + 1):
                    coros.append(_run_one_trial(task, trial_idx))

            # 并行执行
            completed = await asyncio.gather(*coros)

            # 按 task_id 分组
            for task_id, _, trace in completed:
                if task_id not in results:
                    results[task_id] = []
                results[task_id].append(trace)

        return results

    # ------------------------------------------------------------------ #
    # 内部方法
    # ------------------------------------------------------------------ #

    async def _attempt(self, task: Task) -> AgentTrace:
        """执行一次任务尝试，捕获所有异常。

        自动识别多轮任务，委托 MultiTurnRunner 执行。
        """
        # 多轮对话任务：委托 MultiTurnRunner
        if task.is_multi_turn and task.user_agent is not None:
            return await self._attempt_multi_turn(task)

        # 单轮任务：原有逻辑
        sandbox = Sandbox(task.mock_apis)
        try:
            trace = await self.adapter.run_task(
                task_prompt=task.prompt,
                tools=task.tools,
                sandbox=sandbox,
                max_steps=self.max_steps,
                timeout=self.timeout,
                task_id=task.task_id,
            )
            # 将沙箱审计日志注入 trace.metadata
            audit_log = sandbox.get_audit_log(freeze=True)
            if trace.metadata is None:
                trace.metadata = {}
            trace.metadata["audit_log"] = audit_log
            return trace
        except AgentTimeoutError as e:
            return self._failed_trace(task, f"超时: {e}")
        except AgentStepLimitError as e:
            return self._failed_trace(task, f"超出步数: {e}")
        except Exception as e:  # noqa: BLE001 - 兜底，单任务失败不影响整体
            return self._failed_trace(task, f"执行异常: {e}")

    async def _attempt_multi_turn(self, task: Task) -> AgentTrace:
        """执行一次多轮对话任务尝试。"""
        from agent_bench.runner.multi_turn import MultiTurnRunner

        try:
            user_agent = UserAgent.from_task_config(
                task_prompt=task.prompt,
                config=task.user_agent,
                mock_mode=self.user_agent_mock,
                model=self.user_agent_model,
            )
            mt_runner = MultiTurnRunner(
                adapter=self.adapter,
                user_agent=user_agent,
                max_steps_per_turn=self.max_steps,
                timeout_per_turn=self.timeout,
            )
            return await mt_runner.run(task)
        except Exception as e:  # noqa: BLE001
            return self._failed_trace(task, f"多轮对话执行异常: {e}")

    @staticmethod
    def _failed_trace(task: Task, error: str) -> AgentTrace:
        """构造一个失败的占位轨迹。"""
        return AgentTrace(
            task_id=task.task_id,
            actions=[],
            total_tokens=0,
            total_steps=0,
            final_response="",
            execution_time=0.0,
            success=False,
            error=error,
        )
