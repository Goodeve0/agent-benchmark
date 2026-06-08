"""评分引擎。

对应 docs/API_SPEC.md 第2.5节。

v2: 支持多 trial 评分、三正交维度聚合、Pass^k 计算。
v3: 支持规则引擎 + LLM Judge 混合评分。
v4: 支持自定义 grader.py（优先级高于内置规则）。

职责：逐项评分（规则引擎 + LLM Judge + 自定义 grader）；加权汇总；按维度聚合；正交维度聚合。
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from agent_bench.exceptions import ScoringError
from agent_bench.graders import AbstractGrader, load_grader
from agent_bench.models import (
    DIMENSION_TO_ORTHOGONAL,
    AgentTrace,
    DimensionScore,
    EvaluationResult,
    OrthogonalScore,
    RubricItem,
    ScoreDetail,
    ScoreReport,
    Task,
    TaskTrials,
    TrialResult,
)
from agent_bench.scorer.llm_judge import LLMJudge
from agent_bench.scorer.rules import get_rule

logger = logging.getLogger(__name__)


class Scorer:
    """混合评分引擎：自定义 grader / 规则引擎 / LLM Judge。

    评分优先级：
    1. 自定义 grader.py（如果存在）→ 完全由 grader 控制评分
    2. 内置规则引擎（rubric）+ LLM Judge（judge_rubric）→ 混合评分
    """

    def __init__(
        self,
        llm_judge: LLMJudge | None = None,
        spec_dir: str | Path | None = None,
    ) -> None:
        """
        Args:
            llm_judge: LLM Judge 实例。为 None 时只使用规则引擎评分。
            spec_dir: 任务规范目录（用于查找自定义 grader.py）。
        """
        self._llm_judge = llm_judge
        self._spec_dir = Path(spec_dir) if spec_dir else None
        self._grader_cache: dict[str, AbstractGrader | None] = {}

    # ------------------------------------------------------------------ #
    # 单任务 / 单 trial 评分
    # ------------------------------------------------------------------ #

    async def score_task(self, trace: AgentTrace, task: Task) -> ScoreReport:
        """对单个任务的执行轨迹评分。

        评分优先级：
        1. 自定义 grader.py（如果存在）→ 完全由 grader 控制
        2. 内置规则引擎（rubric）+ LLM Judge（judge_rubric）

        Args:
            trace: Agent 执行轨迹。
            task: 原始任务。

        Returns:
            ScoreReport。
        """
        # 优先级 1: 自定义 grader
        grader = self._get_grader(task.task_id)
        if grader is not None:
            logger.info(f"使用自定义 grader 评分: {task.task_id}")
            return await grader.grade(trace, task)

        # 优先级 2: 内置规则 + LLM Judge
        details: list[ScoreDetail] = []

        # 2a. 规则引擎评分
        for item in task.rubric:
            details.append(self._score_item(trace, item))

        # 2b. LLM Judge 评分（如果有 judge_rubric 且 llm_judge 可用）
        if task.has_judge_rubric and self._llm_judge is not None:
            for judge_item in task.judge_rubric:
                detail = await self._llm_judge.judge_item(
                    trace, judge_item, task_prompt=task.prompt
                )
                details.append(detail)
        elif task.has_judge_rubric and self._llm_judge is None:
            # 有 judge_rubric 但没有 LLM Judge → 记 0 分并提示
            for judge_item in task.judge_rubric:
                details.append(
                    ScoreDetail(
                        rubric_name=judge_item.name,
                        points=0.0,
                        max_points=judge_item.points,
                        passed=False,
                        reason="LLM Judge 未启用，无法评分。使用 --judge 参数启用。",
                        judge_type="llm_judge",
                    )
                )

        total = sum(d.points for d in details)
        return ScoreReport(
            task_id=task.task_id,
            dimension=task.dimension,
            sub_dimension=task.sub_dimension,
            difficulty=task.difficulty,
            scores=details,
            total_score=round(total, 4),
            max_score=task.max_score,
        )

    # ------------------------------------------------------------------ #
    # 同步评分（向后兼容，仅规则引擎）
    # ------------------------------------------------------------------ #

    def score_task_sync(self, trace: AgentTrace, task: Task) -> ScoreReport:
        """同步版本的 score_task（仅规则引擎，不调用 LLM Judge）。

        用于向后兼容和不需要 LLM Judge 的场景。
        """
        details: list[ScoreDetail] = []
        for item in task.rubric:
            details.append(self._score_item(trace, item))

        total = sum(d.points for d in details)
        return ScoreReport(
            task_id=task.task_id,
            dimension=task.dimension,
            sub_dimension=task.sub_dimension,
            difficulty=task.difficulty,
            scores=details,
            total_score=round(total, 4),
            max_score=task.max_score,
        )

    # ------------------------------------------------------------------ #
    # 多 trial 评分
    # ------------------------------------------------------------------ #

    async def score_trials(
        self,
        traces: list[AgentTrace],
        task: Task,
    ) -> TaskTrials:
        """对同一任务的多次 trial 逐一评分，汇总为 TaskTrials。

        Args:
            traces: 同一任务的 N 次执行轨迹。
            task: 原始任务。

        Returns:
            TaskTrials（包含各 trial 评分 + pass_k / mean_score 等聚合指标）。
        """
        trial_results: list[TrialResult] = []
        for i, trace in enumerate(traces, start=1):
            report = await self.score_task(trace, task)
            trial_results.append(TrialResult(trial_id=i, report=report))

        return TaskTrials(
            task_id=task.task_id,
            dimension=task.dimension,
            sub_dimension=task.sub_dimension,
            difficulty=task.difficulty,
            trials=trial_results,
        )

    # ------------------------------------------------------------------ #
    # 批量评分（向后兼容）
    # ------------------------------------------------------------------ #

    def score_evaluation(
        self,
        traces: list[AgentTrace],
        tasks: list[Task],
    ) -> list[ScoreReport]:
        """批量评分（单 trial 模式，仅规则引擎，向后兼容）。

        Args:
            traces: 与 tasks 一一对应的执行轨迹。
            tasks: 原始任务列表。

        Raises:
            ScoringError: traces 与 tasks 数量不一致。
        """
        if len(traces) != len(tasks):
            raise ScoringError(
                f"traces 与 tasks 数量不一致: {len(traces)} != {len(tasks)}"
            )
        return [self.score_task_sync(trace, task) for trace, task in zip(traces, tasks, strict=False)]

    # ------------------------------------------------------------------ #
    # 维度聚合
    # ------------------------------------------------------------------ #

    def aggregate_by_dimension(
        self,
        reports: list[ScoreReport],
    ) -> list[DimensionScore]:
        """按 6 个细分维度汇总分数。"""
        score_map: dict[str, float] = defaultdict(float)
        max_map: dict[str, float] = defaultdict(float)
        count_map: dict[str, int] = defaultdict(int)

        for r in reports:
            score_map[r.dimension] += r.total_score
            max_map[r.dimension] += r.max_score
            count_map[r.dimension] += 1

        result: list[DimensionScore] = []
        for dim in sorted(score_map.keys()):
            max_score = max_map[dim]
            pct = round(score_map[dim] / max_score * 100, 2) if max_score else 0.0
            result.append(
                DimensionScore(
                    dimension=dim,
                    score=round(score_map[dim], 4),
                    max_score=round(max_score, 4),
                    percentage=pct,
                    task_count=count_map[dim],
                )
            )
        return result

    def aggregate_orthogonal(
        self,
        dimension_scores: list[DimensionScore],
        task_trials: list[TaskTrials],
    ) -> list[OrthogonalScore]:
        """将 6 细分维度聚合为 3 正交维度。

        - Completion: 聚合 tool_use / reasoning / memory / instruction_following / efficiency
        - Safety: 聚合 safety
        - Robustness: 由 Pass^k 通过率计算（不依赖细分维度分数）

        Args:
            dimension_scores: 6 个细分维度的汇总分数。
            task_trials: 各任务的多 trial 汇总（用于计算 Robustness）。

        Returns:
            3 个 OrthogonalScore。
        """
        # 按正交维度分组聚合
        ortho_score: dict[str, float] = defaultdict(float)
        ortho_max: dict[str, float] = defaultdict(float)

        for ds in dimension_scores:
            ortho_dim = DIMENSION_TO_ORTHOGONAL.get(ds.dimension)
            if ortho_dim is None:
                ortho_dim = "completion"
            ortho_score[ortho_dim] += ds.score
            ortho_max[ortho_dim] += ds.max_score

        # Completion
        comp_max = ortho_max.get("completion", 0.0)
        comp_score = ortho_score.get("completion", 0.0)
        comp_pct = round(comp_score / comp_max * 100, 2) if comp_max else 0.0

        # Safety
        safe_max = ortho_max.get("safety", 0.0)
        safe_score = ortho_score.get("safety", 0.0)
        safe_pct = round(safe_score / safe_max * 100, 2) if safe_max else 0.0

        # Robustness: 基于 Pass^k 通过率
        if task_trials:
            pass_k_count = sum(1 for tt in task_trials if tt.pass_k)
            robustness_pct = round(pass_k_count / len(task_trials) * 100, 2)
        else:
            robustness_pct = 0.0

        return [
            OrthogonalScore(
                dimension="completion",
                score=round(comp_score, 4),
                max_score=round(comp_max, 4),
                percentage=comp_pct,
                description="Agent 是否正确完成了任务目标",
            ),
            OrthogonalScore(
                dimension="safety",
                score=round(safe_score, 4),
                max_score=round(safe_max, 4),
                percentage=safe_pct,
                description="Agent 是否避免了有害、越权或不安全的操作",
            ),
            OrthogonalScore(
                dimension="robustness",
                score=robustness_pct,
                max_score=100.0,
                percentage=robustness_pct,
                description="Agent 在多次试验中是否表现稳定（Pass^k 通过率）",
            ),
        ]

    # ------------------------------------------------------------------ #
    # 构建完整评测结果
    # ------------------------------------------------------------------ #

    def build_result(
        self,
        agent_info: dict,
        task_trials_list: list[TaskTrials],
        num_trials: int = 1,
    ) -> EvaluationResult:
        """将多 trial 评分结果汇总为完整的 EvaluationResult。

        Args:
            agent_info: 来自 adapter.get_agent_info() 的元信息。
            task_trials_list: 各任务的多 trial 汇总。
            num_trials: 每个任务的 trial 次数。

        Returns:
            EvaluationResult（含维度汇总、正交维度、Pass^k）。
        """
        # 取每个任务的 best_report 作为代表性报告
        best_reports: list[ScoreReport] = []
        for tt in task_trials_list:
            best = tt.best_report
            if best is not None:
                best_reports.append(best)

        # 6 细分维度聚合
        dimension_scores = self.aggregate_by_dimension(best_reports)

        # 3 正交维度聚合
        orthogonal_scores = self.aggregate_orthogonal(
            dimension_scores, task_trials_list
        )

        # 总分（基于 best_report）
        overall = sum(r.total_score for r in best_reports)
        overall_max = sum(r.max_score for r in best_reports)
        pct = round(overall / overall_max * 100, 2) if overall_max else 0.0

        # Pass^k 通过率
        if task_trials_list:
            pass_k_count = sum(1 for tt in task_trials_list if tt.pass_k)
            pass_k_rate = round(pass_k_count / len(task_trials_list), 4)
        else:
            pass_k_rate = 0.0

        return EvaluationResult(
            agent_name=agent_info.get("name", "unknown"),
            agent_model=agent_info.get("model", "unknown"),
            timestamp=datetime.now(timezone.utc).isoformat(),
            num_trials=num_trials,
            task_trials=task_trials_list,
            task_reports=best_reports,
            dimension_scores=dimension_scores,
            orthogonal_scores=orthogonal_scores,
            overall_score=round(overall, 4),
            overall_max_score=round(overall_max, 4),
            overall_percentage=pct,
            overall_pass_k_rate=pass_k_rate,
        )

    # ------------------------------------------------------------------ #
    # 向后兼容: 从单 trial 报告构建结果
    # ------------------------------------------------------------------ #

    def build_result_from_reports(
        self,
        agent_info: dict,
        reports: list[ScoreReport],
    ) -> EvaluationResult:
        """从单 trial 报告构建 EvaluationResult（向后兼容）。

        将每个 ScoreReport 包装为单 trial 的 TaskTrials，
        然后调用 build_result()。
        """
        task_trials_list: list[TaskTrials] = []
        for report in reports:
            tt = TaskTrials(
                task_id=report.task_id,
                dimension=report.dimension,
                sub_dimension=report.sub_dimension,
                difficulty=report.difficulty,
                trials=[TrialResult(trial_id=1, report=report)],
            )
            task_trials_list.append(tt)

        return self.build_result(agent_info, task_trials_list, num_trials=1)

    # ------------------------------------------------------------------ #
    # 内部方法
    # ------------------------------------------------------------------ #

    def _score_item(self, trace: AgentTrace, item: RubricItem) -> ScoreDetail:
        """对单个评分项评分（规则引擎）。"""
        rule = get_rule(item.eval_fn) if item.eval_fn else None

        if rule is None:
            reason = (
                f"无评分规则（eval_fn={item.eval_fn!r}），需人工复核"
                if item.eval_fn
                else "未指定 eval_fn，无法自动评分"
            )
            return ScoreDetail(
                rubric_name=item.name,
                points=0.0,
                max_points=item.points,
                passed=False,
                reason=reason,
                judge_type="rule",
            )

        try:
            passed, reason = rule(trace, item.args)
        except Exception as e:
            return ScoreDetail(
                rubric_name=item.name,
                points=0.0,
                max_points=item.points,
                passed=False,
                reason=f"评分规则执行异常: {e}",
                judge_type="rule",
            )

        return ScoreDetail(
            rubric_name=item.name,
            points=item.points if passed else 0.0,
            max_points=item.points,
            passed=passed,
            reason=reason,
            judge_type="rule",
        )

    def _get_grader(self, task_id: str) -> AbstractGrader | None:
        """获取任务的自定义 grader（带缓存）。"""
        if self._spec_dir is None:
            return None

        if task_id in self._grader_cache:
            return self._grader_cache[task_id]

        # 从 task_id 推断任务目录（如 tool_use_001 → specs/tasks/tool_use/）
        parts = task_id.rsplit("_", 1)
        if len(parts) == 2:
            dim_dir = self._spec_dir / parts[0]
        else:
            dim_dir = self._spec_dir

        grader = load_grader(task_id, dim_dir) if dim_dir.exists() else None
        self._grader_cache[task_id] = grader
        return grader
