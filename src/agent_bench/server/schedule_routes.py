"""调度任务 API 路由。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from agent_bench.scheduler.models import (
    EvalSchedule,
    ScheduleCreateRequest,
    ScheduleRun,
    ScheduleUpdateRequest,
)

router = APIRouter(prefix="/schedules", tags=["schedules"])


def _get_scheduler():
    """从 app.state 获取 EvalScheduler 实例。"""
    from agent_bench.server.app import get_app
    app = get_app()
    return app.state.scheduler


@router.post("", response_model=EvalSchedule, status_code=201)
async def create_schedule(req: ScheduleCreateRequest):
    """创建调度任务。"""
    scheduler = _get_scheduler()
    schedule = EvalSchedule(
        name=req.name,
        agent_name=req.agent_name,
        agent_version=req.agent_version,
        dimension=req.dimension,
        task_ids=req.task_ids,
        cron=req.cron,
        scorer_type=req.scorer_type,
        judge_model=req.judge_model,
        badcase_enabled=req.badcase_enabled,
        badcase_threshold=req.badcase_threshold,
        alert_on_score_drop=req.alert_on_score_drop,
        alert_threshold=req.alert_threshold,
        alert_webhook=req.alert_webhook,
        alert_emails=req.alert_emails,
    )
    schedule_id = scheduler.create_schedule(schedule)
    result = scheduler.get_schedule(schedule_id)
    if result is None:
        raise HTTPException(status_code=500, detail="创建调度任务失败")
    return result


@router.get("", response_model=list[EvalSchedule])
async def list_schedules(enabled_only: bool = False):
    """列出调度任务。"""
    scheduler = _get_scheduler()
    return scheduler.list_schedules(enabled_only=enabled_only)


@router.get("/{schedule_id}", response_model=EvalSchedule)
async def get_schedule(schedule_id: str):
    """获取调度任务详情。"""
    scheduler = _get_scheduler()
    schedule = scheduler.get_schedule(schedule_id)
    if schedule is None:
        raise HTTPException(status_code=404, detail="调度任务不存在")
    return schedule


@router.put("/{schedule_id}", response_model=EvalSchedule)
async def update_schedule(schedule_id: str, req: ScheduleUpdateRequest):
    """更新调度任务配置。"""
    scheduler = _get_scheduler()
    # 过滤 None 值
    kwargs = {k: v for k, v in req.model_dump().items() if v is not None}
    if not kwargs:
        raise HTTPException(status_code=400, detail="无更新内容")

    success = scheduler.update_schedule(schedule_id, **kwargs)
    if not success:
        raise HTTPException(status_code=404, detail="调度任务不存在")

    result = scheduler.get_schedule(schedule_id)
    return result


@router.delete("/{schedule_id}", status_code=204)
async def delete_schedule(schedule_id: str):
    """删除调度任务。"""
    scheduler = _get_scheduler()
    success = scheduler.delete_schedule(schedule_id)
    if not success:
        raise HTTPException(status_code=404, detail="调度任务不存在")


@router.post("/{schedule_id}/trigger", response_model=ScheduleRun)
async def trigger_schedule(schedule_id: str):
    """手动触发一次调度执行。"""
    scheduler = _get_scheduler()
    run_id = scheduler.trigger_run(schedule_id)
    if run_id is None:
        raise HTTPException(status_code=404, detail="调度任务不存在")

    # 获取最新的 run
    runs = scheduler.list_runs(schedule_id, limit=1)
    if runs:
        return runs[0]
    return ScheduleRun(run_id=run_id, schedule_id=schedule_id, status="running")


@router.get("/{schedule_id}/runs", response_model=list[ScheduleRun])
async def list_schedule_runs(schedule_id: str, limit: int = 20):
    """获取调度任务的执行历史。"""
    scheduler = _get_scheduler()
    return scheduler.list_runs(schedule_id, limit=limit)
