"""Pipeline 多 Agent 协作适配器。

拓扑结构：
    Agent_1 → Agent_2 → Agent_3 → ... → Agent_N
    （流水线式顺序处理）

工作流程：
1. 第一个 Agent 处理原始任务，生成中间产物
2. 中间产物传给下一个 Agent 继续处理
3. 依次传递，最后一个 Agent 生成最终结果

典型场景：
- Researcher → Writer → Reviewer → Publisher
- 需求分析 → 方案设计 → 代码实现 → 测试验证
- 数据收集 → 数据清洗 → 数据分析 → 报告生成

评测关注点：
- 信息传递损失率（中间产物质量）
- 端到端准确率
- 各阶段一致性
- 上下文传递效率
"""

from __future__ import annotations

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


class PipelineAdapter(MultiAgentAdapter):
    """Pipeline 多 Agent 流水线适配器。"""

    def __init__(
        self,
        stages: list[tuple[str, BaseAdapter, str]],
        name: str = "pipeline",
    ) -> None:
        """
        Args:
            stages: 流水线阶段列表，每项为 (角色名, 适配器, 阶段描述)。
            name: 适配器名称。

        示例::

            pipeline = PipelineAdapter(stages=[
                ("researcher", researcher_adapter, "负责信息搜集和整理"),
                ("writer", writer_adapter, "负责撰写初稿"),
                ("reviewer", reviewer_adapter, "负责审核修改"),
            ])
        """
        roles = [
            AgentRole(name=stage_name, adapter=adapter, description=desc)
            for stage_name, adapter, desc in stages
        ]
        super().__init__(roles=roles, name=name, topology=TopologyType.PIPELINE)
        self._stages = stages

    async def run_task(
        self,
        task_prompt: str,
        tools: list[ToolDef],
        sandbox: Sandbox,
        max_steps: int = 10,
        timeout: int = 60,
        task_id: str = "",
    ) -> AgentTrace:
        """执行流水线协作流程。"""
        start_time = time.time()
        all_actions: list[AgentAction] = []
        total_tokens = 0
        global_step = 0

        # 逐阶段执行
        intermediate_result = task_prompt
        stage_results: dict[str, str] = {}

        for stage_idx, (stage_name, adapter, stage_desc) in enumerate(self._stages):
            logger.info(f"[Pipeline] Stage {stage_idx + 1}/{len(self._stages)}: {stage_name}")

            # 构建当前阶段的 prompt
            if stage_idx == 0:
                # 第一阶段：接收原始任务
                stage_prompt = self._build_first_stage_prompt(task_prompt, stage_name, stage_desc)
            else:
                # 后续阶段：接收前一阶段的输出
                prev_stage = self._stages[stage_idx - 1]
                stage_prompt = self._build_stage_prompt(
                    task_prompt, stage_name, stage_desc,
                    prev_stage[0], stage_results[prev_stage[0]],
                )

            # 执行当前阶段
            try:
                stage_trace = await adapter.run_task(
                    task_prompt=stage_prompt,
                    tools=tools,
                    sandbox=sandbox,
                    max_steps=max_steps,
                    timeout=timeout,
                )
                total_tokens += stage_trace.total_tokens
                intermediate_result = stage_trace.final_response
                stage_results[stage_name] = intermediate_result

                # 记录动作
                for action in stage_trace.actions:
                    global_step += 1
                    action.step = global_step
                    action.metadata = {"agent": stage_name, "stage": stage_idx + 1}
                    all_actions.append(action)

                # 记录消息传递
                if stage_idx > 0:
                    prev_stage_name = self._stages[stage_idx - 1][0]
                    self.send_message(Message(
                        sender=prev_stage_name,
                        receiver=stage_name,
                        content=intermediate_result[:500],
                        metadata={"stage": stage_idx + 1},
                    ))

            except Exception as e:
                # 阶段失败，记录错误并中止
                global_step += 1
                all_actions.append(AgentAction(
                    step=global_step,
                    action_type="thinking",
                    content=f"[{stage_name} 阶段失败] {e}",
                    metadata={"agent": stage_name, "stage": stage_idx + 1, "error": True},
                ))

                return self.build_multi_agent_trace(
                    task_id=task_id,
                    all_actions=all_actions,
                    total_tokens=total_tokens,
                    final_response=f"流水线在 {stage_name} 阶段失败: {e}",
                    execution_time=time.time() - start_time,
                    success=False,
                    error=f"Stage {stage_name} failed: {e}",
                )

        return self.build_multi_agent_trace(
            task_id=task_id,
            all_actions=all_actions,
            total_tokens=total_tokens,
            final_response=intermediate_result,
            execution_time=time.time() - start_time,
        )

    def _build_first_stage_prompt(self, task_prompt: str, stage_name: str, stage_desc: str) -> str:
        """构建第一阶段 prompt。"""
        return (
            f"你是流水线处理的第一阶段 [{stage_name}]。\n"
            f"职责: {stage_desc}\n\n"
            f"原始任务:\n{task_prompt}\n\n"
            f"请完成你的处理，输出结果供下一阶段使用。"
        )

    def _build_stage_prompt(
        self,
        original_task: str,
        stage_name: str,
        stage_desc: str,
        prev_stage_name: str,
        prev_result: str,
    ) -> str:
        """构建后续阶段 prompt。"""
        return (
            f"你是流水线处理的阶段 [{stage_name}]。\n"
            f"职责: {stage_desc}\n\n"
            f"原始任务:\n{original_task}\n\n"
            f"上一阶段 [{prev_stage_name}] 的输出:\n{prev_result}\n\n"
            f"请基于上一阶段的输出完成你的处理。"
        )
