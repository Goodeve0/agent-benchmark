"""告警 API 路由。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from agent_bench.alert.models import Alert, AlertQuery, AlertStats

router = APIRouter(prefix="/alerts", tags=["alerts"])


def _get_alert_engine():
    """从 app.state 获取 AlertEngine 实例。"""
    from agent_bench.server.app import get_app
    app = get_app()
    return app.state.alert_engine


@router.get("", response_model=dict)
async def list_alerts(
    schedule_id: str | None = None,
    alert_type: str | None = None,
    severity: str | None = None,
    agent_name: str | None = None,
    resolved: bool | None = None,
    limit: int = 50,
    offset: int = 0,
):
    """查询告警列表。"""
    engine = _get_alert_engine()
    query = AlertQuery(
        schedule_id=schedule_id,
        alert_type=alert_type,
        severity=severity,
        agent_name=agent_name,
        resolved=resolved,
        limit=limit,
        offset=offset,
    )
    results, total = engine.query(query)
    return {"items": [r.model_dump() for r in results], "total": total}


@router.get("/stats", response_model=AlertStats)
async def get_alert_stats(agent_name: str | None = None):
    """获取告警统计。"""
    engine = _get_alert_engine()
    return engine.get_stats(agent_name=agent_name)


@router.post("/{alert_id}/resolve", response_model=dict)
async def resolve_alert(alert_id: int):
    """标记告警为已处理。"""
    engine = _get_alert_engine()
    success = engine.resolve(alert_id)
    if not success:
        raise HTTPException(status_code=404, detail="告警不存在")
    return {"alert_id": alert_id, "resolved": True}
