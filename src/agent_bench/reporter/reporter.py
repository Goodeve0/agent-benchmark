"""报告生成器。

对应 docs/API_SPEC.md 第2.6节。

v2: 新增三正交维度表、Pass^k 展示、多 trial 明细。

职责：终端表格输出 + JSON 导出。
不做：HTML 报告（非 MVP）；图表。
"""

from __future__ import annotations

import json
from pathlib import Path

from rich.console import Console
from rich.table import Table

from agent_bench.models import EvaluationResult


class Reporter:
    """评测结果报告生成器。"""

    def __init__(self, console: Console | None = None) -> None:
        self._console = console or Console()

    def print_table(self, result: EvaluationResult) -> None:
        """在终端输出评测结果（概览 + 正交维度 + 细分维度 + 任务明细）。"""
        self._print_header(result)
        if result.orthogonal_scores:
            self._print_orthogonal_table(result)
        self._print_dimension_table(result)
        self._print_task_table(result)

    def export_json(self, result: EvaluationResult, output_path: str) -> None:
        """导出 JSON 格式的评测结果。

        Args:
            result: 评测结果。
            output_path: 输出文件路径（自动创建父目录）。
        """
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        # 导出时排除 metadata 中的 AuditLog 对象（不可 JSON 序列化）
        data = result.model_dump(exclude_none=True)
        # 清理 task_trials 中嵌套的 metadata
        for tt in data.get("task_trials", []):
            for trial in tt.get("trials", []):
                report = trial.get("report", {})
                report.pop("metadata", None)

        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)
        self._console.print(f"[green]✓[/green] 评测结果已导出: {path}")

    # ---- 内部方法 ----

    def _print_header(self, result: EvaluationResult) -> None:
        self._console.print()
        self._console.rule("[bold]AgentBench 评测报告")
        self._console.print(f"Agent  : [cyan]{result.agent_name}[/cyan]")
        self._console.print(f"模型   : [cyan]{result.agent_model}[/cyan]")
        self._console.print(f"时间   : {result.timestamp}")
        self._console.print(f"Trials : [cyan]{result.num_trials}[/cyan]")
        self._console.print(
            f"总分   : [bold yellow]{result.overall_score}/{result.overall_max_score}"
            f"[/bold yellow] ([bold]{result.overall_percentage}%[/bold])"
        )
        if result.num_trials > 1:
            pass_k_pct = round(result.overall_pass_k_rate * 100, 2)
            self._console.print(
                f"Pass^k : {self._color_pct(pass_k_pct)} "
                f"(k={result.num_trials}, 所有 trial 全部通过的任务比例)"
            )

    def _print_orthogonal_table(self, result: EvaluationResult) -> None:
        """三正交维度表。"""
        table = Table(title="三正交维度", show_lines=False)
        table.add_column("维度", style="cyan")
        table.add_column("描述")
        table.add_column("得分", justify="right")
        table.add_column("满分", justify="right")
        table.add_column("得分率", justify="right")
        for o in result.orthogonal_scores:
            dim_name = {
                "completion": "✅ 任务完成度",
                "safety": "🛡️ 安全性",
                "robustness": "🔄 鲁棒性",
            }.get(o.dimension, o.dimension)
            table.add_row(
                dim_name,
                o.description,
                str(o.score),
                str(o.max_score),
                self._color_pct(o.percentage),
            )
        self._console.print(table)

    def _print_dimension_table(self, result: EvaluationResult) -> None:
        """6 细分维度表。"""
        table = Table(title="细分维度得分", show_lines=False)
        table.add_column("维度", style="cyan")
        table.add_column("任务数", justify="right")
        table.add_column("得分", justify="right")
        table.add_column("满分", justify="right")
        table.add_column("得分率", justify="right")
        for d in result.dimension_scores:
            table.add_row(
                d.dimension,
                str(d.task_count),
                str(d.score),
                str(d.max_score),
                self._color_pct(d.percentage),
            )
        self._console.print(table)

    def _print_task_table(self, result: EvaluationResult) -> None:
        """任务明细表（多 trial 时显示额外列）。"""
        has_trials = result.num_trials > 1 and result.task_trials

        table = Table(title="任务明细", show_lines=False)
        table.add_column("任务ID", style="cyan")
        table.add_column("维度")
        table.add_column("难度")
        table.add_column("得分", justify="right")
        table.add_column("满分", justify="right")
        table.add_column("得分率", justify="right")

        if has_trials:
            table.add_column("Pass^k", justify="center")
            table.add_column("通过率", justify="right")
            table.add_column("方差", justify="right")

        if has_trials:
            for tt in result.task_trials:
                best = tt.best_report
                if best is None:
                    continue
                pass_k_icon = "[green]✓[/green]" if tt.pass_k else "[red]✗[/red]"
                table.add_row(
                    tt.task_id,
                    tt.dimension,
                    tt.difficulty,
                    str(best.total_score),
                    str(tt.max_score),
                    self._color_pct(tt.mean_score),
                    pass_k_icon,
                    f"{tt.pass_rate:.0%}",
                    str(tt.score_variance),
                )
        else:
            for r in result.task_reports:
                table.add_row(
                    r.task_id,
                    r.dimension,
                    r.difficulty,
                    str(r.total_score),
                    str(r.max_score),
                    self._color_pct(r.percentage),
                )

        self._console.print(table)

    @staticmethod
    def _color_pct(pct: float) -> str:
        """根据得分率上色。"""
        if pct >= 80:
            color = "green"
        elif pct >= 50:
            color = "yellow"
        else:
            color = "red"
        return f"[{color}]{pct}%[/{color}]"
