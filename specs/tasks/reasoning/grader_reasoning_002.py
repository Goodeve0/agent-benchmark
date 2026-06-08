"""reasoning_002 自定义 Grader 示例。

演示如何编写自定义 grader：
- 继承 AbstractGrader
- 实现 grade() 方法
- 使用辅助方法 make_detail() / build_report() / check_response_substance()
"""

from agent_bench.graders.base import AbstractGrader
from agent_bench.models import AgentTrace, ScoreReport, Task


class Grader(AbstractGrader):
    """reasoning_002 的自定义评分器。

    评分逻辑：
    1. 是否调用了 search_venues 工具（20分）
    2. 回复是否有实质内容（20分）
    3. 方案是否包含三个部分：地点、流程、预算（30分）
    4. 预算是否在范围内（30分）
    """

    async def grade(self, trace: AgentTrace, task: Task) -> ScoreReport:
        details = []

        # 1. 工具调用检查
        called_tools = trace.called_tool_names()
        tool_ok = "search_venues" in called_tools
        details.append(self.make_detail(
            "调用场地搜索工具",
            20,
            tool_ok,
            f"{'已' if tool_ok else '未'}调用 search_venues（实际: {called_tools}）",
        ))

        # 2. 回复实质性检查
        substance_ok, substance_reason = self.check_response_substance(
            trace.final_response,
            min_length=30,
            required_keywords=["活动"],
        )
        details.append(self.make_detail(
            "回复有实质内容",
            20,
            substance_ok,
            substance_reason,
        ))

        # 3. 方案完整性（检查三个部分）
        response = trace.final_response or ""
        has_venue = any(kw in response for kw in ["地点", "场地", "场所", "朝阳", "望京"])
        has_schedule = any(kw in response for kw in ["流程", "安排", "时间", "上午", "下午"])
        has_budget = any(kw in response for kw in ["预算", "费用", "元", "花费"])
        parts_count = sum([has_venue, has_schedule, has_budget])
        plan_ok = parts_count >= 2  # 至少包含 2 个部分
        details.append(self.make_detail(
            "方案完整性",
            30,
            plan_ok,
            f"包含 {parts_count}/3 个部分（地点={has_venue}, 流程={has_schedule}, 预算={has_budget}）",
        ))

        # 4. 预算合理性
        budget_ok = "5000" in response or "五千" in response or has_budget
        details.append(self.make_detail(
            "预算合理性",
            30,
            budget_ok,
            "方案考虑了预算约束" if budget_ok else "方案未提及预算",
        ))

        return self.build_report(task, details)
