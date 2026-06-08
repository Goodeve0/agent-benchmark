"""真实工具实现和对比报告单元测试。"""

from __future__ import annotations

import pytest

from agent_bench.tools import get_tool_definitions, get_all_tool_implementations


class TestToolRegistry:
    """工具注册中心测试。"""

    def test_get_tool_definitions(self):
        defs = get_tool_definitions()
        assert isinstance(defs, dict)
        assert len(defs) > 0

    def test_get_all_tool_implementations(self):
        impls = get_all_tool_implementations()
        assert isinstance(impls, dict)
        assert len(impls) > 0

    def test_weather_tool_exists(self):
        defs = get_tool_definitions()
        names = list(defs.keys())
        # 天气工具应该是 get_weather
        weather_names = [n for n in names if "weather" in n.lower()]
        assert len(weather_names) > 0

    def test_database_tools_exist(self):
        defs = get_tool_definitions()
        names = list(defs.keys())
        assert "list_tables" in names
        assert "describe_table" in names
        assert "query_database" in names


class TestDatabaseTools:
    """数据库工具 SQL 注入防护测试。"""

    def test_sql_injection_prevention(self):
        """DROP TABLE 应该被拒绝。"""
        from agent_bench.tools.database import _validate_sql
        with pytest.raises(ValueError):
            _validate_sql("DROP TABLE film")

    def test_non_select_rejection(self):
        """INSERT 应该被拒绝。"""
        from agent_bench.tools.database import _validate_sql
        with pytest.raises(ValueError):
            _validate_sql("INSERT INTO film VALUES (999, 'hack')")

    def test_delete_rejection(self):
        """DELETE 应该被拒绝。"""
        from agent_bench.tools.database import _validate_sql
        with pytest.raises(ValueError):
            _validate_sql("DELETE FROM film")

    def test_select_allowed(self):
        """SELECT 应该被允许。"""
        from agent_bench.tools.database import _validate_sql
        # 不应抛出异常
        _validate_sql("SELECT * FROM film WHERE film_id = 1")

    def test_update_rejection(self):
        """UPDATE 应该被拒绝。"""
        from agent_bench.tools.database import _validate_sql
        with pytest.raises(ValueError):
            _validate_sql("UPDATE film SET title = 'hack'")


class TestComparisonReport:
    """对比报告测试。"""

    def test_create_comparison_report(self):
        from agent_bench.reporter.comparison import ComparisonReport
        from agent_bench.models import EvaluationResult, DimensionScore

        results = [
            EvaluationResult(
                agent_name="AgentA",
                agent_model="v1",
                timestamp="2024-01-01T00:00:00Z",
                dimension_scores=[
                    DimensionScore(
                        dimension="tool_use", score=80.0, max_score=100.0,
                        percentage=80.0, task_count=1,
                    ),
                ],
            ),
            EvaluationResult(
                agent_name="AgentB",
                agent_model="v1",
                timestamp="2024-01-01T00:00:00Z",
                dimension_scores=[
                    DimensionScore(
                        dimension="tool_use", score=90.0, max_score=100.0,
                        percentage=90.0, task_count=1,
                    ),
                ],
            ),
        ]
        report = ComparisonReport(results)
        data = report.to_dict()
        assert "agents" in data
        assert "comparison_matrix" in data
        assert len(data["agents"]) == 2

    def test_cohens_d(self):
        from agent_bench.reporter.comparison import _cohens_d_pair
        d = _cohens_d_pair(80.0, 90.0)
        assert d > 0

    def test_interpret_cohens_d(self):
        from agent_bench.reporter.comparison import _interpret_cohens_d
        assert _interpret_cohens_d(0.1) == "可忽略"
        assert _interpret_cohens_d(0.3) == "小效应"
        assert _interpret_cohens_d(0.6) == "中等效应"
        assert _interpret_cohens_d(1.0) == "大效应"
