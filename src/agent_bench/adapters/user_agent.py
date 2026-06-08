"""模拟用户适配器：在多轮对话评测中扮演用户角色。

UserAgent 根据 persona 描述和对话历史，生成用户的下一条消息。
支持两种模式：
- mock_mode=True: 基于规则生成确定性回复（无需 LLM / API Key）。
- mock_mode=False: 调用 OpenAI API 生成回复（需要 OPENAI_API_KEY）。

设计原则：
- UserAgent 不是被评测的对象，它是评测基础设施的一部分。
- 它的职责是模拟真实用户行为，给被测 Agent 提供合理的交互输入。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ConversationTurn:
    """对话中的一轮。

    Attributes:
        role: 角色，"user" 或 "agent"。
        content: 消息内容。
        metadata: 附加元数据（如工具调用信息）。
    """

    role: str  # "user" | "agent"
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)


class UserAgent:
    """模拟用户，根据 persona 和对话历史生成下一条用户消息。

    Attributes:
        persona: 用户人设描述。
        task_prompt: 原始任务描述（用户的核心需求）。
        success_criteria: 对话成功的判定标准。
        system_prompt_suffix: 附加到系统提示的后缀。
        mock_mode: 是否使用 mock 模式（无需 LLM）。
        model: LLM 模型名（mock_mode=False 时使用）。
    """

    def __init__(
        self,
        persona: str,
        task_prompt: str,
        success_criteria: str = "Agent 成功完成了用户的需求。",
        system_prompt_suffix: str = "",
        mock_mode: bool = True,
        model: str = "gpt-4o",
    ) -> None:
        self.persona = persona
        self.task_prompt = task_prompt
        self.success_criteria = success_criteria
        self.system_prompt_suffix = system_prompt_suffix
        self.mock_mode = mock_mode
        self.model = model

    async def generate_message(
        self,
        history: list[ConversationTurn],
        round_num: int,
        max_rounds: int,
    ) -> str:
        """根据对话历史生成用户的下一条消息。

        Args:
            history: 到目前为止的对话历史。
            round_num: 当前轮次（从 1 开始）。
            max_rounds: 最大轮次。

        Returns:
            用户的下一条消息文本。
        """
        if self.mock_mode:
            return self._mock_generate(history, round_num, max_rounds)
        return await self._llm_generate(history, round_num, max_rounds)

    async def should_continue(
        self,
        history: list[ConversationTurn],
        round_num: int,
        max_rounds: int,
    ) -> bool:
        """判断对话是否应该继续。

        在 mock 模式下，只要未达到最大轮次就继续。
        在 LLM 模式下，LLM 可以判断用户需求是否已满足。

        Args:
            history: 对话历史。
            round_num: 当前轮次。
            max_rounds: 最大轮次。

        Returns:
            True 表示应继续对话，False 表示结束。
        """
        if round_num >= max_rounds:
            return False

        if self.mock_mode:
            return self._mock_should_continue(history, round_num)
        return await self._llm_should_continue(history, round_num, max_rounds)

    # ------------------------------------------------------------------ #
    # Mock 模式实现
    # ------------------------------------------------------------------ #

    def _mock_generate(
        self,
        history: list[ConversationTurn],
        round_num: int,
        max_rounds: int,
    ) -> str:
        """Mock 模式：基于规则生成确定性用户回复。"""
        if not history:
            # 第一轮：直接发送任务需求
            return self.task_prompt

        # 获取 Agent 最后一条回复
        agent_msgs = [t for t in history if t.role == "agent"]
        if not agent_msgs:
            return "请继续处理我的需求。"

        last_agent_msg = agent_msgs[-1].content

        # 根据轮次和 Agent 回复生成不同的追问
        if round_num == 2:
            return self._mock_followup(last_agent_msg)
        if round_num == 3:
            return self._mock_clarification(last_agent_msg)
        if round_num >= max_rounds - 1:
            return "好的，请给我最终的总结。"
        return "明白了。关于你提到的内容，能否再详细说明一下？"

    def _mock_followup(self, agent_response: str) -> str:
        """生成追问消息。"""
        if "已完成" in agent_response or "完成" in agent_response:
            return "结果看起来不错，但能否提供更多细节？"
        if "错误" in agent_response or "失败" in agent_response:
            return "遇到了什么问题？能否换一种方式尝试？"
        return "谢谢你的回复。我还有一个相关的问题：能否进一步分析一下？"

    def _mock_clarification(self, agent_response: str) -> str:
        """生成澄清消息。"""
        if len(agent_response) < 50:
            return "你的回复太简短了，能否提供更详细的解释？"
        return "好的，我理解了。最后确认一下，这个方案的可行性如何？"

    def _mock_should_continue(
        self,
        history: list[ConversationTurn],
        round_num: int,
    ) -> bool:
        """Mock 模式：简单规则判断是否继续。"""
        if round_num <= 1:
            return True

        # 检查 Agent 最后回复是否包含"完成"类关键词
        agent_msgs = [t for t in history if t.role == "agent"]
        if agent_msgs:
            last = agent_msgs[-1].content.lower()
            if any(kw in last for kw in ["最终总结", "总结如下", "以上就是"]):
                return False

        return True

    # ------------------------------------------------------------------ #
    # LLM 模式实现
    # ------------------------------------------------------------------ #

    def _build_system_prompt(self) -> str:
        """构建 LLM 模式的系统提示。"""
        prompt = f"""你正在扮演一个用户，与一个 AI Agent 进行对话。

## 你的人设
{self.persona}

## 你的核心需求
{self.task_prompt}

## 对话成功标准
{self.success_criteria}

## 行为准则
1. 始终保持你的人设角色。
2. 根据 Agent 的回复进行合理的追问、澄清或确认。
3. 如果 Agent 的回复不够好，要求它改进。
4. 如果 Agent 已经很好地完成了你的需求，表示满意并结束对话。
5. 不要透露你是 AI 或这是一个测试。
6. 回复要简洁自然，像真实用户一样。

## 特殊指令
- 如果你认为对话应该结束（需求已满足），在回复末尾加上 [END]。
- 只输出用户的消息内容，不要加任何前缀或解释。"""

        if self.system_prompt_suffix:
            prompt += f"\n\n{self.system_prompt_suffix}"

        return prompt

    async def _llm_generate(
        self,
        history: list[ConversationTurn],
        round_num: int,
        max_rounds: int,
    ) -> str:
        """LLM 模式：调用 OpenAI API 生成用户回复。"""
        try:
            from openai import AsyncOpenAI
        except ImportError as e:
            raise ImportError(
                "LLM 模式需要安装 openai: pip install openai"
            ) from e

        client = AsyncOpenAI()

        messages: list[dict[str, str]] = [
            {"role": "system", "content": self._build_system_prompt()},
        ]

        # 将对话历史转换为 OpenAI 消息格式
        # 注意：UserAgent 扮演的是"用户"，所以 user_agent 的消息是 assistant
        # 而被测 Agent 的消息是 user（从 UserAgent 的视角看）
        for turn in history:
            if turn.role == "user":
                messages.append({"role": "assistant", "content": turn.content})
            else:  # agent
                messages.append({"role": "user", "content": turn.content})

        # 添加轮次提示
        if round_num >= max_rounds - 1:
            messages.append({
                "role": "system",
                "content": f"注意：这是第 {round_num}/{max_rounds} 轮对话，即将达到最大轮次。"
                "如果需求已基本满足，请考虑结束对话（在回复末尾加 [END]）。",
            })

        response = await client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=0.7,
            max_tokens=500,
        )

        content = response.choices[0].message.content or ""
        # 移除 [END] 标记（由 should_continue 处理）
        return content.replace("[END]", "").strip()

    async def _llm_should_continue(
        self,
        history: list[ConversationTurn],
        round_num: int,
        max_rounds: int,
    ) -> bool:
        """LLM 模式：检查最后一条用户消息是否包含 [END] 标记。"""
        if round_num >= max_rounds:
            return False

        # 检查最后一条用户消息原始内容（在 _llm_generate 移除 [END] 之前）
        # 这里我们通过重新检查 Agent 回复来判断
        # 简化实现：如果 Agent 最后回复包含明确的完成信号，则结束
        agent_msgs = [t for t in history if t.role == "agent"]
        if agent_msgs:
            last = agent_msgs[-1].content
            # 如果 Agent 明确表示完成
            if any(kw in last for kw in ["还有其他", "还需要", "希望能帮到你"]):
                # 有一定概率结束（模拟真实用户行为）
                if round_num >= 3:
                    return False

        return True

    # ------------------------------------------------------------------ #
    # 序列化
    # ------------------------------------------------------------------ #

    def to_dict(self) -> dict[str, Any]:
        """序列化为字典。"""
        return {
            "persona": self.persona,
            "task_prompt": self.task_prompt,
            "success_criteria": self.success_criteria,
            "mock_mode": self.mock_mode,
            "model": self.model,
        }

    @classmethod
    def from_task_config(
        cls,
        task_prompt: str,
        config: Any,  # UserAgentConfig
        mock_mode: bool = True,
        model: str = "gpt-4o",
    ) -> UserAgent:
        """从 Task 的 UserAgentConfig 创建 UserAgent。

        Args:
            task_prompt: 任务描述。
            config: UserAgentConfig 实例。
            mock_mode: 是否使用 mock 模式。
            model: LLM 模型名。

        Returns:
            UserAgent 实例。
        """
        return cls(
            persona=config.persona,
            task_prompt=config.initial_message or task_prompt,
            success_criteria=config.success_criteria,
            system_prompt_suffix=config.system_prompt_suffix,
            mock_mode=mock_mode,
            model=model,
        )
