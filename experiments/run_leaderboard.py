"""
多 Agent Leaderboard 生成脚本

对多个 Agent（mock、gpt-4o-mini、gpt-4o 等）跑全量 benchmark，
生成标准化的 Leaderboard JSON，供 Web 前端渲染。

用法：
  # Mock 模式（无需 API Key，生成演示数据）
  python experiments/run_leaderboard.py --mock-only

  # 真实模式（需要 OPENAI_API_KEY）
  OPENAI_API_KEY=sk-xxx python experiments/run_leaderboard.py

  # 指定 agent 列表
  OPENAI_API_KEY=sk-xxx python experiments/run_leaderboard.py --agents mock,gpt-4o-mini,gpt-4o
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from agent_bench.adapters import get_adapter
from agent_bench.loader import TaskLoader
from agent_bench.runner import EvalRunner
from agent_bench.scorer import Scorer


DIMENSION_LABELS = {
    "tool_use": "工具使用",
    "reasoning": "多步推理",
    "memory": "记忆能力",
    "instruction_following": "指令遵循",
    "efficiency": "执行效率",
    "safety": "安全性",
}


async def run_agent(
    agent_name: str,
    tasks: list,
    scorer: Scorer,
    num_trials: int = 1,
    model: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
) -> dict:
    """对单个 Agent 跑全量 benchmark，返回结果。"""
    print(f"\n  运行 Agent：{agent_name}")

    if agent_name == "mock":
        adapter = get_adapter("mock")
    elif agent_name in ("gpt-4o", "gpt-4o-mini", "gpt-3.5-turbo"):
        adapter = get_adapter("raw_api", model=agent_name, api_key=api_key, base_url=base_url)
    else:
        adapter = get_adapter(agent_name, model=model, api_key=api_key, base_url=base_url)

    runner = EvalRunner(adapter=adapter, scorer=scorer, num_trials=num_trials)

    all_reports = []
    dim_scores: dict[str, list[float]] = {dim: [] for dim in DIMENSION_LABELS}

    for task in tasks:
        print(f"    [{task.task_id}]", end="", flush=True)
        try:
            result = await runner.run_task(task)
            report = result.best_report if result.best_report else result.task_reports[0]
            pct = report.total_score / report.max_score if report.max_score else 0
            all_reports.append({
                "task_id": task.task_id,
                "dimension": task.dimension,
                "score": report.total_score,
                "max": report.max_score,
                "pct": round(pct, 4),
                "passed": report.passed,
                "pass_k": result.pass_k if hasattr(result, "pass_k") else report.passed,
            })
            if task.dimension in dim_scores:
                dim_scores[task.dimension].append(pct)
            print(f" {'✓' if report.passed else '✗'} {pct:.0%}", end="")
        except Exception as e:
            print(f" ✗ (error: {e})", end="")
            all_reports.append({
                "task_id": task.task_id,
                "dimension": task.dimension,
                "score": 0, "max": 100, "pct": 0,
                "passed": False, "pass_k": False,
            })
        print()

    # 计算维度得分
    dim_summary = {}
    for dim, scores in dim_scores.items():
        if scores:
            dim_summary[dim] = round(sum(scores) / len(scores), 4)
        else:
            dim_summary[dim] = None

    # 计算总分
    valid = [r for r in all_reports if r["max"] > 0]
    overall = sum(r["score"] for r in valid) / sum(r["max"] for r in valid) if valid else 0
    pass_rate = sum(1 for r in valid if r["passed"]) / len(valid) if valid else 0
    pass_k_rate = sum(1 for r in valid if r["pass_k"]) / len(valid) if valid else 0

    return {
        "agent": agent_name,
        "model": model or agent_name,
        "overall": round(overall, 4),
        "pass_rate": round(pass_rate, 4),
        "pass_k_rate": round(pass_k_rate, 4),
        "dimension_scores": dim_summary,
        "task_details": all_reports,
    }


async def main():
    parser = argparse.ArgumentParser(description="多 Agent Leaderboard 生成")
    parser.add_argument("--specs-dir", default="specs/tasks")
    parser.add_argument("--output", default="results/leaderboard.json")
    parser.add_argument("--agents", default="mock", help="agent 列表，逗号分隔")
    parser.add_argument("--mock-only", action="store_true", help="只跑 mock agent")
    parser.add_argument("--trials", type=int, default=1)
    parser.add_argument("--base-url", default=None)
    args = parser.parse_args()

    api_key = os.environ.get("OPENAI_API_KEY")
    agent_list = ["mock"] if args.mock_only else args.agents.split(",")

    if any(a != "mock" for a in agent_list) and not api_key:
        print("⚠️  非 mock agent 需要设置 OPENAI_API_KEY")
        sys.exit(1)

    print("=" * 60)
    print("AgentBench Leaderboard 生成")
    print("=" * 60)

    loader = TaskLoader(specs_dir=args.specs_dir)
    tasks = loader.load_all()
    scorer = Scorer(spec_dir=args.specs_dir)
    print(f"\n加载任务数：{len(tasks)}")
    print(f"Agent 列表：{agent_list}")

    leaderboard = []
    for agent in agent_list:
        result = await run_agent(
            agent_name=agent,
            tasks=tasks,
            scorer=scorer,
            num_trials=args.trials,
            api_key=api_key,
            base_url=args.base_url,
        )
        leaderboard.append(result)

    # 按总分降序
    leaderboard.sort(key=lambda x: x["overall"], reverse=True)

    output = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "num_tasks": len(tasks),
        "num_agents": len(leaderboard),
        "leaderboard": leaderboard,
    }

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print("\n" + "=" * 60)
    print("Leaderboard 排名")
    print("=" * 60)
    for i, entry in enumerate(leaderboard, 1):
        print(f"  #{i} {entry['agent']:20s}  总分:{entry['overall']:.1%}  "
              f"通过率:{entry['pass_rate']:.1%}  Pass^k:{entry['pass_k_rate']:.1%}")

    print(f"\n✓ 报告已保存：{args.output}")


if __name__ == "__main__":
    asyncio.run(main())
