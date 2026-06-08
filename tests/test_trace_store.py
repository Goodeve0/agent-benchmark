"""Trace 存储层单元测试。"""

from __future__ import annotations

import time

import pytest

from agent_bench.trace_store.models import (
    ActionRecord,
    TracePayload,
    TraceQuery,
)
from agent_bench.trace_store.store import TraceStore


@pytest.fixture
def trace_store(tmp_path):
    """创建临时 TraceStore。"""
    db_path = str(tmp_path / "test_traces.db")
    return TraceStore(db_path=db_path)


def _make_payload(
    trace_id: str = "test_001",
    task_id: str = "task_001",
    agent_name: str = "test-agent",
    agent_version: str = "1.0.0",
    actions: list[ActionRecord] | None = None,
    success: bool = True,
) -> TracePayload:
    """创建测试用 TracePayload。"""
    if actions is None:
        actions = [
            ActionRecord(
                action_type="tool_call",
                tool_name="search",
                parameters={"query": "test"},
                result={"status": "ok"},
                timestamp=time.time(),
                duration_ms=100.0,
            ),
            ActionRecord(
                action_type="response",
                content="测试回复",
                timestamp=time.time(),
            ),
        ]
    return TracePayload(
        trace_id=trace_id,
        task_id=task_id,
        agent_name=agent_name,
        agent_version=agent_version,
        actions=actions,
        total_tokens=500,
        final_response="测试回复",
        execution_time=1.5,
        success=success,
    )


class TestTraceStoreSave:
    """Trace 保存测试。"""

    def test_save_single_trace(self, trace_store):
        payload = _make_payload()
        trace_id = trace_store.save_trace(payload)
        assert trace_id == "test_001"

    def test_save_trace_with_auto_hash(self, trace_store):
        """保存时自动计算链式哈希。"""
        payload = _make_payload()
        trace_store.save_trace(payload)
        assert payload.payload_hash != ""
        assert payload.prev_hash == "GENESIS"

    def test_save_multiple_traces_chain(self, trace_store):
        """多条 Trace 形成链式哈希。"""
        p1 = _make_payload(trace_id="trace_1")
        p2 = _make_payload(trace_id="trace_2")
        p3 = _make_payload(trace_id="trace_3")

        trace_store.save_trace(p1)
        trace_store.save_trace(p2)
        trace_store.save_trace(p3)

        # p2 的 prev_hash 应该等于 p1 的 payload_hash
        assert p2.prev_hash == p1.payload_hash
        # p3 的 prev_hash 应该等于 p2 的 payload_hash
        assert p3.prev_hash == p2.payload_hash

    def test_save_batch(self, trace_store):
        payloads = [
            _make_payload(trace_id=f"batch_{i}")
            for i in range(5)
        ]
        trace_ids = trace_store.save_traces_batch(payloads)
        assert len(trace_ids) == 5


class TestTraceStoreQuery:
    """Trace 查询测试。"""

    def test_query_all(self, trace_store):
        for i in range(3):
            trace_store.save_trace(_make_payload(trace_id=f"q_{i}"))

        results, total = trace_store.query_traces(TraceQuery())
        assert total == 3
        assert len(results) == 3

    def test_query_by_agent(self, trace_store):
        trace_store.save_trace(_make_payload(trace_id="a1", agent_name="agent-a"))
        trace_store.save_trace(_make_payload(trace_id="b1", agent_name="agent-b"))

        results, total = trace_store.query_traces(
            TraceQuery(agent_name="agent-a")
        )
        assert total == 1
        assert results[0].agent_name == "agent-a"

    def test_query_by_task(self, trace_store):
        trace_store.save_trace(_make_payload(trace_id="t1", task_id="task_A"))
        trace_store.save_trace(_make_payload(trace_id="t2", task_id="task_B"))

        results, total = trace_store.query_traces(
            TraceQuery(task_id="task_A")
        )
        assert total == 1
        assert results[0].task_id == "task_A"

    def test_query_pagination(self, trace_store):
        for i in range(10):
            trace_store.save_trace(_make_payload(trace_id=f"page_{i}"))

        results, total = trace_store.query_traces(TraceQuery(limit=3, offset=0))
        assert total == 10
        assert len(results) == 3

    def test_query_by_success(self, trace_store):
        trace_store.save_trace(_make_payload(trace_id="s1", success=True))
        trace_store.save_trace(_make_payload(trace_id="s2", success=False))

        results, total = trace_store.query_traces(TraceQuery(success=False))
        assert total == 1
        assert results[0].success is False


class TestTraceStoreDetail:
    """Trace 详情测试。"""

    def test_get_detail(self, trace_store):
        trace_store.save_trace(_make_payload())
        detail = trace_store.get_trace_detail("test_001")
        assert detail is not None
        assert detail.trace_id == "test_001"
        assert len(detail.actions) == 2
        assert detail.actions[0].tool_name == "search"

    def test_get_detail_not_found(self, trace_store):
        detail = trace_store.get_trace_detail("nonexistent")
        assert detail is None


class TestTraceStoreStats:
    """Trace 统计测试。"""

    def test_stats_empty(self, trace_store):
        stats = trace_store.get_stats()
        assert stats.total_traces == 0
        assert stats.success_rate == 0.0

    def test_stats_with_data(self, trace_store):
        trace_store.save_trace(_make_payload(trace_id="st1", agent_name="a1"))
        trace_store.save_trace(_make_payload(trace_id="st2", agent_name="a1", success=False))
        trace_store.save_trace(_make_payload(trace_id="st3", agent_name="a2"))

        stats = trace_store.get_stats()
        assert stats.total_traces == 3
        assert stats.success_rate == pytest.approx(2 / 3, abs=0.01)
        assert stats.agent_counts == {"a1": 2, "a2": 1}


class TestTraceStoreIntegrity:
    """链式哈希完整性验证测试。"""

    def test_verify_valid_chain(self, trace_store):
        for i in range(5):
            trace_store.save_trace(_make_payload(trace_id=f"chain_{i}"))

        report = trace_store.verify_integrity()
        assert report.is_valid is True
        assert report.total_traces == 5
        assert report.broken == 0

    def test_verify_empty(self, trace_store):
        report = trace_store.verify_integrity()
        assert report.is_valid is True
        assert report.total_traces == 0


class TestTraceToAgentTrace:
    """Trace → AgentTrace 转换测试。"""

    def test_convert(self, trace_store):
        trace_store.save_trace(_make_payload())
        agent_trace = trace_store.trace_to_agent_trace("test_001")
        assert agent_trace is not None
        assert agent_trace.task_id == "task_001"
        assert agent_trace.total_tokens == 500
        assert len(agent_trace.actions) == 2

    def test_convert_not_found(self, trace_store):
        result = trace_store.trace_to_agent_trace("nonexistent")
        assert result is None
