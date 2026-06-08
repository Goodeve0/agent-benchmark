"""Trace API 路由 — 上报/查询/验证。"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from agent_bench.trace_store.models import (
    ActionRecord,
    TracePayload,
    TraceQuery,
)

logger = logging.getLogger(__name__)

trace_router = APIRouter(prefix="/traces", tags=["traces"])


def _get_trace_store(request: Request):
    """从 FastAPI Request 获取 TraceStore 实例。"""
    return request.app.state.trace_store


@trace_router.post("")
async def upload_trace(payload: TracePayload, request: Request):
    """上报一条 Trace（SDK 调用）。

    请求体为 TracePayload JSON，包含 actions 列表和链式哈希信息。
    """
    store = _get_trace_store(request)
    try:
        trace_id = store.save_trace(payload)
        return {"trace_id": trace_id, "status": "saved"}
    except Exception as e:
        logger.error("Trace 上报失败: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Trace 保存失败: {e}") from e


@trace_router.get("")
async def list_traces(
    request: Request,
    task_id: str | None = None,
    agent_name: str | None = None,
    agent_version: str | None = None,
    project_id: str | None = None,
    source: str | None = None,
    success: bool | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    limit: int = 50,
    offset: int = 0,
):
    """查询 Trace 列表（分页 + 过滤）。"""
    store = _get_trace_store(request)
    query = TraceQuery(
        task_id=task_id,
        agent_name=agent_name,
        agent_version=agent_version,
        project_id=project_id,
        source=source,
        success=success,
        start_time=start_time,
        end_time=end_time,
        limit=min(limit, 200),  # 上限 200
        offset=max(offset, 0),
    )
    results, total = store.query_traces(query)
    return {
        "traces": [r.model_dump() for r in results],
        "total": total,
        "limit": query.limit,
        "offset": query.offset,
    }


@trace_router.get("/stats")
async def get_trace_stats(
    request: Request,
    project_id: str | None = None,
):
    """获取 Trace 统计信息。"""
    store = _get_trace_store(request)
    stats = store.get_stats(project_id=project_id)
    return stats.model_dump()


@trace_router.post("/verify")
async def verify_integrity(
    request: Request,
    project_id: str | None = None,
):
    """验证链式哈希完整性。"""
    store = _get_trace_store(request)
    report = store.verify_integrity(project_id=project_id)
    return report.model_dump()


@trace_router.get("/{trace_id}")
async def get_trace_detail(trace_id: str, request: Request):
    """获取 Trace 详情（含 actions 明细）。"""
    store = _get_trace_store(request)
    detail = store.get_trace_detail(trace_id)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"Trace {trace_id} 不存在")
    return detail.model_dump()
