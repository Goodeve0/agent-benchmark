"""任务相关数据模型。

对应 docs/API_SPEC.md 第1.1-1.3节。

v2: 新增 JudgeRubricItem / judge_rubric 支持 LLM Judge 混合评分。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

Difficulty = Literal["easy", "medium", "hard"]
JudgeType = Literal["rule", "llm_judge"]
TaskMode = Literal["single_turn", "multi_turn"]


class ToolDef(BaseModel):
    """工具定义。

    Attributes:
        name: 工具名称，全局唯一。
        description: 工具描述，对 Agent 可见。
        parameters: JSON Schema 格式的参数定义。
    """

    name: str
    description: str
    parameters: dict[str, Any] = Field(default_factory=dict)


class RubricItem(BaseModel):
    """单个评分项（规则引擎评分）。

    Attributes:
        name: 评分项名称。
        points: 分值，必须大于 0。
        criteria: 评分标准的文字描述。
        eval_fn: 可选，内置评分函数名；为空时使用默认规则评分。
        args: 可选，传给评分函数的额外参数。
    """

    name: str
    points: float
    criteria: str
    eval_fn: str | None = None
    args: dict[str, Any] = Field(default_factory=dict)

    @field_validator("points")
    @classmethod
    def _points_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("RubricItem.points 必须大于 0")
        return v


class JudgeRubricItem(BaseModel):
    """LLM Judge 评分项。

    与 RubricItem 不同，LLM Judge 评分项不指定 eval_fn，
    而是提供自然语言的评分标准 (criteria)，由 LLM 判断是否通过。

    Attributes:
        name: 评分项名称。
        points: 分值，必须大于 0。
        criteria: 自然语言评分标准（LLM 据此判断）。
        model: 使用的 LLM 模型名（默认 gpt-4o）。
    """

    name: str
    points: float
    criteria: str
    model: str = "gpt-4o"

    @field_validator("points")
    @classmethod
    def _points_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("JudgeRubricItem.points 必须大于 0")
        return v


class UserAgentConfig(BaseModel):
    """多轮对话中模拟用户的配置。

    Attributes:
        persona: 用户人设描述（LLM 据此扮演用户）。
        max_rounds: 最大对话轮数。
        system_prompt_suffix: 附加到用户 LLM 系统提示的后缀。
        initial_message: 用户的第一条消息（如果为空则使用 task.prompt）。
        success_criteria: 对话成功的判定标准（自然语言描述）。
    """

    persona: str = "一个普通用户，会根据 Agent 的回复进行追问和澄清。"
    max_rounds: int = 5
    system_prompt_suffix: str = ""
    initial_message: str = ""
    success_criteria: str = "Agent 成功完成了用户的需求。"


class Task(BaseModel):
    """评测任务。

    v2: 新增 judge_rubric 字段，支持规则 + LLM Judge 混合评分。
    v3: 新增 mode / user_agent 字段，支持多轮对话评测。

    Attributes:
        task_id: 任务唯一 ID，建议格式 {dimension}_{编号}。
        dimension: 所属维度。
        sub_dimension: 所属子维度。
        difficulty: 难度，easy / medium / hard。
        prompt: 给 Agent 的任务描述。
        tools: 可用工具列表，至少 1 个。
        expected_tool_calls: 预期工具调用序列，可选。
        rubric: 规则引擎评分标准列表，至少 1 个。
        judge_rubric: LLM Judge 评分标准列表（可选，与 rubric 并存）。
        mock_apis: Mock API 配置，{tool_name: response}。
        mode: 任务模式（single_turn / multi_turn）。
        user_agent: 多轮对话中模拟用户的配置（mode=multi_turn 时使用）。
    """

    task_id: str
    dimension: str
    sub_dimension: str
    difficulty: Difficulty
    prompt: str
    tools: list[ToolDef]
    expected_tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    rubric: list[RubricItem]
    judge_rubric: list[JudgeRubricItem] = Field(default_factory=list)
    mock_apis: dict[str, Any] = Field(default_factory=dict)
    mode: TaskMode = "single_turn"
    user_agent: UserAgentConfig | None = None

    @field_validator("tools")
    @classmethod
    def _tools_not_empty(cls, v: list[ToolDef]) -> list[ToolDef]:
        if not v:
            raise ValueError("Task.tools 不能为空")
        return v

    @field_validator("rubric")
    @classmethod
    def _rubric_not_empty(cls, v: list[RubricItem]) -> list[RubricItem]:
        if not v:
            raise ValueError("Task.rubric 不能为空")
        return v

    @property
    def max_score(self) -> float:
        """该任务的满分（规则 + LLM Judge 评分项分值之和）。"""
        rule_score = sum(item.points for item in self.rubric)
        judge_score = sum(item.points for item in self.judge_rubric)
        return rule_score + judge_score

    @property
    def has_judge_rubric(self) -> bool:
        """是否包含 LLM Judge 评分项。"""
        return len(self.judge_rubric) > 0

    @property
    def is_multi_turn(self) -> bool:
        """是否为多轮对话任务。"""
        return self.mode == "multi_turn"
