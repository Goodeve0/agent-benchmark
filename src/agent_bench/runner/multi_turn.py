"""多轮对话评测运行器。

编排 UserAgent（模拟用户）与被测 Agent 之间的多轮交互。

流程：
1. UserAgent 发送初始消息（来自 task.prompt 或 user_agent.initial_message）。
2. 被测 Agent 处理消息并回复。
3. UserAgent 根据 Agent 回复生成下一条消息。
4. 重复 2-3，直到达到 max_rounds 或 UserAgent 判断对话结束。
5. 收集完整对话轨迹，用于后续评分。

设计要点：
- 每轮对话共享同一个 Sandbox（工具状态跨轮次保持）。
- 对话历史通过 ConversationTurn 列表传递。
- 最终生成的 AgentTrace 包含所有轮次的 actions + 完整对话历史。
"""

from __future__ import annotations

import time
from typing import Any

from agent_bench.adapters.base import BaseAdapter
from agent_bench.adapters.user_agent import ConversationTurn, UserAgent
from agent_bench.models import AgentAction, AgentTrace, Task
from agent_bench.sandbox import Sandbox


class MultiTurnRunner:
    """多轮对话评测运行器。

    Attributes:
        adapter: 被测 Agent 的适配器。
        user_agent: 模拟用户的 UserAgent。
        max_steps_per_turn: 每轮 Agent 的最大步数。
        timeout_per_turn: 每轮 Agent 的超时秒数。
    """

    def __init__(
        self,
        adapter: BaseAdapter,
        user_agent: UserAgent,
        max_steps_per_turn: int = 10,
        timeout_per_turn: int = 60,
    ) -> None:
        self.adapter = adapter
        self.user_agent = user_agent
        self.max_steps_per_turn = max_steps_per_turn
        self.timeout_per_turn = timeout_per_turn

    async def run(self, task: Task) -> AgentTrace:
        """执行多轮对话评测。

        Args:
            task: 评测任务（mode=multi_turn）。

        Returns:
            AgentTrace: 包含所有轮次的完整执行轨迹。
                - actions: 所有轮次的 AgentAction 合并列表。
                - metadata.conversation_history: 完整对话历史。
                - metadata.num_rounds: 实际对话轮数。
                - metadata.audit_log: 沙箱审计日志。
        """
        config = task.user_agent
        max_rounds = config.max_rounds if config else 5

        # 共享 Sandbox（工具状态跨轮次保持）
        sandbox = Sandbox(task.mock_apis)

        # 对话历史
        history: list[ConversationTurn] = []
        # 所有轮次的 actions 合并
        all_actions: list[AgentAction] = []
        total_tokens = 0
        global_step = 0
        start_time = time.time()

        for round_num in range(1, max_rounds + 1):
            # ---- 用户发言 ----
            if round_num == 1:
                # 第一轮：使用初始消息或任务描述
                user_msg = (
                    config.initial_message if config and config.initial_message
                    else task.prompt
                )
            else:
                # 后续轮次：UserAgent 生成消息
                user_msg = await self.user_agent.generate_message(
                    history, round_num, max_rounds,
                )

            history.append(ConversationTurn(role="user", content=user_msg))

            # 记录用户消息为 thinking action（方便追踪）
            global_step += 1
            all_actions.append(
                AgentAction(
                    step=global_step,
                    action_type="thinking",
                    content=f"[User Round {round_num}] {user_msg}",
                )
            )

            # ---- Agent 回复 ----
            try:
                agent_trace = await self.adapter.run_task(
                    task_prompt=self._build_agent_prompt(user_msg, history),
                    tools=task.tools,
                    sandbox=sandbox,
                    max_steps=self.max_steps_per_turn,
                    timeout=self.timeout_per_turn,
                )
            except Exception as e:  # noqa: BLE001
                # Agent 执行失败，记录错误并结束
                history.append(
                    ConversationTurn(
                        role="agent",
                        content=f"[错误] {e}",
                        metadata={"error": str(e)},
                    )
                )
                break

            # 合并 Agent 的 actions（重新编号 step）
            for action in agent_trace.actions:
                global_step += 1
                action.step = global_step
                all_actions.append(action)

            total_tokens += agent_trace.total_tokens

            # 记录 Agent 回复到对话历史
            history.append(
                ConversationTurn(
                    role="agent",
                    content=agent_trace.final_response,
                    metadata={
                        "tool_calls": [
                            a.tool_name for a in agent_trace.actions
                            if a.action_type == "tool_call"
                        ],
                        "success": agent_trace.success,
                    },
                )
            )

            # ---- 判断是否继续 ----
            if round_num < max_rounds:
                should_go = await self.user_agent.should_continue(
                    history, round_num, max_rounds,
                )
                if not should_go:
                    break

        # ---- 构造最终 AgentTrace ----
        elapsed = round(time.time() - start_time, 4)
        audit_log = sandbox.get_audit_log(freeze=True)

        # 最终回复取 Agent 最后一条回复
        agent_msgs = [t for t in history if t.role == "agent"]
        final_response = agent_msgs[-1].content if agent_msgs else ""

        # 计算实际轮数
        num_rounds = len([t for t in history if t.role == "user"])

        return AgentTrace(
            task_id=task.task_id,
            actions=all_actions,
            total_tokens=total_tokens,
            total_steps=global_step,
            final_response=final_response,
            execution_time=elapsed,
            success=True,
            error=None,
            metadata={
                "audit_log": audit_log,
                "multi_turn": True,
                "num_rounds": num_rounds,
                "max_rounds": max_rounds,
                "conversation_history": [
                    {"role": t.role, "content": t.content, "metadata": t.metadata}
                    for t in history
                ],
            },
        )

    def _build_agent_prompt(
        self,
        current_message: str,
        history: list[ConversationTurn],
    ) -> str:
        """构建传给被测 Agent 的提示。

        包含对话历史上下文，让 Agent 能理解多轮对话的语境。

        Args:
            current_message: 当前用户消息。
            history: 完整对话历史（包含当前消息）。

        Returns:
            构造好的提示文本。
        """
        if len(history) <= 1:
            # 第一轮，直接使用用户消息
            return current_message

        # 多轮：构建包含历史的提示
        parts = ["以下是与用户的对话历史：\n"]
        # 排除最后一条（就是 current_message，会单独放在最后）
        for turn in history[:-1]:
            role_label = "用户" if turn.role == "user" else "助手"
            parts.append(f"{role_label}: {turn.content}")

        parts.append(f"\n用户的最新消息: {current_message}")
        parts.append("\n请根据对话历史和用户的最新消息进行回复。")

        return "\n".join(parts)
