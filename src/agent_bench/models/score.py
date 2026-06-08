"""评分相关数据模型。

对应 docs/API_SPEC.md 第1.6-1.9节。

v2: 新增 TrialResult / TaskTrials / OrthogonalScores 支持 Pass^k 与三正交维度。
v3: ScoreDetail 新增 judge_type 字段，区分规则评分与 LLM Judge 评分。
"""

from __future__ import annotations

import statistics
from typing import Literal

from pydantic import BaseModel, Field, computed_field, model_validator

JudgeType = Literal["rule", "llm_judge"]


class ScoreDetail(BaseModel):
    """单个评分项的详情。

    Attributes:
        rubric_name: 对应的 RubricItem.name。
        points: 实际得分。
        max_points: 满分。
        passed: 是否达标。
        reason: 评分理由。
        judge_type: 评分方式（rule=规则引擎, llm_judge=LLM 评分）。
    """

    rubric_name: str
    points: float
    max_points: float
    passed: bool
    reason: str
    judge_type: JudgeType = "rule"

    @model_validator(mode="after")
    def _points_not_exceed_max(self) -> ScoreDetail:
        if self.points > self.max_points:
            raise ValueError("ScoreDetail.points 不能超过 max_points")
        return self


class ScoreReport(BaseModel):
    """单个任务的评分报告（单次 trial）。

    Attributes:
        task_id: 任务 ID。
        dimension: 所属维度。
        sub_dimension: 所属子维度。
        difficulty: 难度。
        scores: 各评分项详情。
        total_score: 总得分。
        max_score: 总满分。
    """

    task_id: str
    dimension: str
    sub_dimension: str
    difficulty: str
    scores: list[ScoreDetail] = Field(default_factory=list)
    total_score: float = 0.0
    max_score: float = 0.0

    @property
    def percentage(self) -> float:
        """该任务得分率（0-100）。"""
        if self.max_score == 0:
            return 0.0
        return round(self.total_score / self.max_score * 100, 2)

    @property
    def passed(self) -> bool:
        """该任务是否通过（得分率 >= 60%）。"""
        return self.percentage >= 60.0


# ---------------------------------------------------------------------------
# Pass^k: 多 trial 支持
# ---------------------------------------------------------------------------


class TrialResult(BaseModel):
    """单次 trial 的结果。

    Attributes:
        trial_id: 第几次试验（从 1 开始）。
        report: 该次试验的评分报告。
    """

    trial_id: int
    report: ScoreReport


class TaskTrials(BaseModel):
    """一个任务的多次 trial 汇总。

    Attributes:
        task_id: 任务 ID。
        dimension: 所属维度。
        sub_dimension: 所属子维度。
        difficulty: 难度。
        trials: 各次 trial 结果。
    """

    task_id: str
    dimension: str
    sub_dimension: str
    difficulty: str
    trials: list[TrialResult] = Field(default_factory=list)

    @computed_field
    @property
    def num_trials(self) -> int:
        return len(self.trials)

    @property
    def scores(self) -> list[float]:
        """各 trial 的得分率列表。"""
        return [t.report.percentage for t in self.trials]

    @computed_field
    @property
    def mean_score(self) -> float:
        """平均得分率。"""
        if not self.scores:
            return 0.0
        return round(statistics.mean(self.scores), 2)

    @computed_field
    @property
    def score_variance(self) -> float:
        """得分方差（衡量稳定性）。"""
        if len(self.scores) < 2:
            return 0.0
        return round(statistics.variance(self.scores), 4)

    @computed_field
    @property
    def pass_rate(self) -> float:
        """通过率：通过的 trial 数 / 总 trial 数（0-1）。"""
        if not self.trials:
            return 0.0
        passed = sum(1 for t in self.trials if t.report.passed)
        return round(passed / len(self.trials), 4)

    @computed_field
    @property
    def pass_k(self) -> bool:
        """Pass^k：所有 trial 是否全部通过。"""
        if not self.trials:
            return False
        return all(t.report.passed for t in self.trials)

    @computed_field
    @property
    def best_report(self) -> ScoreReport | None:
        """得分最高的 trial 报告。"""
        if not self.trials:
            return None
        return max(self.trials, key=lambda t: t.report.percentage).report

    @computed_field
    @property
    def max_score(self) -> float:
        """满分（取第一个 trial 的满分）。"""
        if not self.trials:
            return 0.0
        return self.trials[0].report.max_score


class DimensionScore(BaseModel):
    """维度汇总分数。

    Attributes:
        dimension: 维度 ID。
        score: 该维度总得分。
        max_score: 该维度总满分。
        percentage: 得分率（0-100）。
        task_count: 该维度下任务数。
    """

    dimension: str
    score: float
    max_score: float
    percentage: float
    task_count: int


# ---------------------------------------------------------------------------
# 三正交维度: Completion / Safety / Robustness
# ---------------------------------------------------------------------------

OrthogonalDimension = Literal["completion", "safety", "robustness"]

# 6 个细分维度 → 三正交维度的映射
DIMENSION_TO_ORTHOGONAL: dict[str, OrthogonalDimension] = {
    "tool_use": "completion",
    "reasoning": "completion",
    "memory": "completion",
    "instruction_following": "completion",
    "efficiency": "completion",
    "safety": "safety",
    "multi_agent": "completion",
}


class OrthogonalScore(BaseModel):
    """三正交维度之一的汇总分数。

    Attributes:
        dimension: completion / safety / robustness。
        score: 得分。
        max_score: 满分。
        percentage: 得分率（0-100）。
        description: 维度说明。
    """

    dimension: OrthogonalDimension
    score: float
    max_score: float
    percentage: float
    description: str = ""


class EvaluationResult(BaseModel):
    """完整评测结果。

    Attributes:
        agent_name: Agent 名称。
        agent_model: Agent 使用的模型。
        timestamp: ISO 8601 格式时间戳。
        num_trials: 每个任务的 trial 次数。
        task_trials: 各任务的多 trial 汇总。
        task_reports: 各任务评分报告（向后兼容，取 best_report）。
        dimension_scores: 各维度汇总分数。
        orthogonal_scores: 三正交维度汇总分数。
        overall_score: 总得分。
        overall_max_score: 总满分。
        overall_percentage: 总得分率（0-100）。
        overall_pass_k_rate: 所有任务的 Pass^k 通过率。
    """

    agent_name: str
    agent_model: str
    timestamp: str
    num_trials: int = 1
    task_trials: list[TaskTrials] = Field(default_factory=list)
    task_reports: list[ScoreReport] = Field(default_factory=list)
    dimension_scores: list[DimensionScore] = Field(default_factory=list)
    orthogonal_scores: list[OrthogonalScore] = Field(default_factory=list)
    overall_score: float = 0.0
    overall_max_score: float = 0.0
    overall_percentage: float = 0.0
    overall_pass_k_rate: float = 0.0
