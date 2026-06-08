"""命令行入口。

对应 docs/API_SPEC.md 第4节。

v2: 新增 --trials / --parallel 参数，支持多 trial + 并行评测。
v3: 新增 --judge 参数，支持规则 + LLM Judge 混合评分。
v4: 新增 --graph 参数，支持 LangGraph 编排引擎；多轮对话任务自动识别。

命令:
    agent-bench run            运行评测
    agent-bench run-graph      使用 LangGraph 编排引擎运行评测
    agent-bench list-tasks     列出所有任务
    agent-bench list-dimensions 列出所有维度
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import typer
import yaml
from rich.console import Console
from rich.table import Table

from agent_bench.adapters import get_adapter
from agent_bench.exceptions import AgentBenchError
from agent_bench.loader import TaskLoader
from agent_bench.reporter import Reporter
from agent_bench.runner import EvalRunner
from agent_bench.scorer import LLMJudge, Scorer

app = typer.Typer(help="AgentBench — Agent 能力评测基准框架", add_completion=False)
console = Console()

DEFAULT_SPEC_DIR = "specs/tasks"
DEFAULT_DIMENSIONS_FILE = "specs/dimensions.yaml"


@app.command()
def run(
    agent: str = typer.Option("mock", help="适配器类型: mock | raw_api"),
    model: str = typer.Option("gpt-4o", help="模型名（raw_api 时使用）"),
    dimension: str | None = typer.Option(None, help="只评测指定维度"),
    task: str | None = typer.Option(None, help="只评测指定 task_id"),
    spec_dir: str = typer.Option(DEFAULT_SPEC_DIR, help="任务规范目录"),
    output: str | None = typer.Option(None, help="评测结果 JSON 输出路径"),
    max_steps: int = typer.Option(10, help="单任务最大步数"),
    timeout: int = typer.Option(60, help="单任务超时秒数"),
    trials: int = typer.Option(1, help="每个任务的 trial 次数（Pass^k 需要 k>=3）"),
    parallel: int = typer.Option(4, help="最大并行任务数"),
    judge: bool = typer.Option(False, help="启用 LLM Judge 混合评分"),
    judge_model: str = typer.Option("gpt-4o", help="LLM Judge 使用的模型"),
    judge_mock: bool = typer.Option(False, help="LLM Judge 使用 Mock 模式（不调用真实 LLM）"),
) -> None:
    """运行评测。"""
    try:
        loader = TaskLoader(spec_dir)
        if task:
            tasks = [loader.load_task_by_id(task)]
        elif dimension:
            tasks = loader.load_tasks_by_dimension(dimension)
        else:
            tasks = loader.load_all_tasks()
    except AgentBenchError as e:
        console.print(f"[red]任务加载失败:[/red] {e}")
        raise typer.Exit(code=1) from e

    if not tasks:
        console.print("[yellow]未找到匹配的评测任务[/yellow]")
        raise typer.Exit(code=1)

    try:
        adapter = _build_adapter(agent, model)
    except (ValueError, ImportError) as e:
        console.print(f"[red]适配器创建失败:[/red] {e}")
        raise typer.Exit(code=1) from e

    # 统计任务模式
    single_count = sum(1 for t in tasks if not t.is_multi_turn)
    multi_count = sum(1 for t in tasks if t.is_multi_turn)

    # 构建 LLM Judge（如果启用）
    llm_judge = None
    if judge or judge_mock:
        llm_judge = LLMJudge(model=judge_model, mock_mode=judge_mock)
        judge_label = f"mock({judge_model})" if judge_mock else judge_model
        console.print(f"LLM Judge: [cyan]{judge_label}[/cyan]")

    console.print(
        f"开始评测: agent=[cyan]{agent}[/cyan], "
        f"任务数=[cyan]{len(tasks)}[/cyan] "
        f"(单轮={single_count}, 多轮={multi_count}), "
        f"trials=[cyan]{trials}[/cyan], "
        f"parallel=[cyan]{parallel}[/cyan]"
    )

    runner = EvalRunner(
        adapter,
        max_steps=max_steps,
        timeout=timeout,
        num_trials=trials,
        max_parallel=parallel,
    )
    scorer = Scorer(llm_judge=llm_judge, spec_dir=spec_dir)

    if trials > 1:
        # 多 trial 模式：并行执行 + Pass^k 评分
        task_traces = asyncio.run(runner.run_evaluation_parallel(tasks))
        task_trials_list = []
        for t in tasks:
            traces = task_traces.get(t.task_id, [])
            tt = asyncio.run(scorer.score_trials(traces, t))
            task_trials_list.append(tt)
        result = scorer.build_result(
            adapter.get_agent_info(), task_trials_list, num_trials=trials
        )
    else:
        # 单 trial 模式
        traces = asyncio.run(runner.run_evaluation(tasks))
        if llm_judge is not None:
            # 混合评分模式（async）
            reports = asyncio.run(_score_all_async(scorer, traces, tasks))
        else:
            # 纯规则评分（sync，向后兼容）
            reports = scorer.score_evaluation(traces, tasks)
        result = scorer.build_result_from_reports(adapter.get_agent_info(), reports)

    reporter = Reporter(console)
    reporter.print_table(result)
    if output:
        reporter.export_json(result, output)


@app.command("run-graph")
def run_graph(
    agent: str = typer.Option("mock", help="适配器类型: mock | raw_api"),
    model: str = typer.Option("gpt-4o", help="模型名（raw_api 时使用）"),
    dimension: str | None = typer.Option(None, help="只评测指定维度"),
    task: str | None = typer.Option(None, help="只评测指定 task_id"),
    spec_dir: str = typer.Option(DEFAULT_SPEC_DIR, help="任务规范目录"),
    output: str | None = typer.Option(None, help="评测结果 JSON 输出路径"),
    max_steps: int = typer.Option(10, help="单任务最大步数"),
    timeout: int = typer.Option(60, help="单任务超时秒数"),
    trials: int = typer.Option(1, help="每个任务的 trial 次数"),
    parallel: int = typer.Option(4, help="最大并行任务数"),
    judge: bool = typer.Option(False, help="启用 LLM Judge 混合评分"),
    judge_model: str = typer.Option("gpt-4o", help="LLM Judge 使用的模型"),
    judge_mock: bool = typer.Option(False, help="LLM Judge 使用 Mock 模式"),
    checkpoint: str = typer.Option("memory", help="Checkpoint 后端: memory | file"),
    thread_id: str = typer.Option("default", help="线程 ID（用于断点续跑）"),
) -> None:
    """使用 LangGraph 编排引擎运行评测。

    将评测流程建模为有向图，支持：
    - 自动识别单轮/多轮任务并路由到不同执行路径
    - Checkpoint 断点续跑
    - 可视化执行流程
    """
    try:
        from agent_bench.graph import build_eval_graph, get_checkpointer, run_eval_graph
    except ImportError:
        console.print(
            "[red]LangGraph 未安装。[/red] 请运行: "
            "[cyan]pip install langgraph langchain-core[/cyan]"
        )
        raise typer.Exit(code=1)

    # 构建过滤条件
    task_filter = None
    if dimension or task:
        task_filter = {}
        if dimension:
            task_filter["dimension"] = dimension
        if task:
            task_filter["task_id"] = task

    # 构建适配器参数
    adapter_kwargs = {}
    if agent == "raw_api":
        adapter_kwargs["model"] = model

    console.print(
        f"[bold]LangGraph 编排模式[/bold]\n"
        f"  适配器: [cyan]{agent}[/cyan]\n"
        f"  Checkpoint: [cyan]{checkpoint}[/cyan]\n"
        f"  Thread ID: [cyan]{thread_id}[/cyan]\n"
        f"  Trials: [cyan]{trials}[/cyan]"
    )

    # 获取 checkpointer
    cp = get_checkpointer(checkpoint)

    # 运行
    final_state = asyncio.run(
        run_eval_graph(
            spec_dir=spec_dir,
            adapter_type=agent,
            adapter_kwargs=adapter_kwargs,
            num_trials=trials,
            max_steps=max_steps,
            timeout=timeout,
            max_parallel=parallel,
            task_filter=task_filter,
            judge_enabled=judge or judge_mock,
            judge_model=judge_model,
            judge_mock=judge_mock,
            user_agent_mock=True,
            checkpointer=cp,
            thread_id=thread_id,
        )
    )

    # 输出结果
    summary = final_state.get("summary", {})
    _print_graph_summary(summary)

    if output:
        import json
        with open(output, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2, default=str)
        console.print(f"\n结果已导出: [cyan]{output}[/cyan]")


def _print_graph_summary(summary: dict) -> None:
    """打印 LangGraph 评测结果摘要。"""
    console.print("\n[bold]═══ LangGraph 评测结果 ═══[/bold]\n")

    total = summary.get("total_tasks", 0)
    passed = summary.get("total_passed", 0)
    rate = summary.get("pass_rate", 0)
    pct = summary.get("overall_percentage", 0)

    console.print(f"  任务总数: [cyan]{total}[/cyan]")
    console.print(f"  通过数量: [green]{passed}[/green] / {total}")
    console.print(f"  通过率:   [{'green' if rate >= 0.6 else 'red'}]{rate:.1%}[/]")
    console.print(f"  总得分率: [{'green' if pct >= 60 else 'red'}]{pct:.1f}%[/]")

    # 任务明细表
    task_summaries = summary.get("task_summaries", [])
    if task_summaries:
        console.print()
        table = Table(title="任务明细")
        table.add_column("任务ID", style="cyan")
        table.add_column("维度")
        table.add_column("模式")
        table.add_column("得分", justify="right")
        table.add_column("满分", justify="right")
        table.add_column("得分率", justify="right")
        table.add_column("通过", justify="center")

        for ts in task_summaries:
            mode_icon = "🔄" if ts.get("mode") == "multi_turn" else "📝"
            pass_icon = "✅" if ts.get("passed") else "❌"
            pct_val = ts.get("percentage", 0)
            pct_style = "green" if pct_val >= 60 else "red"
            table.add_row(
                ts.get("task_id", ""),
                ts.get("dimension", ""),
                f"{mode_icon} {ts.get('mode', 'single_turn')}",
                f"{ts.get('score', 0):.1f}",
                f"{ts.get('max_score', 0):.1f}",
                f"[{pct_style}]{pct_val:.1f}%[/]",
                pass_icon,
            )
        console.print(table)

    # 错误信息
    errors = summary.get("errors", [])
    if errors:
        console.print(f"\n[red]错误 ({len(errors)}):[/red]")
        for err in errors:
            console.print(f"  • {err}")


async def _score_all_async(
    scorer: Scorer,
    traces: list,
    tasks: list,
) -> list:
    """异步批量评分（支持 LLM Judge）。"""
    from agent_bench.models import ScoreReport

    reports: list[ScoreReport] = []
    for trace, task in zip(traces, tasks):
        report = await scorer.score_task(trace, task)
        reports.append(report)
    return reports


@app.command("list-tasks")
def list_tasks(
    spec_dir: str = typer.Option(DEFAULT_SPEC_DIR, help="任务规范目录"),
) -> None:
    """列出所有可用评测任务。"""
    try:
        tasks = TaskLoader(spec_dir).load_all_tasks()
    except AgentBenchError as e:
        console.print(f"[red]任务加载失败:[/red] {e}")
        raise typer.Exit(code=1) from e

    table = Table(title=f"评测任务（共 {len(tasks)} 个）")
    table.add_column("任务ID", style="cyan")
    table.add_column("维度")
    table.add_column("子维度")
    table.add_column("难度")
    table.add_column("模式", justify="center")
    table.add_column("Judge", justify="center")
    for t in tasks:
        judge_icon = "✓" if t.has_judge_rubric else ""
        mode_icon = "🔄" if t.is_multi_turn else "📝"
        table.add_row(
            t.task_id, t.dimension, t.sub_dimension, t.difficulty,
            mode_icon, judge_icon,
        )
    console.print(table)


@app.command("list-dimensions")
def list_dimensions(
    dimensions_file: str = typer.Option(DEFAULT_DIMENSIONS_FILE, help="维度定义文件"),
) -> None:
    """列出所有评测维度（含三正交维度）。"""
    path = Path(dimensions_file)
    if not path.exists():
        console.print(f"[red]维度定义文件不存在:[/red] {path}")
        raise typer.Exit(code=1)

    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    # 正交维度表
    ortho_dims = data.get("orthogonal_dimensions", [])
    if ortho_dims:
        ortho_table = Table(title="三正交维度")
        ortho_table.add_column("维度ID", style="cyan")
        ortho_table.add_column("名称")
        ortho_table.add_column("描述")
        ortho_table.add_column("来源")
        for od in ortho_dims:
            maps_from = od.get("maps_from", [])
            computed = od.get("computed_from", "")
            source = ", ".join(maps_from) if maps_from else computed
            ortho_table.add_row(
                od.get("id", ""),
                od.get("name", ""),
                od.get("description", ""),
                source,
            )
        console.print(ortho_table)
        console.print()

    # 细分维度表
    table = Table(title="细分评测维度")
    table.add_column("维度ID", style="cyan")
    table.add_column("名称")
    table.add_column("权重", justify="right")
    table.add_column("正交维度")
    table.add_column("子维度")
    for dim in data.get("dimensions", []):
        subs = ", ".join(dim.get("sub_dimensions", []))
        table.add_row(
            dim.get("id", ""),
            dim.get("name", ""),
            str(dim.get("weight", "")),
            dim.get("orthogonal", ""),
            subs,
        )
    console.print(table)


# ---- 内部方法 ----


def _build_adapter(agent: str, model: str):
    """根据 CLI 参数构建适配器。"""
    if agent == "raw_api":
        return get_adapter("raw_api", model=model)
    return get_adapter(agent)


if __name__ == "__main__":
    app()
