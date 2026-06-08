"""核心数据模型单元测试。"""

from __future__ import annotations

import pytest

from agent_bench.models import Task, ScoreReport, DimensionScore, EvaluationResult
from agent_bench.models.task import ToolDef, RubricItem, JudgeRubricItem


def _make_task(**overrides) -> Task:
    """创建测试用的 Task 对象。"""
    defaults = dict(
        task_id="test_001",
        dimension="tool_use",
        sub_dimension="api_call",
        difficulty="easy",
        prompt="查询北京天气",
        tools=[ToolDef(name="weather_query", description="查询天气", parameters={"type": "object", "properties": {"city": {"type": "string"}}})],
        rubric=[RubricItem(name="调用天气工具", points=50.0, criteria="是否调用了天气查询工具")],
    )
    defaults.update(overrides)
    return Task(**defaults)


class TestTask:
    """Task 数据模型测试。"""

    def test_create_single_turn_task(self):
        task = _make_task()
        assert task.task_id == "test_001"
        assert task.is_multi_turn is False
        assert task.mode == "single_turn"
        assert task.has_judge_rubric is False

    def test_create_multi_turn_task(self):
        task = _make_task(
            mode="multi_turn",
            user_agent={"persona": "用户", "max_rounds": 3},
        )
        assert task.is_multi_turn is True
        assert task.mode == "multi_turn"

    def test_task_with_tools(self):
        task = _make_task(
            tools=[
                ToolDef(name="weather_query", description="查询天气", parameters={}),
                ToolDef(name="search", description="搜索", parameters={}),
            ],
        )
        assert len(task.tools) == 2
        assert task.tools[0].name == "weather_query"

    def test_task_with_judge_rubric(self):
        task = _make_task(
            judge_rubric=[
                JudgeRubricItem(name="回答质量", points=30.0, criteria="回答是否准确"),
            ],
        )
        assert task.has_judge_rubric is True

    def test_max_score_property(self):
        task = _make_task(
            rubric=[
                RubricItem(name="item1", points=50.0, criteria="c1"),
                RubricItem(name="item2", points=30.0, criteria="c2"),
            ],
            judge_rubric=[
                JudgeRubricItem(name="judge1", points=20.0, criteria="jc1"),
            ],
        )
        assert task.max_score == 100.0

    def test_tools_not_empty_validator(self):
        with pytest.raises(Exception):
            _make_task(tools=[])

    def test_rubric_not_empty_validator(self):
        with pytest.raises(Exception):
            _make_task(rubric=[])


class TestScoreReport:
    """ScoreReport 数据模型测试。"""

    def test_create_score_report(self):
        report = ScoreReport(
            task_id="test_001",
            dimension="tool_use",
            sub_dimension="api_call",
            difficulty="easy",
            total_score=85.0,
            max_score=100.0,
        )
        assert report.percentage == 85.0
        assert report.passed is True

    def test_score_report_zero(self):
        report = ScoreReport(
            task_id="test_002",
            dimension="tool_use",
            sub_dimension="api_call",
            difficulty="hard",
            total_score=0.0,
            max_score=100.0,
        )
        assert report.percentage == 0.0
        assert report.passed is False

    def test_score_report_below_threshold(self):
        report = ScoreReport(
            task_id="test_003",
            dimension="tool_use",
            sub_dimension="api_call",
            difficulty="medium",
            total_score=59.9,
            max_score=100.0,
        )
        assert report.passed is False


class TestDimensionScore:
    """DimensionScore 数据模型测试。"""

    def test_create_dimension_score(self):
        ds = DimensionScore(
            dimension="tool_use",
            score=170.0,
            max_score=200.0,
            percentage=85.0,
            task_count=2,
        )
        assert ds.percentage == 85.0
        assert ds.task_count == 2


class TestEvaluationResult:
    """EvaluationResult 数据模型测试。"""

    def test_create_evaluation_result(self):
        result = EvaluationResult(
            agent_name="MockAgent",
            agent_model="mock-v1",
            timestamp="2024-01-01T00:00:00Z",
            dimension_scores=[
                DimensionScore(
                    dimension="tool_use", score=85.0, max_score=100.0,
                    percentage=85.0, task_count=1,
                ),
            ],
            task_reports=[
                ScoreReport(
                    task_id="test_001",
                    dimension="tool_use",
                    sub_dimension="api_call",
                    difficulty="easy",
                    total_score=85.0,
                    max_score=100.0,
                ),
            ],
            overall_score=85.0,
            overall_max_score=100.0,
            overall_percentage=85.0,
        )
        assert result.agent_name == "MockAgent"
        assert result.overall_percentage == 85.0

    def test_serialization(self):
        result = EvaluationResult(
            agent_name="TestAgent",
            agent_model="test-v1",
            timestamp="2024-01-01T00:00:00Z",
            dimension_scores=[
                DimensionScore(
                    dimension="tool_use", score=90.0, max_score=100.0,
                    percentage=90.0, task_count=1,
                ),
            ],
        )
        data = result.model_dump(exclude_none=True)
        assert isinstance(data, dict)
        assert data["agent_name"] == "TestAgent"
