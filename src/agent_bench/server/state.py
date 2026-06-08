"""服务端全局状态管理。

管理任务列表、评测运行状态、WebSocket 连接等。
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import WebSocket

from agent_bench.adapters import get_adapter
from agent_bench.loader import TaskLoader
from agent_bench.models import EvaluationResult, Task, TaskTrials
from agent_bench.runner import EvalRunner
from agent_bench.scorer import Scorer
from agent_bench.scorer.llm_judge import LLMJudge


class EvalRun:
    """单次评测运行的状态。"""

    def __init__(self, run_id: str, config: dict) -> None:
        self.run_id = run_id
        self.config = config
        self.status: str = "pending"  # pending | running | completed | failed | cancelled
        self.progress: float = 0.0
        self.current_task: str = ""
        self.completed_tasks: int = 0
        self.total_tasks: int = 0
        self.result: EvaluationResult | None = None
        self.error: str | None = None
        self.started_at: str = ""
        self.finished_at: str = ""
        self._task: asyncio.Task | None = None  # 后台 asyncio.Task

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "config": self.config,
            "status": self.status,
            "progress": self.progress,
            "current_task": self.current_task,
            "completed_tasks": self.completed_tasks,
            "total_tasks": self.total_tasks,
            "error": self.error,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "has_result": self.result is not None,
        }


class AppState:
    """应用全局状态。"""

    def __init__(self, spec_dir: str) -> None:
        self.spec_dir = spec_dir
        self.tasks: list[Task] = []
        self.runs: dict[str, EvalRun] = {}
        # 历史评测结果（排行榜用）
        self.history: list[dict] = []
        # WebSocket 连接池
        self.ws_connections: list[WebSocket] = []
        self._lock = asyncio.Lock()

    def load_tasks(self) -> None:
        """加载任务列表。加载失败时记录警告但不阻止服务器启动。"""
        try:
            loader = TaskLoader(self.spec_dir)
            self.tasks = loader.load_all_tasks()
        except Exception as e:  # noqa: BLE001
            import warnings
            warnings.warn(f"任务加载失败: {e}", stacklevel=2)
            self.tasks = []

    def get_task_ids(self) -> list[str]:
        return [t.task_id for t in self.tasks]

    def get_task_by_id(self, task_id: str) -> Task | None:
        for t in self.tasks:
            if t.task_id == task_id:
                return t
        return None

    def get_tasks_summary(self) -> list[dict]:
        """返回任务摘要列表（不含完整 rubric，减少传输量）。"""
        return [
            {
                "task_id": t.task_id,
                "dimension": t.dimension,
                "sub_dimension": t.sub_dimension,
                "difficulty": t.difficulty,
                "mode": t.mode,
                "prompt_preview": t.prompt[:80] + ("..." if len(t.prompt) > 80 else ""),
                "max_score": t.max_score,
                "has_judge_rubric": t.has_judge_rubric,
                "is_multi_turn": t.is_multi_turn,
                "num_tools": len(t.tools),
            }
            for t in self.tasks
        ]

    async def start_run(self, config: dict) -> str:
        """启动一次评测运行，返回 run_id。"""
        run_id = f"run_{uuid.uuid4().hex[:8]}"
        run = EvalRun(run_id=run_id, config=config)
        run.status = "running"
        run.started_at = datetime.now(timezone.utc).isoformat()
        run.total_tasks = len(self.tasks)
        run._task = asyncio.create_task(self._execute_run(run))
        self.runs[run_id] = run
        return run_id

    async def _execute_run(self, run: EvalRun) -> None:
        """在后台执行评测。"""
        try:
            config = run.config
            adapter_type = config.get("adapter_type", "mock")
            num_trials = config.get("num_trials", 1)
            max_parallel = config.get("max_parallel", 4)
            judge_mock = config.get("judge_mock", True)
            selected_tasks = config.get("tasks", [])

            # 过滤任务
            if selected_tasks:
                tasks = [t for t in self.tasks if t.task_id in selected_tasks]
            else:
                tasks = self.tasks

            run.total_tasks = len(tasks)
            if not tasks:
                run.status = "failed"
                run.error = "没有找到匹配的任务"
                await self._broadcast_progress(run)
                return

            # 创建 adapter
            adapter_kwargs = {}
            if adapter_type == "raw_api":
                adapter_kwargs["model"] = config.get("model", "gpt-4o")
            elif adapter_type == "data_analyst":
                adapter_kwargs["model"] = config.get("model", "gpt-4o")
            elif adapter_type == "multi_agent":
                from agent_bench.adapters.multi_agent import get_multi_agent_adapter
                topology = config.get("topology", "manager_worker")
                adapter = get_multi_agent_adapter(
                    topology, model=config.get("model", "gpt-4o")
                )
                # multi_agent 不走 get_adapter，直接跳过
                adapter_kwargs = None

            if adapter_kwargs is not None:
                adapter = get_adapter(adapter_type, **adapter_kwargs)

            # 创建 scorer
            llm_judge = None
            if not judge_mock:
                try:
                    llm_judge = LLMJudge(mock_mode=False)
                except Exception:
                    llm_judge = LLMJudge(mock_mode=True)
            else:
                llm_judge = LLMJudge(mock_mode=True)

            scorer = Scorer(llm_judge=llm_judge, spec_dir=self.spec_dir)

            # 创建 runner
            runner = EvalRunner(
                adapter=adapter,
                num_trials=num_trials,
                max_parallel=max_parallel,
                user_agent_mock=judge_mock,
            )

            # 执行评测（单 trial 或多 trial）
            if num_trials > 1:
                all_traces = await runner.run_evaluation_parallel(tasks)
                # 评分
                task_trials_list = []
                for task in tasks:
                    traces = all_traces.get(task.task_id, [])
                    if traces:
                        tt = await scorer.score_trials(traces, task)
                    else:
                        tt = TaskTrials(
                            task_id=task.task_id,
                            dimension=task.dimension,
                            sub_dimension=task.sub_dimension,
                            difficulty=task.difficulty,
                        )
                    task_trials_list.append(tt)
                    run.completed_tasks += 1
                    run.current_task = task.task_id
                    run.progress = round(run.completed_tasks / run.total_tasks * 100, 1)
                    await self._broadcast_progress(run)
            else:
                traces = await runner.run_evaluation(tasks)
                # 评分
                for task, trace in zip(tasks, traces, strict=False):
                    report = await scorer.score_task(trace, task)
                    run.completed_tasks += 1
                    run.current_task = task.task_id
                    run.progress = round(run.completed_tasks / run.total_tasks * 100, 1)
                    await self._broadcast_progress(run)

                # 构建结果
                agent_info = adapter.get_agent_info()
                reports = []
                for task, trace in zip(tasks, traces, strict=False):
                    report = await scorer.score_task(trace, task)
                    reports.append(report)
                result = scorer.build_result_from_reports(agent_info, reports)
                run.result = result

            # 如果是多 trial，构建完整结果
            if num_trials > 1:
                agent_info = adapter.get_agent_info()
                result = scorer.build_result(agent_info, task_trials_list, num_trials)
                run.result = result

            run.status = "completed"
            run.progress = 100.0
            run.finished_at = datetime.now(timezone.utc).isoformat()

            # 保存到历史
            self._save_to_history(run)

            await self._broadcast_progress(run)

        except asyncio.CancelledError:
            run.status = "cancelled"
            run.finished_at = datetime.now(timezone.utc).isoformat()
            await self._broadcast_progress(run)
        except Exception as e:
            run.status = "failed"
            run.error = str(e)
            run.finished_at = datetime.now(timezone.utc).isoformat()
            await self._broadcast_progress(run)

    def _save_to_history(self, run: EvalRun) -> None:
        """保存评测结果到历史记录（排行榜用）。"""
        if run.result is None:
            return
        entry = {
            "run_id": run.run_id,
            "agent_name": run.result.agent_name,
            "agent_model": run.result.agent_model,
            "timestamp": run.result.timestamp,
            "num_trials": run.result.num_trials,
            "overall_percentage": run.result.overall_percentage,
            "overall_pass_k_rate": run.result.overall_pass_k_rate,
            "orthogonal_scores": [
                {
                    "dimension": o.dimension,
                    "percentage": o.percentage,
                }
                for o in run.result.orthogonal_scores
            ],
        }
        self.history.append(entry)

    async def cancel_run(self, run_id: str) -> bool:
        """取消评测运行。"""
        run = self.runs.get(run_id)
        if run is None or run._task is None:
            return False
        run._task.cancel()
        return True

    async def cancel_all(self) -> None:
        """取消所有运行中的评测。"""
        for run_id in list(self.runs.keys()):
            await self.cancel_run(run_id)

    def get_run(self, run_id: str) -> EvalRun | None:
        return self.runs.get(run_id)

    def get_result_json(self, run_id: str) -> dict | None:
        """获取评测结果的 JSON 可序列化字典。"""
        run = self.runs.get(run_id)
        if run is None or run.result is None:
            return None
        return run.result.model_dump(exclude_none=True)

    # ---- WebSocket 管理 ----

    async def connect_ws(self, ws: WebSocket) -> None:
        await ws.accept()
        self.ws_connections.append(ws)

    def disconnect_ws(self, ws: WebSocket) -> None:
        if ws in self.ws_connections:
            self.ws_connections.remove(ws)

    async def _broadcast_progress(self, run: EvalRun) -> None:
        """向所有 WebSocket 客户端广播评测进度。"""
        if not self.ws_connections:
            return
        msg = json.dumps({
            "type": "progress",
            "data": run.to_dict(),
        }, ensure_ascii=False, default=str)
        dead: list[WebSocket] = []
        for ws in self.ws_connections:
            try:
                await ws.send_text(msg)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect_ws(ws)

    # ---- 排行榜 ----

    def get_leaderboard(self) -> list[dict]:
        """返回按 overall_percentage 降序排列的排行榜。"""
        sorted_history = sorted(
            self.history, key=lambda x: x.get("overall_percentage", 0), reverse=True
        )
        for i, entry in enumerate(sorted_history, 1):
            entry["rank"] = i
        return sorted_history

    # ---- 维度 ----

    def get_dimensions(self) -> list[dict]:
        """返回维度定义列表。"""
        from pathlib import Path

        import yaml

        dim_path = Path(self.spec_dir).parent / "dimensions.yaml"
        if not dim_path.exists():
            return []
        with open(dim_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return data.get("dimensions", [])

    # ---- 对比评测 ----

    async def run_comparison(self, config: dict) -> dict:
        """执行多 Agent 横向对比评测。"""
        from agent_bench.reporter.comparison import ComparisonReport

        adapter_types = config.get("adapter_types", ["mock"])
        model = config.get("model", "gpt-4o")
        selected_tasks = config.get("tasks", [])
        judge_mock = config.get("judge_mock", True)

        # 过滤任务
        if selected_tasks:
            tasks = [t for t in self.tasks if t.task_id in selected_tasks]
        else:
            tasks = self.tasks

        if not tasks:
            return {"error": "没有找到匹配的任务"}

        llm_judge = None
        if not judge_mock:
            try:
                llm_judge = LLMJudge(mock_mode=False)
            except Exception:
                llm_judge = LLMJudge(mock_mode=True)
        else:
            llm_judge = LLMJudge(mock_mode=True)

        results = []
        for adapter_type in adapter_types:
            try:
                if adapter_type == "multi_agent":
                    from agent_bench.adapters.multi_agent import get_multi_agent_adapter
                    topology = config.get("topology", "manager_worker")
                    adapter = get_multi_agent_adapter(topology, model=model)
                else:
                    adapter_kwargs = {}
                    if adapter_type in ("raw_api", "data_analyst"):
                        adapter_kwargs["model"] = model
                    adapter = get_adapter(adapter_type, **adapter_kwargs)
            except Exception:  # noqa: BLE001
                continue

            runner = EvalRunner(adapter=adapter, user_agent_mock=judge_mock)
            scorer = Scorer(llm_judge=llm_judge, spec_dir=self.spec_dir)

            traces = await runner.run_evaluation(tasks)
            reports = []
            for task, trace in zip(tasks, traces, strict=False):
                report = await scorer.score_task(trace, task)
                reports.append(report)
            result = scorer.build_result_from_reports(adapter.get_agent_info(), reports)
            results.append(result)

        if len(results) < 2:
            return {"error": "成功评测的适配器不足 2 个"}

        report = ComparisonReport(results)
        return report.to_dict()


