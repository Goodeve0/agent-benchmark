"""BadCase API 路由。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from agent_bench.badcase.models import BadCase, BadCaseQuery, BadCaseSummary

router = APIRouter(prefix="/badcases", tags=["badcases"])


def _get_badcase_store():
    """从 app.state 获取 BadCaseStore 实例。"""
    from agent_bench.server.app import get_app
    app = get_app()
    return app.state.badcase_store


@router.get("", response_model=dict)
async def list_badcases(
    agent_name: str | None = None,
    agent_version: str | None = None,
    dimension: str | None = None,
    reflux_source: str | None = None,
    resolved: bool | None = None,
    min_percentage: float | None = None,
    max_percentage: float | None = None,
    limit: int = 50,
    offset: int = 0,
):
    """查询 BadCase 列表。"""
    store = _get_badcase_store()
    query = BadCaseQuery(
        agent_name=agent_name,
        agent_version=agent_version,
        dimension=dimension,
        reflux_source=reflux_source,
        resolved=resolved,
        min_percentage=min_percentage,
        max_percentage=max_percentage,
        limit=limit,
        offset=offset,
    )
    results, total = store.query(query)
    return {"items": [r.model_dump() for r in results], "total": total}


@router.get("/stats", response_model=BadCaseSummary)
async def get_badcase_stats(agent_name: str | None = None):
    """获取 BadCase 统计。"""
    store = _get_badcase_store()
    return store.get_stats(agent_name=agent_name)


@router.post("/{trace_id}/resolve", response_model=dict)
async def resolve_badcase(trace_id: str):
    """标记 BadCase 为已解决。"""
    store = _get_badcase_store()
    success = store.resolve(trace_id)
    if not success:
        raise HTTPException(status_code=404, detail="未找到未解决的 BadCase")
    return {"trace_id": trace_id, "resolved": True}
