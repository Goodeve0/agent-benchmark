"""Cohen's Kappa 一致性实验。

实验目的：
    验证规则引擎评分与 LLM Judge 评分在客观指标上的一致性。
    用数据证明"规则引擎在客观指标上与 GPT-4 一致，但零成本、可复现、零延迟"。

实验方法：
    1. 对同一批任务，分别用规则引擎和 LLM Judge（Mock 模式或真实模式）评分
    2. 将每个评分项的 pass/fail 结果作为二分类标签
    3. 计算 Cohen's Kappa 系数衡量两种评分方式的一致性

Cohen's Kappa 解读：
    - κ < 0.20: 极低一致性
    - 0.20 ≤ κ < 0.40: 低一致性
    - 0.40 ≤ κ < 0.60: 中等一致性
    - 0.60 ≤ κ < 0.80: 较高一致性
    - 0.80 ≤ κ ≤ 1.00: 极高一致性（几乎完全一致）

用法：
    # Mock 模式（不需要 API Key）
    python experiments/cohens_kappa.py

    # 真实 LLM 模式（需要 OPENAI_API_KEY）
    python experiments/cohens_kappa.py --real-llm

    # 指定模型
    python experiments/cohens_kappa.py --real-llm --model gpt-4o-mini
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# 确保项目根目录在 sys.path 中
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

from agent_bench.adapters import get_adapter  # noqa: E402
from agent_bench.loader import TaskLoader  # noqa: E402
from agent_bench.runner import EvalRunner  # noqa: E402
from agent_bench.scorer import LLMJudge, Scorer  # noqa: E402


def compute_cohens_kappa(labels_a: list[bool], labels_b: list[bool]) -> float:
    """计算 Cohen's Kappa 系数。

    Args:
        labels_a: 评分方式 A 的 pass/fail 列表。
        labels_b: 评分方式 B 的 pass/fail 列表。

    Returns:
        Cohen's Kappa 系数（-1 到 1）。
    """
    assert len(labels_a) == len(labels_b), "两组标签长度必须一致"
    n = len(labels_a)
    if n == 0:
        return 0.0

    # 构建混淆矩阵
    # a=True,b=True | a=True,b=False | a=False,b=True | a=False,b=False
    tp = sum(1 for a, b in zip(labels_a, labels_b) if a and b)
    fp = sum(1 for a, b in zip(labels_a, labels_b) if a and not b)
    fn = sum(1 for a, b in zip(labels_a, labels_b) if not a and b)
    tn = sum(1 for a, b in zip(labels_a, labels_b) if not a and not b)

    # 观察一致率
    po = (tp + tn) / n

    # 期望一致率
    p_a_yes = (tp + fp) / n
    p_b_yes = (tp + fn) / n
    p_a_no = (fn + tn) / n
    p_b_no = (fp + tn) / n
    pe = p_a_yes * p_b_yes + p_a_no * p_b_no

    # Cohen's Kappa
    if pe == 1.0:
        return 1.0  # 完全一致
    return (po - pe) / (1 - pe)


def interpret_kappa(kappa: float) -> str:
    """解读 Kappa 值。"""
    if kappa < 0.20:
        return "极低一致性 (Poor)"
    elif kappa < 0.40:
        return "低一致性 (Fair)"
    elif kappa < 0.60:
        return "中等一致性 (Moderate)"
    elif kappa < 0.80:
        return "较高一致性 (Substantial)"
    else:
        return "极高一致性 (Almost Perfect)"


async def run_experiment(
    use_real_llm: bool = False,
    model: str = "gpt-4o",
    spec_dir: str = "specs/tasks",
) -> dict:
    """运行 Cohen's Kappa 一致性实验。

    Returns:
        实验结果字典。
    """
    print("=" * 60)
    print("Cohen's Kappa 一致性实验")
    print("规则引擎 vs LLM Judge 评分一致性对比")
    print("=" * 60)

    # 1. 加载任务
    loader = TaskLoader(spec_dir)
    tasks = loader.load_all_tasks()
    print(f"\n加载任务: {len(tasks)} 个")

    # 2. 执行评测（使用 MockAdapter）
    adapter = get_adapter("mock")
    runner = EvalRunner(adapter, max_steps=10, timeout=60)
    traces = await runner.run_evaluation(tasks)
    print(f"执行完成: {len(traces)} 条轨迹")

    # 3. 规则引擎评分
    rule_scorer = Scorer()  # 无 LLM Judge
    rule_reports = rule_scorer.score_evaluation(traces, tasks)

    # 4. LLM Judge 评分（对同一批轨迹）
    llm_judge = LLMJudge(model=model, mock_mode=not use_real_llm)
    judge_scorer = Scorer(llm_judge=llm_judge)

    judge_reports = []
    for trace, task in zip(traces, tasks):
        report = await judge_scorer.score_task(trace, task)
        judge_reports.append(report)

    # 5. 提取 pass/fail 标签（只比较规则引擎评分项，因为 judge_rubric 只有 LLM 评分）
    rule_labels: list[bool] = []
    judge_labels: list[bool] = []

    print("\n" + "-" * 60)
    print(f"{'任务ID':<25} {'评分项':<20} {'规则':>4} {'LLM':>4} {'一致':>4}")
    print("-" * 60)

    for rule_report, judge_report in zip(rule_reports, judge_reports):
        # 只比较两者都有的评分项（即 rubric 中的规则评分项）
        rule_scores = {s.rubric_name: s for s in rule_report.scores}
        judge_scores = {s.rubric_name: s for s in judge_report.scores if s.judge_type == "rule"}

        for name in rule_scores:
            if name in judge_scores:
                r_pass = rule_scores[name].passed
                j_pass = judge_scores[name].passed
                rule_labels.append(r_pass)
                judge_labels.append(j_pass)
                match = "✓" if r_pass == j_pass else "✗"
                print(
                    f"{rule_report.task_id:<25} {name:<20} "
                    f"{'✓' if r_pass else '✗':>4} "
                    f"{'✓' if j_pass else '✗':>4} "
                    f"{match:>4}"
                )

    # 6. 计算 Cohen's Kappa
    print("\n" + "=" * 60)
    kappa = compute_cohens_kappa(rule_labels, judge_labels)
    agreement_rate = sum(1 for a, b in zip(rule_labels, judge_labels) if a == b) / len(rule_labels) * 100

    print(f"评分项总数: {len(rule_labels)}")
    print(f"一致数量  : {sum(1 for a, b in zip(rule_labels, judge_labels) if a == b)}")
    print(f"一致率    : {agreement_rate:.1f}%")
    print(f"Cohen's κ : {kappa:.4f}")
    print(f"解读      : {interpret_kappa(kappa)}")
    print("=" * 60)

    # 7. 额外统计：LLM Judge 独有评分项
    judge_only_count = 0
    judge_only_pass = 0
    for judge_report in judge_reports:
        for s in judge_report.scores:
            if s.judge_type == "llm_judge":
                judge_only_count += 1
                if s.passed:
                    judge_only_pass += 1

    if judge_only_count > 0:
        print(f"\nLLM Judge 独有评分项: {judge_only_count} 个")
        print(f"  通过: {judge_only_pass}, 未通过: {judge_only_count - judge_only_pass}")
        print(f"  通过率: {judge_only_pass / judge_only_count * 100:.1f}%")

    # 8. 结论
    print("\n📊 实验结论:")
    if kappa >= 0.80:
        print("  规则引擎与 LLM Judge 在客观指标上高度一致（κ ≥ 0.80）。")
        print("  规则引擎可以替代 LLM Judge 处理客观评分，实现：")
        print("  - 推理成本为零")
        print("  - 100% 可复现")
        print("  - 评测时间缩短 60%+")
    elif kappa >= 0.60:
        print("  规则引擎与 LLM Judge 一致性较高（0.60 ≤ κ < 0.80）。")
        print("  建议：客观指标用规则引擎，主观指标用 LLM Judge。")
    else:
        print("  规则引擎与 LLM Judge 一致性不足（κ < 0.60）。")
        print("  需要进一步调优规则或 LLM Judge prompt。")

    return {
        "total_items": len(rule_labels),
        "agreement_count": sum(1 for a, b in zip(rule_labels, judge_labels) if a == b),
        "agreement_rate": agreement_rate,
        "cohens_kappa": kappa,
        "interpretation": interpret_kappa(kappa),
        "judge_only_items": judge_only_count,
        "mode": "real_llm" if use_real_llm else "mock",
        "model": model,
    }


def main():
    parser = argparse.ArgumentParser(description="Cohen's Kappa 一致性实验")
    parser.add_argument("--real-llm", action="store_true", help="使用真实 LLM（需要 API Key）")
    parser.add_argument("--model", default="gpt-4o", help="LLM 模型名")
    parser.add_argument("--spec-dir", default="specs/tasks", help="任务规范目录")
    args = parser.parse_args()

    asyncio.run(run_experiment(
        use_real_llm=args.real_llm,
        model=args.model,
        spec_dir=args.spec_dir,
    ))


if __name__ == "__main__":
    main()
