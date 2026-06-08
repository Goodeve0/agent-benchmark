"""Sandbox 单元测试。"""

from __future__ import annotations

import asyncio

import pytest

from agent_bench.sandbox.sandbox import Sandbox, AuditLog, _compute_checksum
from agent_bench.sandbox.real_sandbox import RealSandbox


class TestSandbox:
    """Sandbox（Mock 模式）单元测试。"""

    def test_create_sandbox(self):
        sandbox = Sandbox(mock_apis={"weather_query": {"temp": 25, "city": "北京"}})
        assert sandbox is not None

    @pytest.mark.asyncio
    async def test_execute_tool(self):
        sandbox = Sandbox(mock_apis={"weather_query": {"temp": 25, "city": "北京"}})
        result = await sandbox.execute_tool("weather_query", {"city": "北京"})
        assert result is not None
        assert result["temp"] == 25

    @pytest.mark.asyncio
    async def test_execute_unmocked_tool(self):
        sandbox = Sandbox(mock_apis={})
        result = await sandbox.execute_tool("unknown_tool", {})
        assert "warning" in result

    def test_get_audit_log(self):
        sandbox = Sandbox(mock_apis={"search": {"results": []}})
        asyncio.run(sandbox.execute_tool("search", {"query": "test"}))
        log = sandbox.get_audit_log()
        assert len(log.entries) >= 1

    @pytest.mark.asyncio
    async def test_chain_hash_integrity(self):
        """验证审计日志的链式哈希完整性。"""
        sandbox = Sandbox(mock_apis={
            "weather_query": {"temp": 25},
            "search": {"results": []},
        })
        await sandbox.execute_tool("weather_query", {"city": "北京"})
        await sandbox.execute_tool("search", {"query": "test"})
        log = sandbox.get_audit_log(freeze=False)
        assert log.verify_integrity()

    @pytest.mark.asyncio
    async def test_frozen_log_rejects_calls(self):
        """验证冻结后的审计日志不允许再执行工具调用。"""
        sandbox = Sandbox(mock_apis={"weather_query": {"temp": 25}})
        await sandbox.execute_tool("weather_query", {"city": "北京"})
        sandbox.get_audit_log(freeze=True)
        with pytest.raises(RuntimeError, match="审计日志已冻结"):
            await sandbox.execute_tool("weather_query", {"city": "上海"})


class TestAuditLog:
    """审计日志测试。"""

    def test_verify_empty_log(self):
        log = AuditLog()
        assert log.verify_integrity()

    def test_tool_names(self):
        log = AuditLog()
        # 手动构造有 tool_names 的日志
        from agent_bench.sandbox.sandbox import AuditEntry
        log.entries.append(
            AuditEntry(seq=1, tool_name="weather_query", params={}, result={}, timestamp=0.0, checksum="abc")
        )
        assert log.tool_names == ["weather_query"]


class TestRealSandbox:
    """RealSandbox 单元测试。"""

    def test_create_real_sandbox(self):
        sandbox = RealSandbox(
            tool_implementations={},
            mock_apis={"weather_query": {"temp": 25}},
        )
        assert sandbox is not None

    @pytest.mark.asyncio
    async def test_mock_fallback_for_unregistered_tool(self):
        sandbox = RealSandbox(
            tool_implementations={},
            mock_apis={"weather_query": {"temp": 25}},
        )
        result = await sandbox.execute_tool("weather_query", {"city": "北京"})
        assert result["_source"] == "mock_fallback"

    @pytest.mark.asyncio
    async def test_budget_exceeded(self):
        sandbox = RealSandbox(
            tool_implementations={},
            mock_apis={"weather_query": {"temp": 25}},
            budget=1,
        )
        await sandbox.execute_tool("weather_query", {"city": "北京"})
        from agent_bench.exceptions import BudgetExceededError
        with pytest.raises(BudgetExceededError):
            await sandbox.execute_tool("weather_query", {"city": "上海"})

    @pytest.mark.asyncio
    async def test_tool_not_found_error(self):
        from agent_bench.exceptions import ToolNotFoundError
        sandbox = RealSandbox(
            tool_implementations={},
            mock_apis={},
        )
        with pytest.raises(ToolNotFoundError):
            await sandbox.execute_tool("nonexistent_tool", {})

    @pytest.mark.asyncio
    async def test_fallback_on_error(self):
        """真实调用失败时降级到 Mock 数据。"""
        async def failing_tool(**kwargs):
            raise RuntimeError("API 不可用")

        sandbox = RealSandbox(
            tool_implementations={"weather_query": failing_tool},
            mock_apis={"weather_query": {"temp": 20}},
            fallback_on_error=True,
        )
        result = await sandbox.execute_tool("weather_query", {"city": "北京"})
        assert result["_source"] == "mock_fallback"
