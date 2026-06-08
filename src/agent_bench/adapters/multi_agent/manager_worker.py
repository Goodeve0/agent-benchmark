"""Manager-Worker 多 Agent 协作适配器。

拓扑结构：
    Manager Agent（规划、分派、汇总）
      ├── Worker Agent 1（执行子任务 A）
      ├── Worker Agent 2（执行子任务 B）
      └── Worker Agent 3（执行子任务 C）

工作流程：
1. Manager 分析任务，分解为子任务列表
2. 将子任务分配给 Workers
3. Workers 并行执行子任务
4. Manager 汇总 Workers 的结果，生成最终回复
"""

from __future__ import annotations

import asyncio
import json
import logging
import time

from agent_bench.adapters.base import BaseAdapter
from agent_bench.adapters.multi_agent.base import (
    AgentRole,
    Message,
    MultiAgentAdapter,
    TopologyType,
)
from agent_bench.models import AgentAction, AgentTrace, ToolDef
from agent_bench.sandbox.sandbox import Sandbox

logger = logging.getLogger(__name__)

_DECOMPOSE_SYSTEM_PROMPT = """你是一个任务管理 Agent（Manager）。你的职责是：
1. 分析用户的任务需求
2. 将任务分解为独立的子任务
3. 以 JSON 格式输出子任务列表

输出格式（必须严格遵循）：
```json
{
  "subtasks": [
    {"id": 1, "description": "子任务描述", "assign_to": "worker_1"},
    {"id": 2, "description": "子任务描述", "assign_to": "worker_2"}
  ]
}
```

要求：
- 每个子任务应该独立可执行
- 子任务描述要清晰具体
- assign_to 从可用的 worker 中选择
- 子任务之间尽量减少依赖
"""

_SYNTHESIZE_SYSTEM_PROMPT = """你是一个任务管理 Agent（Manager）。你的职责是：
汇总各个 Worker 的执行结果，生成最终的完整回复。

要求：
- 包含每个 Worker 的关键发现
- 消除重复信息
- 给出综合性的结论
- 如果有冲突信息，指出并给出判断
"""


class ManagerWorkerAdapter(MultiAgentAdapter):
    """Manager-Worker 多 Agent 协作适配器。"""

    def __init__(
        self,
        manager: BaseAdapter,
        workers: list[BaseAdapter],
        name: str = "manager-worker",
    ) -> None:
        roles = [
            AgentRole(name="manager", adapter=manager, description="任务规划与汇总"),
        ]
        for i, worker in enumerate(workers, 1):
            roles.append(
                AgentRole(name=f"worker_{i}", adapter=worker, description=f"执行子任务 {i}")
            )

        super().__init__(roles=roles, name=name, topology=TopologyType.MANAGER_WORKER)
        self._manager = manager
        self._workers = workers

    async def run_task(
        self,
        task_prompt: str,
        tools: list[ToolDef],
        sandbox: Sandbox,
        max_steps: int = 10,
        timeout: int = 60,
        task_id: str = "",
    ) -> AgentTrace:
        """执行 Manager-Worker 协作流程。"""
        start_time = time.time()
        all_actions: list[AgentAction] = []
        total_tokens = 0
        global_step = 0

        # Phase 1: Manager 分解任务
        logger.info("[ManagerWorker] Phase 1: Manager 分解任务")
        decompose_trace = await self._manager.run_task(
            task_prompt=self._build_decompose_prompt(task_prompt),
            tools=[],
            sandbox=sandbox,
            max_steps=3,
            timeout=30,
        )
        total_tokens += decompose_trace.total_tokens

        for action in decompose_trace.actions:
            global_step += 1
            action.step = global_step
            action.metadata = {"agent": "manager", "phase": "decompose"}
            all_actions.append(action)

        subtasks = self._parse_subtasks(decompose_trace.final_response)
        if not subtasks:
            return self.build_multi_agent_trace(
                task_id=task_id,
                all_actions=all_actions,
                total_tokens=total_tokens,
                final_response=decompose_trace.final_response,
                execution_time=time.time() - start_time,
                success=False,
                error="Manager 未能成功分解任务",
            )

        self.send_message(Message(
            sender="manager",
            receiver="",
            content=f"任务已分解为 {len(subtasks)} 个子任务",
            metadata={"phase": "decompose"},
        ))

        # Phase 2: Workers 并行执行
        logger.info(f"[ManagerWorker] Phase 2: {len(subtasks)} Workers 并行执行")
        worker_tasks = []
        for i, subtask in enumerate(subtasks):
            worker_idx = min(i, len(self._workers) - 1)
            worker_name = f"worker_{worker_idx + 1}"
            worker = self._workers[worker_idx]

            self.send_message(Message(
                sender="manager",
                receiver=worker_name,
                content=subtask.get("description", str(subtask)),
                metadata={"subtask_id": subtask.get("id", i + 1)},
            ))

            worker_tasks.append(
                worker.run_task(
                    task_prompt=self._build_worker_prompt(subtask, task_prompt),
                    tools=tools,
                    sandbox=sandbox,
                    max_steps=max_steps,
                    timeout=timeout,
                )
            )

        worker_traces = await asyncio.gather(*worker_tasks, return_exceptions=True)

        worker_results: dict[str, str] = {}
        for i, trace_result in enumerate(worker_traces):
            worker_name = f"worker_{min(i, len(self._workers) - 1) + 1}"

            if isinstance(trace_result, Exception):
                global_step += 1
                all_actions.append(AgentAction(
                    step=global_step,
                    action_type="thinking",
                    content=f"[{worker_name} 执行失败] {trace_result}",
                    metadata={"agent": worker_name, "phase": "execute", "error": True},
                ))
                worker_results[worker_name] = f"执行失败: {trace_result}"
                continue

            trace: AgentTrace = trace_result
            total_tokens += trace.total_tokens

            for action in trace.actions:
                global_step += 1
                action.step = global_step
                action.metadata = {"agent": worker_name, "phase": "execute"}
                all_actions.append(action)

            worker_results[worker_name] = trace.final_response

            self.send_message(Message(
                sender=worker_name,
                receiver="manager",
                content=trace.final_response,
                metadata={"phase": "execute"},
            ))

        # Phase 3: Manager 汇总
        logger.info("[ManagerWorker] Phase 3: Manager 汇总结果")
        synthesize_trace = await self._manager.run_task(
            task_prompt=self._build_synthesize_prompt(task_prompt, worker_results),
            tools=[],
            sandbox=sandbox,
            max_steps=3,
            timeout=30,
        )
        total_tokens += synthesize_trace.total_tokens

        for action in synthesize_trace.actions:
            global_step += 1
            action.step = global_step
            action.metadata = {"agent": "manager", "phase": "synthesize"}
            all_actions.append(action)

        return self.build_multi_agent_trace(
            task_id=task_id,
            all_actions=all_actions,
            total_tokens=total_tokens,
            final_response=synthesize_trace.final_response,
            execution_time=time.time() - start_time,
        )

    def _build_decompose_prompt(self, task_prompt: str) -> str:
        worker_names = [f"worker_{i+1}" for i in range(len(self._workers))]
        return (
            f"{_DECOMPOSE_SYSTEM_PROMPT}\n\n"
            f"可用的 Workers: {worker_names}\n\n"
            f"用户任务: {task_prompt}\n\n"
            f"请分解为子任务并分配给 Workers。"
        )

    def _build_worker_prompt(self, subtask: dict, original_task: str) -> str:
        description = subtask.get("description", str(subtask))
        return (
            f"你是 Manager-Worker 团队中的一个 Worker。\n"
            f"原始任务: {original_task}\n"
            f"你被分配的子任务: {description}\n\n"
            f"请专注于完成你的子任务，给出简洁明确的结果。"
        )

    def _build_synthesize_prompt(self, original_task: str, worker_results: dict[str, str]) -> str:
        results_text = "\n\n".join(
            f"### {name} 的结果:\n{result}"
            for name, result in worker_results.items()
        )
        return (
            f"{_SYNTHESIZE_SYSTEM_PROMPT}\n\n"
            f"原始任务: {original_task}\n\n"
            f"各 Worker 的执行结果:\n{results_text}\n\n"
            f"请汇总以上结果，生成完整的最终回复。"
        )

    @staticmethod
    def _parse_subtasks(response: str) -> list[dict]:
        """从 Manager 的回复中解析子任务列表。"""
        try:
            json_start = response.find("{")
            json_end = response.rfind("}") + 1
            if json_start >= 0 and json_end > json_start:
                data = json.loads(response[json_start:json_end])
                return data.get("subtasks", [])
        except json.JSONDecodeError:
            pass

        lines = [line.strip().lstrip("0123456789.-) ") for line in response.split("\n") if line.strip()]
        if lines:
            return [{"id": i + 1, "description": line, "assign_to": f"worker_{i + 1}"} for i, line in enumerate(lines)]

        return []
