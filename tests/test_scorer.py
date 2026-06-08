"""评分引擎单元测试。"""

from __future__ import annotations

import pytest

from agent_bench.scorer import Scorer
from agent_bench.scorer.rules import RULE_REGISTRY


class TestRuleEngine:
    """规则引擎测试。"""

    def test_rule_registry_not_empty(self):
        assert len(RULE_REGISTRY) > 0

    def test_check_tool_called_in_registry(self):
        assert "check_tool_called" in RULE_REGISTRY

    def test_check_response_length_in_registry(self):
        assert "check_response_length" in RULE_REGISTRY


class TestScorer:
    """Scorer 综合测试。"""

    def test_create_scorer(self):
        scorer = Scorer()
        assert scorer is not None

    def test_create_scorer_with_mock_judge(self):
        from agent_bench.scorer.llm_judge import LLMJudge
        judge = LLMJudge(mock_mode=True)
        scorer = Scorer(llm_judge=judge)
        assert scorer is not None


class TestLLMJudge:
    """LLM Judge 测试。"""

    def test_create_mock_judge(self):
        from agent_bench.scorer.llm_judge import LLMJudge
        judge = LLMJudge(mock_mode=True)
        assert judge.mock_mode is True
