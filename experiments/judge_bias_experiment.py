"""
LLM-as-Judge 偏差实验：规则引擎 vs LLM Judge 评分对比

实验目的：
  量化 LLM-as-Judge 的自我评分偏差（self-bias）。
  让同一套 Agent 执行轨迹分别通过规则引擎和 LLM Judge 评分，
  计算两种方式的差异和 Cohen's Kappa 一致性系数。

实验设计：
  1. 用 MockAdapter 生成固定的执行轨迹（deterministic）
  2. 对同一批 traces，分别用规则引擎和 LLM Judge（mock 模式）评分
  3. 如果有 OpenAI Key，则额外跑真实 LLM Judge
  4. 计算 Cohen's Kappa、pass rate 差异、置信度分布

用法：
  # 基础模式（无需 API Key，使用 Mock LLM Judge）
  python experiments/judge_bias_experiment.py

  # 真实 LLM Judge 模式
  OPENAI_API_KEY=sk-xxx python experiments/judge_bias_experiment.py --real-llm

  # 指定任务目录
  python experiments/judge_bias_experiment.py --specs-dir specs/tasks --output results/bias_report.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

# 确保 src 在 path 中
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from agent_bench.adapters import get_adapter
from agent_bench.loader import TaskLoader
from agent_bench.models import AgentTrace, JudgeRubricItem, ScoreDetail
from agent_bench.runner import EvalRunner
from agent_bench.sandbox import Sandbox
from agent_bench.scorer import Scorer
from agent_bench.scorer.llm_judge import LLMJudge


# ────────────────────────────────────────────────────────────────────────────
# Cohen's Kappa 计算
# ────────────────────────────────────────────────────────────────────────────

def cohen_kappa(labels_a: list[bool], labels_b: list[bool]) -> float:
    """计算两个评分器之间的 Cohen's Kappa 系数。

    Kappa = (Po - Pe) / (1 - Pe)
    - Po: 实际一致率
    - Pe: 期望一致率（随机）
    - Kappa = 1.0：完全一致
    - Kappa = 0.0：仅随机一致
    - Kappa < 0：低于随机水平

    解读标准（Landis & Koch, 1977）：
    - < 0.00: 差
    - 0.00–0.20: 轻微
    - 0.21–0.40: 尚可
    - 0.41–0.60: 中等
    - 0.61–0.80: 较好
    - 0.81–1.00: 几乎完美
    """
    if len(labels_a) != len(labels_b) or not labels_a:
        return 0.0

    n = len(labels_a)
    agree = sum(1 for a, b in zip(labels_a, labels_b) if a == b)
    po = agree / n

    pa_true = sum(labels_a) / n
    pb_true = sum(labels_b) / n
    pe = pa_true * pb_true + (1 - pa_true) * (1 - pb_true)

    if pe >= 1.0:
        return 1.0

    return round((po - pe) / (1 - pe), 4)


def kappa_interpretation(kappa: float) -> str:
    if kappa < 0:
        return "差（低于随机水平）"
    elif kappa < 0.20:
        return "轻微一致"
    elif kappa < 0.40:
        return "尚可"
    elif kappa < 0.60:
        return "中等"
    elif kappa < 0.80:
        return "较好"
    else:
        return "几乎完美"


# ────────────────────────────────────────────────────────────────────────────
# 实验核心逻辑
# ────────────────────────────────────────────────────────────────────────────

class JudgeBiasExperiment:
    """LLM Judge 偏差实验主类。"""

    def __init__(
        self,
        specs_dir: str = "specs/tasks",
        output_path: str = "results/bias_report.json",
        use_real_llm: bool = False,
        llm_model: str = "gpt-4o",
        openai_base_url: str | None = None,
        num_trials: int = 3,
    ):
        self.specs_dir = Path(specs_dir)
        self.output_path = Path(output_path)
        self.use_real_llm = use_real_llm
        self.llm_model = llm_model
        self.openai_base_url = openai_base_url
        self.num_trials = num_trials

    async def run(self) -> dict[str, Any]:
        """运行实验，返回完整报告。"""
        print("=" * 60)
        print("LLM-as-Judge 偏差实验")
        print("=" * 60)

        # 1. 加载所有任务
        loader = TaskLoader(specs_dir=str(self.specs_dir))
        tasks = loader.load_all()
        print(f"\n加载任务数：{len(tasks)}")

        if not tasks:
            print("⚠️  未找到任务，请确认 specs_dir 路径正确")
            return {}

        # 2. 初始化评分器
        rule_scorer = Scorer(spec_dir=self.specs_dir)
        llm_judge = LLMJudge(
            model=self.llm_model,
            mock_mode=not self.use_real_llm,
            api_key=os.environ.get("OPENAI_API_KEY"),
            base_url=self.openai_base_url,
        )
        mock_adapter = get_adapter("mock")

        # 3. 对每个任务跑 num_trials 次
        task_results = []
        rule_decisions: list[bool] = []
        llm_decisions: list[bool] = []

        for task in tasks:
            print(f"\n  任务：{task.task_id} ({task.dimension}/{task.sub_dimension})")
            trial_data = []

            for trial in range(self.num_trials):
                # 生成执行轨迹
                sandbox = Sandbox(mock_apis=task.mock_apis or {})
                trace: AgentTrace = await mock_adapter.run_task(
                    task_prompt=task.prompt,
                    tools=task.tools or [],
                    sandbox=sandbox,
                )
                audit_log = sandbox.get_audit_log(freeze=True)
                if trace.metadata is None:
                    trace.metadata = {}
                trace.metadata["audit_log"] = audit_log

                # 规则引擎评分
                rule_report = rule_scorer.score(task, trace)
                rule_pass = rule_report.passed

                # LLM Judge 评分（对 rubric 中每项都跑一遍）
                llm_details: list[ScoreDetail] = []
                for rubric_item in (task.rubric or []):
                    # 将 rubric 包装为 JudgeRubricItem 让 LLM 评分
                    judge_item = JudgeRubricItem(
                        name=rubric_item.name,
                        points=rubric_item.points,
                        criteria=rubric_item.criteria or rubric_item.name,
                    )
                    detail = await llm_judge.judge_item(
                        trace=trace,
                        item=judge_item,
                        task_prompt=task.prompt,
                    )
                    llm_details.append(detail)

                llm_score = sum(d.points for d in llm_details)
                llm_max = sum(d.max_points for d in llm_details)
                llm_pass = (llm_score / llm_max >= 0.6) if llm_max > 0 else False

                rule_decisions.append(rule_pass)
                llm_decisions.append(llm_pass)

                trial_data.append({
                    "trial": trial + 1,
                    "rule_score": rule_report.total_score,
                    "rule_max": rule_report.max_score,
                    "rule_pass": rule_pass,
                    "llm_score": llm_score,
                    "llm_max": llm_max,
                    "llm_pass": llm_pass,
                    "agree": rule_pass == llm_pass,
                })
                print(f"    Trial {trial + 1}: rule={'✓' if rule_pass else '✗'} "
                      f"({rule_report.total_score}/{rule_report.max_score})  "
                      f"llm={'✓' if llm_pass else '✗'} "
                      f"({llm_score:.0f}/{llm_max:.0f})")

            task_results.append({
                "task_id": task.task_id,
                "dimension": task.dimension,
                "sub_dimension": task.sub_dimension,
                "difficulty": task.difficulty,
                "trials": trial_data,
            })

        # 4. 汇总统计
        n = len(rule_decisions)
        kappa = cohen_kappa(rule_decisions, llm_decisions)

        rule_pass_rate = sum(rule_decisions) / n if n > 0 else 0
        llm_pass_rate = sum(llm_decisions) / n if n > 0 else 0
        agree_rate = sum(1 for a, b in zip(rule_decisions, llm_decisions) if a == b) / n if n > 0 else 0

        # 按维度统计
        dim_stats: dict[str, dict] = defaultdict(lambda: {
            "rule_pass": 0, "llm_pass": 0, "total": 0
        })
        for tr in task_results:
            dim = tr["dimension"]
            for trial in tr["trials"]:
                dim_stats[dim]["total"] += 1
                if trial["rule_pass"]:
                    dim_stats[dim]["rule_pass"] += 1
                if trial["llm_pass"]:
                    dim_stats[dim]["llm_pass"] += 1

        print("\n" + "=" * 60)
        print("实验结果汇总")
        print("=" * 60)
        print(f"  总评分次数：{n}")
        print(f"  规则引擎通过率：{rule_pass_rate:.1%}")
        print(f"  LLM Judge 通过率：{llm_pass_rate:.1%}")
        print(f"  通过率差值（LLM - 规则）：{(llm_pass_rate - rule_pass_rate):+.1%}")
        print(f"  评分一致率：{agree_rate:.1%}")
        print(f"  Cohen's Kappa：{kappa} （{kappa_interpretation(kappa)}）")
        print()
        print("  按维度分析：")
        for dim, stats in dim_stats.items():
            t = stats["total"]
            rpr = stats["rule_pass"] / t if t > 0 else 0
            lpr = stats["llm_pass"] / t if t > 0 else 0
            print(f"    {dim:25s}  rule={rpr:.0%}  llm={lpr:.0%}  diff={lpr-rpr:+.0%}")

        # 5. 构建报告
        report = {
            "experiment": "LLM-as-Judge vs Rule Engine Bias Analysis",
            "config": {
                "num_tasks": len(tasks),
                "num_trials_per_task": self.num_trials,
                "llm_model": self.llm_model if self.use_real_llm else "mock",
                "use_real_llm": self.use_real_llm,
            },
            "summary": {
                "total_evaluations": n,
                "rule_pass_rate": round(rule_pass_rate, 4),
                "llm_pass_rate": round(llm_pass_rate, 4),
                "pass_rate_diff": round(llm_pass_rate - rule_pass_rate, 4),
                "agreement_rate": round(agree_rate, 4),
                "cohens_kappa": kappa,
                "kappa_interpretation": kappa_interpretation(kappa),
                "finding": self._generate_finding(
                    rule_pass_rate, llm_pass_rate, kappa
                ),
            },
            "dimension_breakdown": {
                dim: {
                    "total": s["total"],
                    "rule_pass_rate": round(s["rule_pass"] / s["total"], 4) if s["total"] else 0,
                    "llm_pass_rate": round(s["llm_pass"] / s["total"], 4) if s["total"] else 0,
                }
                for dim, s in dim_stats.items()
            },
            "task_results": task_results,
        }

        # 6. 保存报告
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.output_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"\n✓ 报告已保存：{self.output_path}")

        return report

    def _generate_finding(
        self, rule_rate: float, llm_rate: float, kappa: float
    ) -> str:
        diff = llm_rate - rule_rate
        diff_pct = f"{abs(diff):.0%}"
        direction = "偏高" if diff > 0 else "偏低"
        kappa_str = kappa_interpretation(kappa)

        if abs(diff) < 0.05 and kappa >= 0.6:
            return (
                f"两种评分方式高度一致（Kappa={kappa}，{kappa_str}），"
                f"通过率差异仅 {diff_pct}，LLM Judge 偏差不显著。"
            )
        else:
            return (
                f"LLM Judge 通过率比规则引擎{direction} {diff_pct}，"
                f"Cohen's Kappa={kappa}（{kappa_str}），"
                f"两种评分方式存在{"显著" if abs(diff) >= 0.1 else ""}差异。"
                f"规则引擎评分具有更高确定性，避免了 LLM 评分的系统性偏差。"
            )


# ────────────────────────────────────────────────────────────────────────────
# CLI 入口
# ────────────────────────────────────────────────────────────────────────────

async def main():
    parser = argparse.ArgumentParser(description="LLM-as-Judge 偏差实验")
    parser.add_argument(
        "--specs-dir", default="specs/tasks",
        help="评测任务目录（默认：specs/tasks）"
    )
    parser.add_argument(
        "--output", default="results/bias_report.json",
        help="报告输出路径（默认：results/bias_report.json）"
    )
    parser.add_argument(
        "--real-llm", action="store_true",
        help="使用真实 LLM Judge（需要 OPENAI_API_KEY）"
    )
    parser.add_argument(
        "--model", default="gpt-4o",
        help="LLM Judge 模型名（默认：gpt-4o）"
    )
    parser.add_argument(
        "--base-url", default=None,
        help="OpenAI API Base URL（可选，用于接入其他兼容接口）"
    )
    parser.add_argument(
        "--trials", type=int, default=3,
        help="每个任务的 trial 次数（默认：3，用于 Pass^k 和稳定性分析）"
    )
    args = parser.parse_args()

    if args.real_llm and not os.environ.get("OPENAI_API_KEY"):
        print("⚠️  --real-llm 模式需要设置 OPENAI_API_KEY 环境变量")
        sys.exit(1)

    exp = JudgeBiasExperiment(
        specs_dir=args.specs_dir,
        output_path=args.output,
        use_real_llm=args.real_llm,
        llm_model=args.model,
        openai_base_url=args.base_url,
        num_trials=args.trials,
    )
    await exp.run()


if __name__ == "__main__":
    asyncio.run(main())
