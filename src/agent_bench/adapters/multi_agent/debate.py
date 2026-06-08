"""Debate 多 Agent 协作适配器。

拓扑结构：
    Affirmative Agent ←→ Negative Agent
              ↓
          Judge Agent（裁决）

工作流程：
1. Affirmative 提出主张和论据
2. Negative 反驳并提出反对论据
3. 可选：多轮辩论
4. Judge 评估双方论据，做出裁决

评测关注点：
- 论证质量（论据是否充分、逻辑是否严密）
- 反驳有效性（是否针对对方论点）
- 裁决准确性（是否基于事实而非偏见）
- 辩论效率（token 消耗 / 信息增益比）
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

_AFFIRMATIVE_PROMPT = """你是辩论的正方（Affirmative）。你的职责是：
- 支持给定的命题
- 提供有力的论据和证据
- 回应反方的反驳
- 保持逻辑严密和论点清晰

注意：即使你个人不同意该命题，也要尽力为正方辩护。这是辩论练习。
"""

_NEGATIVE_PROMPT = """你是辩论的反方（Negative）。你的职责是：
- 反驳给定的命题
- 提出反对论据和反例
- 回应正方的论点
- 保持逻辑严密和论点清晰

注意：即使你个人同意该命题，也要尽力为反方辩护。这是辩论练习。
"""

_JUDGE_PROMPT = """你是辩论的裁判（Judge）。你的职责是：
- 评估正方和反方的论据质量
- 判断哪方的论证更有说服力
- 指出双方论证的优缺点
- 做出公正的裁决

裁决格式：
```json
{
  "winner": "affirmative" 或 "negative",
  "reason": "裁决理由",
  "affirmative_score": 1-10,
  "negative_score": 1-10,
  "key_arguments": ["正方关键论据", "反方关键论据"]
}
```
"""


class DebateAdapter(MultiAgentAdapter):
    """Debate 多 Agent 辩论适配器。"""

    def __init__(
        self,
        affirmative: BaseAdapter,
        negative: BaseAdapter,
        judge: BaseAdapter,
        max_rounds: int = 2,
        name: str = "debate",
    ) -> None:
        """
        Args:
            affirmative: 正方 Agent。
            negative: 反方 Agent。
            judge: 裁判 Agent。
            max_rounds: 最大辩论轮数。
            name: 适配器名称。
        """
        roles = [
            AgentRole(name="affirmative", adapter=affirmative, description="正方：支持命题"),
            AgentRole(name="negative", adapter=negative, description="反方：反驳命题"),
            AgentRole(name="judge", adapter=judge, description="裁判：裁决辩论"),
        ]
        super().__init__(roles=roles, name=name, topology=TopologyType.DEBATE)
        self._affirmative = affirmative
        self._negative = negative
        self._judge = judge
        self._max_rounds = max_rounds

    async def run_task(
        self,
        task_prompt: str,
        tools: list[ToolDef],
        sandbox: Sandbox,
        max_steps: int = 10,
        timeout: int = 60,
        task_id: str = "",
    ) -> AgentTrace:
        """执行辩论流程。"""
        start_time = time.time()
        all_actions: list[AgentAction] = []
        total_tokens = 0
        global_step = 0

        # 辩论历史
        debate_history: list[str] = []

        # 轮流辩论
        for round_num in range(1, self._max_rounds + 1):
            # 正方发言
            aff_prompt = self._build_debate_prompt(
                _AFFIRMATIVE_PROMPT, task_prompt, debate_history, "正方", round_num
            )
            aff_trace = await self._affirmative.run_task(
                task_prompt=aff_prompt, tools=tools, sandbox=sandbox,
                max_steps=max_steps, timeout=timeout,
            )
            total_tokens += aff_trace.total_tokens
            aff_response = aff_trace.final_response

            for action in aff_trace.actions:
                global_step += 1
                action.step = global_step
                action.metadata = {"agent": "affirmative", "round": round_num}
                all_actions.append(action)

            debate_history.append(f"[正方 第{round_num}轮] {aff_response}")
            self.send_message(Message(
                sender="affirmative", receiver="negative",
                content=aff_response, metadata={"round": round_num},
            ))

            # 反方发言
            neg_prompt = self._build_debate_prompt(
                _NEGATIVE_PROMPT, task_prompt, debate_history, "反方", round_num
            )
            neg_trace = await self._negative.run_task(
                task_prompt=neg_prompt, tools=tools, sandbox=sandbox,
                max_steps=max_steps, timeout=timeout,
            )
            total_tokens += neg_trace.total_tokens
            neg_response = neg_trace.final_response

            for action in neg_trace.actions:
                global_step += 1
                action.step = global_step
                action.metadata = {"agent": "negative", "round": round_num}
                all_actions.append(action)

            debate_history.append(f"[反方 第{round_num}轮] {neg_response}")
            self.send_message(Message(
                sender="negative", receiver="affirmative",
                content=neg_response, metadata={"round": round_num},
            ))

        # 裁判裁决
        judge_prompt = self._build_judge_prompt(task_prompt, debate_history)
        judge_trace = await self._judge.run_task(
            task_prompt=judge_prompt, tools=[], sandbox=sandbox,
            max_steps=3, timeout=30,
        )
        total_tokens += judge_trace.total_tokens

        for action in judge_trace.actions:
            global_step += 1
            action.step = global_step
            action.metadata = {"agent": "judge", "phase": "verdict"}
            all_actions.append(action)

        self.send_message(Message(
            sender="judge", receiver="",
            content=judge_trace.final_response, metadata={"phase": "verdict"},
        ))

        return self.build_multi_agent_trace(
            task_id=task_id,
            all_actions=all_actions,
            total_tokens=total_tokens,
            final_response=judge_trace.final_response,
            execution_time=time.time() - start_time,
        )

    def _build_debate_prompt(
        self,
        system_prompt: str,
        proposition: str,
        history: list[str],
        side: str,
        round_num: int,
    ) -> str:
        """构建辩手 prompt。"""
        history_text = "\n".join(history) if history else "（首轮，暂无历史）"
        return (
            f"{system_prompt}\n\n"
            f"辩论命题: {proposition}\n"
            f"你的立场: {side}\n"
            f"当前轮次: {round_num}/{self._max_rounds}\n\n"
            f"辩论历史:\n{history_text}\n\n"
            f"请发表你的第 {round_num} 轮论点。"
        )

    def _build_judge_prompt(self, proposition: str, history: list[str]) -> str:
        """构建裁判 prompt。"""
        history_text = "\n".join(history)
        return (
            f"{_JUDGE_PROMPT}\n\n"
            f"辩论命题: {proposition}\n\n"
            f"完整辩论记录:\n{history_text}\n\n"
            f"请做出你的裁决。"
        )
