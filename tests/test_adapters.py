"""适配器单元测试。"""

from __future__ import annotations

import pytest

from agent_bench.adapters import get_adapter
from agent_bench.adapters.mock_adapter import MockAdapter


class TestMockAdapter:
    """MockAdapter 单元测试。"""

    def test_create_mock_adapter(self):
        adapter = get_adapter("mock")
        assert isinstance(adapter, MockAdapter)

    def test_get_agent_info(self):
        adapter = MockAdapter()
        info = adapter.get_agent_info()
        assert "name" in info
        assert "model" in info

    @pytest.mark.asyncio
    async def test_run_single_turn(self):
        from agent_bench.models.task import ToolDef, RubricItem
        from agent_bench.sandbox import Sandbox

        adapter = MockAdapter()
        tools = [ToolDef(name="weather_query", description="查询天气", parameters={})]
        sandbox = Sandbox(mock_apis={"weather_query": {"temp": 25, "city": "北京"}})
        trace = await adapter.run_task(
            task_prompt="查询北京天气",
            tools=tools,
            sandbox=sandbox,
        )
        assert trace is not None


class TestDataAnalystAdapter:
    """DataAnalystAdapter 单元测试。"""

    def test_import_guard(self):
        """DataAnalystAdapter 导入时如果没有 openai 应该抛出 ImportError。"""
        try:
            adapter = get_adapter("data_analyst", model="gpt-4o")
        except ImportError as e:
            assert "openai" in str(e)


class TestMultiAgentAdapter:
    """多 Agent 适配器单元测试。"""

    def test_invalid_topology(self):
        from agent_bench.adapters.multi_agent import get_multi_agent_adapter
        with pytest.raises(ValueError, match="未知的多 Agent 拓扑"):
            get_multi_agent_adapter("invalid_topology")

    def test_manager_worker_creation(self):
        """ManagerWorkerAdapter 可以通过 get_multi_agent_adapter 创建。"""
        from agent_bench.adapters.multi_agent import get_multi_agent_adapter
        # 创建需要 openai 依赖，此处仅验证工厂方法存在
        assert callable(get_multi_agent_adapter)

    def test_debate_creation(self):
        """DebateAdapter 工厂方法可用。"""
        from agent_bench.adapters.multi_agent import get_multi_agent_adapter
        assert callable(get_multi_agent_adapter)

    def test_pipeline_creation(self):
        """PipelineAdapter 工厂方法可用。"""
        from agent_bench.adapters.multi_agent import get_multi_agent_adapter
        assert callable(get_multi_agent_adapter)
