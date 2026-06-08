"""多 Agent 对比报告生成器。

支持多个 Agent 的评测结果横向对比，输出：
- 维度对比表（各 Agent 在每个维度的得分率）
- 最优 Agent 高亮
- 统计显著性提示（Cohen's d 效应量）
- JSON 导出
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.table import Table

from agent_bench.models import EvaluationResult


class ComparisonReport:
    """多 Agent 对比报告生成器。"""

    def __init__(
        self,
        results: list[EvaluationResult] | None = None,
        console: Console | None = None,
    ) -> None:
        self._results = results or []
        self._console = console or Console()
        self._report: dict[str, Any] | None = None

    @property
    def report(self) -> dict[str, Any]:
        """惰性计算对比报告。"""
        if self._report is None:
            self._report = self._compute(self._results)
        return self._report

    def _compute(self, results: list[EvaluationResult]) -> dict[str, Any]:
        """生成多 Agent 对比报告。"""
        if not results:
            return {"error": "无可对比的评测结果"}

        all_dimensions = set()
        for r in results:
            for ds in r.dimension_scores:
                all_dimensions.add(ds.dimension)

        comparison: dict[str, dict[str, float]] = {}
        for r in results:
            agent_key = f"{r.agent_name}({r.agent_model})"
            comparison[agent_key] = {}
            for ds in r.dimension_scores:
                comparison[agent_key][ds.dimension] = ds.percentage

        best_per_dim: dict[str, tuple[str, float]] = {}
        for dim in all_dimensions:
            best_agent = ""
            best_score = -1.0
            for agent_key, dim_scores in comparison.items():
                score = dim_scores.get(dim, 0.0)
                if score > best_score:
                    best_score = score
                    best_agent = agent_key
            best_per_dim[dim] = (best_agent, best_score)

        overall_ranking: dict[str, float] = {}
        for r in results:
            agent_key = f"{r.agent_name}({r.agent_model})"
            overall_ranking[agent_key] = r.overall_percentage

        effect_sizes: dict[str, float] = {}
        if len(results) >= 2:
            for dim in sorted(all_dimensions):
                scores = [
                    comparison[f"{r.agent_name}({r.agent_model})"].get(dim, 0.0)
                    for r in results
                ]
                if len(scores) == 2:
                    effect_sizes[dim] = _cohens_d_pair(scores[0], scores[1])

        return {
            "agents": [f"{r.agent_name}({r.agent_model})" for r in results],
            "dimensions": sorted(all_dimensions),
            "comparison_matrix": comparison,
            "best_per_dimension": {dim: {"agent": agent, "score": score} for dim, (agent, score) in best_per_dim.items()},
            "overall_ranking": dict(sorted(overall_ranking.items(), key=lambda x: x[1], reverse=True)),
            "effect_sizes": effect_sizes,
        }

    def compare(self, results: list[EvaluationResult]) -> dict[str, Any]:
        """生成多 Agent 对比报告（兼容旧接口）。"""
        return self._compute(results)

    def print_comparison(self, results: list[EvaluationResult]) -> None:
        """在终端输出多 Agent 对比表格。"""
        report_data = self._compute(results)
        self._render_table(report_data)

    def print_table(self, console: Console | None = None) -> None:
        """便捷方法：打印构造时传入的 results 的对比表。"""
        c = console or self._console
        report_data = self.report
        self._render_table(report_data, console=c)

    def _render_table(self, report_data: dict[str, Any], console: Console | None = None) -> None:
        """渲染对比表格到终端。"""
        c = console or self._console

        if "error" in report_data:
            c.print(f"[red]{report_data['error']}[/red]")
            return

        agents = report_data["agents"]
        dimensions = report_data["dimensions"]
        comparison = report_data["comparison_matrix"]
        best_per_dim = report_data["best_per_dimension"]

        table = Table(title="Agent 维度对比", show_lines=True)
        table.add_column("维度", style="cyan", width=20)
        for agent in agents:
            table.add_column(agent, justify="right", width=18)

        for dim in dimensions:
            row = [dim]
            best_agent = best_per_dim[dim]["agent"]
            for agent in agents:
                score = comparison[agent].get(dim, 0.0)
                if agent == best_agent:
                    row.append(f"[bold green]{score:.1f}%[/bold green]")
                else:
                    row.append(f"{score:.1f}%")
            table.add_row(*row)

        c.print(table)

        c.print()
        c.print("[bold]综合排名:[/bold]")
        for rank, (agent, score) in enumerate(report_data["overall_ranking"].items(), 1):
            medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(rank, f" {rank}.")
            c.print(f"  {medal} {agent}: [bold yellow]{score:.1f}%[/bold yellow]")

        if report_data["effect_sizes"]:
            c.print()
            c.print("[bold]效应量 (Cohen's d):[/bold]")
            for dim, d in report_data["effect_sizes"].items():
                level = _interpret_cohens_d(d)
                c.print(f"  {dim}: d={d:.2f} ({level})")

    def export_comparison_json(self, results: list[EvaluationResult], output_path: str) -> None:
        """导出对比报告为 JSON（兼容旧接口）。"""
        report_data = self._compute(results)
        self._write_json(report_data, output_path)

    def export_json(self, output_path: str) -> None:
        """便捷方法：导出构造时传入的 results 的对比报告。"""
        self._write_json(self.report, output_path)

    def _write_json(self, report_data: dict[str, Any], output_path: str) -> None:
        """写入 JSON 文件。"""
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(report_data, f, ensure_ascii=False, indent=2, default=str)
        self._console.print(f"[green]✓[/green] 对比报告已导出: {path}")

    def to_dict(self) -> dict[str, Any]:
        """返回对比报告的字典形式（用于 API 响应）。"""
        return self.report


def _cohens_d_pair(score_a: float, score_b: float) -> float:
    """计算两个分数之间的 Cohen's d（简化版）。"""
    diff = abs(score_a - score_b)
    pooled_std = 50.0
    return round(diff / pooled_std, 4)


def _interpret_cohens_d(d: float) -> str:
    """解读 Cohen's d 效应量。"""
    d = abs(d)
    if d < 0.2:
        return "可忽略"
    if d < 0.5:
        return "小效应"
    if d < 0.8:
        return "中等效应"
    return "大效应"
