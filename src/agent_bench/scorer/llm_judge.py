"""LLM Judge 评分器。

使用 LLM（如 GPT-4o）对 Agent 的执行结果进行主观评分。
与规则引擎互补：规则引擎处理客观指标（工具调用、格式），LLM Judge 处理主观指标（回复质量、推理深度）。

设计要点:
- 每个 JudgeRubricItem 独立调用一次 LLM，返回 pass/fail + 理由
- 使用结构化 prompt，要求 LLM 输出 JSON 格式的判定结果
- 支持 Mock 模式（不调用真实 LLM），用于测试和 Cohen's Kappa 实验
"""

from __future__ import annotations

import json
import logging
from typing import Any

from agent_bench.models import AgentTrace, JudgeRubricItem, ScoreDetail

logger = logging.getLogger(__name__)

# LLM Judge 的系统 prompt
JUDGE_SYSTEM_PROMPT = """你是一个严格的 AI Agent 评测裁判。你的任务是根据给定的评分标准，判断 Agent 的执行结果是否达标。

你必须以 JSON 格式回复，包含以下字段：
- "passed": true 或 false（是否达标）
- "reason": 字符串（判定理由，简洁明了）
- "confidence": 0.0-1.0 之间的浮点数（你对判定的置信度）

只输出 JSON，不要输出其他内容。"""

JUDGE_USER_PROMPT_TEMPLATE = """## 评分项
- 名称: {rubric_name}
- 评分标准: {criteria}

## Agent 执行信息
- 任务提示: {task_prompt}
- Agent 最终回复: {final_response}
- 工具调用记录: {tool_calls}
- 执行步骤数: {total_steps}
- 是否成功完成: {success}

## 请判断
根据上述评分标准，Agent 的表现是否达标？请以 JSON 格式回复。"""


class LLMJudge:
    """LLM Judge 评分器。

    支持两种模式:
    - 真实模式: 调用 OpenAI API 进行评分
    - Mock 模式: 使用预设规则模拟 LLM 评分（用于测试和实验）
    """

    def __init__(
        self,
        model: str = "gpt-4o",
        mock_mode: bool = False,
        api_key: str | None = None,
        base_url: str | None = None,
    ) -> None:
        """
        Args:
            model: LLM 模型名。
            mock_mode: 是否使用 Mock 模式（不调用真实 LLM）。
            api_key: OpenAI API Key（真实模式需要）。
            base_url: OpenAI API Base URL（可选）。
        """
        self.model = model
        self.mock_mode = mock_mode
        self._client = None

        if not mock_mode:
            try:
                import openai  # noqa: F811

                kwargs: dict[str, Any] = {}
                if api_key:
                    kwargs["api_key"] = api_key
                if base_url:
                    kwargs["base_url"] = base_url
                self._client = openai.OpenAI(**kwargs)
            except ImportError:
                logger.warning(
                    "openai 未安装，LLM Judge 将使用 Mock 模式。"
                    "安装: pip install 'agent-bench[openai]'"
                )
                self.mock_mode = True

    async def judge_item(
        self,
        trace: AgentTrace,
        item: JudgeRubricItem,
        task_prompt: str = "",
    ) -> ScoreDetail:
        """对单个 JudgeRubricItem 进行 LLM 评分。

        Args:
            trace: Agent 执行轨迹。
            item: LLM Judge 评分项。
            task_prompt: 原始任务提示。

        Returns:
            ScoreDetail（judge_type="llm_judge"）。
        """
        if self.mock_mode:
            return self._mock_judge(trace, item)

        return await self._real_judge(trace, item, task_prompt)

    def _mock_judge(
        self,
        trace: AgentTrace,
        item: JudgeRubricItem,
    ) -> ScoreDetail:
        """Mock 模式评分：基于简单启发式规则模拟 LLM 判断。

        Mock 策略:
        - 如果 Agent 成功完成且有最终回复 → 通过
        - 如果 Agent 失败或无回复 → 不通过
        """
        if trace.success and trace.final_response and len(trace.final_response.strip()) > 0:
            return ScoreDetail(
                rubric_name=item.name,
                points=item.points,
                max_points=item.points,
                passed=True,
                reason=f"[LLM Judge Mock] Agent 成功完成任务并给出回复，符合标准: {item.criteria}",
                judge_type="llm_judge",
            )
        else:
            reason = "[LLM Judge Mock] Agent "
            if not trace.success:
                reason += f"执行失败({trace.error})"
            elif not trace.final_response:
                reason += "未给出最终回复"
            else:
                reason += "回复为空"
            return ScoreDetail(
                rubric_name=item.name,
                points=0.0,
                max_points=item.points,
                passed=False,
                reason=reason,
                judge_type="llm_judge",
            )

    async def _real_judge(
        self,
        trace: AgentTrace,
        item: JudgeRubricItem,
        task_prompt: str,
    ) -> ScoreDetail:
        """真实 LLM 评分：调用 OpenAI API。"""
        # 构造工具调用摘要
        tool_calls_summary = []
        for action in trace.tool_calls():
            tool_calls_summary.append({
                "tool": action.tool_name,
                "params": action.parameters,
                "result": str(action.result)[:200],  # 截断避免过长
            })

        user_prompt = JUDGE_USER_PROMPT_TEMPLATE.format(
            rubric_name=item.name,
            criteria=item.criteria,
            task_prompt=task_prompt[:500],  # 截断
            final_response=trace.final_response[:1000],  # 截断
            tool_calls=json.dumps(tool_calls_summary, ensure_ascii=False, indent=2),
            total_steps=trace.total_steps,
            success=trace.success,
        )

        try:
            # 使用同步客户端（在 async 上下文中用 run_in_executor 更好，
            # 但为简化实现先直接调用）
            response = self._client.chat.completions.create(
                model=item.model or self.model,
                messages=[
                    {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.0,  # 确定性评分
                max_tokens=256,
            )

            content = response.choices[0].message.content or ""
            result = self._parse_judge_response(content)

            passed = result.get("passed", False)
            reason = result.get("reason", "LLM Judge 未给出理由")
            confidence = result.get("confidence", 0.5)

            return ScoreDetail(
                rubric_name=item.name,
                points=item.points if passed else 0.0,
                max_points=item.points,
                passed=passed,
                reason=f"[LLM Judge, confidence={confidence:.2f}] {reason}",
                judge_type="llm_judge",
            )

        except Exception as e:
            logger.error(f"LLM Judge 调用失败: {e}")
            return ScoreDetail(
                rubric_name=item.name,
                points=0.0,
                max_points=item.points,
                passed=False,
                reason=f"[LLM Judge] 调用失败: {e}",
                judge_type="llm_judge",
            )

    @staticmethod
    def _parse_judge_response(content: str) -> dict:
        """解析 LLM 返回的 JSON 判定结果。"""
        content = content.strip()
        # 处理 markdown 代码块包裹
        if content.startswith("```"):
            lines = content.split("\n")
            # 去掉首尾的 ``` 行
            lines = [line for line in lines if not line.strip().startswith("```")]
            content = "\n".join(lines)

        try:
            return json.loads(content)
        except (json.JSONDecodeError, ValueError):
            # 尝试从文本中提取 JSON
            import re

            match = re.search(r"\{[^}]+\}", content, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group())
                except (json.JSONDecodeError, ValueError):
                    pass
            return {"passed": False, "reason": f"无法解析 LLM 响应: {content[:200]}", "confidence": 0.0}
