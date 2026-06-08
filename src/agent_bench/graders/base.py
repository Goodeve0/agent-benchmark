"""AbstractGrader 基类。

自定义 grader 需继承此基类，实现 grade() 方法。
适用于复杂评分逻辑（如多步推理验证、输出结构化校验、业务规则校验等），
这些逻辑难以用 YAML 声明式规则表达。

用法示例:
    # specs/tasks/reasoning/grader.py
    from agent_bench.graders.base import AbstractGrader

    class Grader(AbstractGrader):
        async def grade(self, trace, task):
            details = []
            # 自定义评分逻辑...
            details.append(self.make_detail("步骤合理性", 30, True, "推理步骤合理"))
            return self.build_report(task, details)
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from agent_bench.models import AgentTrace, ScoreDetail, ScoreReport, Task


class AbstractGrader(ABC):
    """自定义 Grader 基类。

    子类必须实现 grade() 方法。
    提供 make_detail() 和 build_report() 辅助方法简化评分。
    """

    @abstractmethod
    async def grade(self, trace: AgentTrace, task: Task) -> ScoreReport:
        """对单个任务的执行轨迹评分。

        Args:
            trace: Agent 执行轨迹。
            task: 原始任务。

        Returns:
            ScoreReport。
        """
        ...

    # ------------------------------------------------------------------ #
    # 辅助方法
    # ------------------------------------------------------------------ #

    @staticmethod
    def make_detail(
        name: str,
        max_points: float,
        passed: bool,
        reason: str,
        judge_type: str = "rule",
    ) -> ScoreDetail:
        """快速构造一个 ScoreDetail。"""
        return ScoreDetail(
            rubric_name=name,
            points=max_points if passed else 0.0,
            max_points=max_points,
            passed=passed,
            reason=reason,
            judge_type=judge_type,
        )

    @staticmethod
    def build_report(task: Task, details: list[ScoreDetail]) -> ScoreReport:
        """从 ScoreDetail 列表构建 ScoreReport。"""
        total = sum(d.points for d in details)
        max_score = sum(d.max_points for d in details)
        return ScoreReport(
            task_id=task.task_id,
            dimension=task.dimension,
            sub_dimension=task.sub_dimension,
            difficulty=task.difficulty,
            scores=details,
            total_score=round(total, 4),
            max_score=max_score,
        )

    # ------------------------------------------------------------------ #
    # 常用评分辅助
    # ------------------------------------------------------------------ #

    @staticmethod
    def compute_robustness(pass_results: list[bool]) -> float:
        """计算鲁棒性分数（通过率）。

        Args:
            pass_results: 多次试验的 pass/fail 列表。

        Returns:
            通过率（0.0 - 1.0）。
        """
        if not pass_results:
            return 0.0
        return sum(pass_results) / len(pass_results)

    @staticmethod
    def check_response_substance(
        response: str,
        min_length: int = 20,
        required_keywords: list[str] | None = None,
    ) -> tuple[bool, str]:
        """检查回复是否有实质内容（非空洞回复）。

        Args:
            response: Agent 的最终回复。
            min_length: 最小长度要求。
            required_keywords: 必须包含的关键词。

        Returns:
            (是否通过, 理由)。
        """
        if not response or len(response.strip()) < min_length:
            return False, f"回复过短（{len(response.strip())} < {min_length}）"

        if required_keywords:
            missing = [kw for kw in required_keywords if kw not in response]
            if missing:
                return False, f"回复缺少关键词: {missing}"

        return True, f"回复有实质内容（长度={len(response.strip())}）"
