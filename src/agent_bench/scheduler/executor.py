"""调度执行器 — 执行一次定时评估任务的核心逻辑。"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from agent_bench.scheduler.models import (
    EvalSchedule,
    ScheduleRun,
    ScheduleRunStatus,
)

logger = logging.getLogger(__name__)


async def run_scheduled_eval(
    schedule: EvalSchedule,
    run_id: str | None = None,
    scheduler: Any = None,
) -> ScheduleRun:
    """执行一次定时评估。

    流程:
    1. 拉取最新 Trace（按 agent + version + 时间范围）
    2. Scorer 评分
    3. 存储评分结果
    4. 检查告警条件
    5. 低分 Trace → BadCase 回流
    6. 更新调度状态
    """
    from agent_bench.trace_store import TraceStore
    from agent_bench.scorer.scorer import Scorer
    from agent_bench.badcase import BadCaseStore, BadCase
    from agent_bench.alert import AlertEngine

    if run_id is None:
        run_id = uuid.uuid4().hex

    now = datetime.now(timezone.utc)
    run = ScheduleRun(
        run_id=run_id,
        schedule_id=schedule.schedule_id,
        status=ScheduleRunStatus.RUNNING,
        started_at=now.isoformat(),
    )

    if scheduler:
        scheduler.save_run(run)

    try:
        # 1. 拉取 Trace
        trace_store = _get_trace_store(scheduler)
        from agent_bench.trace_store.models import TraceQuery

        query = TraceQuery(
            agent_name=schedule.agent_name,
            agent_version=schedule.agent_version,
            limit=500,
            offset=0,
        )
        if schedule.last_run_at:
            query.start_time = schedule.last_run_at

        traces, total = trace_store.query_traces(query)
        logger.info(
            "调度 %s: 查询到 %d 条 Trace (agent=%s)",
            schedule.name, total, schedule.agent_name,
        )

        if total == 0:
            run.status = ScheduleRunStatus.SUCCESS
            run.traces_count = 0
            run.finished_at = datetime.now(timezone.utc).isoformat()
            if scheduler:
                scheduler.update_run(run.run_id, **_run_to_dict(run))
                scheduler.update_schedule_last_run(schedule.schedule_id, "success")
            return run

        # 2. 评分
        scorer = _get_scorer(schedule)
        total_score = 0.0
        scored_count = 0
        badcases: list[BadCase] = []

        for summary in traces:
            detail = trace_store.get_trace_detail(summary.trace_id)
            if detail is None:
                continue

            agent_trace = trace_store.trace_to_agent_trace(summary.trace_id)
            if agent_trace is None:
                continue

            # 自由评分模式（SDK 上报的 Trace 不一定有 Task YAML）
            report = scorer.score_task_free(agent_trace)
            total_score += report.percentage
            scored_count += 1

            # BadCase 检测
            if schedule.badcase_enabled and report.percentage < schedule.badcase_threshold:
                bc = BadCase(
                    trace_id=summary.trace_id,
                    task_id=summary.task_id,
                    agent_name=summary.agent_name,
                    agent_version=summary.agent_version,
                    score=report.score,
                    max_score=report.max_score,
                    percentage=report.percentage,
                    dimension=report.lowest_dimension if hasattr(report, "lowest_dimension") else None,
                    failure_reason=_summarize_failure(report),
                    reflux_source="auto",
                )
                badcases.append(bc)

        # 3. 存储评分结果
        avg_score = total_score / scored_count if scored_count > 0 else 0.0

        # 4. BadCase 回流
        badcase_count = 0
        if schedule.badcase_enabled and badcases:
            # 截断到 max_per_run
            badcases = badcases[: schedule.badcase_max_per_run]
            badcase_store = _get_badcase_store(scheduler)
            for bc in badcases:
                badcase_store.save(bc)
                badcase_count += 1
            logger.info("调度 %s: 回流 %d 条 BadCase", schedule.name, badcase_count)

        # 5. 告警检查
        alert_count = 0
        try:
            alert_engine = _get_alert_engine(scheduler)
            if schedule.alert_on_score_drop or schedule.alert_threshold > 0:
                alerts = alert_engine.check_and_alert(
                    agent_name=schedule.agent_name,
                    agent_version=schedule.agent_version,
                    current_score=avg_score,
                    schedule=schedule,
                )
                alert_count = len(alerts)
        except Exception as e:
            logger.warning("告警检查失败: %s", e)

        # 6. 更新运行结果
        run.status = ScheduleRunStatus.SUCCESS
        run.traces_count = scored_count
        run.avg_score = round(avg_score, 4)
        run.badcase_count = badcase_count
        run.alert_count = alert_count
        run.finished_at = datetime.now(timezone.utc).isoformat()

        logger.info(
            "调度 %s: 完成 (scored=%d, avg=%.1f%%, badcase=%d, alerts=%d)",
            schedule.name, scored_count, avg_score, badcase_count, alert_count,
        )

    except Exception as e:
        logger.error("调度 %s: 执行失败 - %s", schedule.name, e)
        run.status = ScheduleRunStatus.FAILED
        run.error_message = str(e)
        run.finished_at = datetime.now(timezone.utc).isoformat()

    finally:
        if scheduler:
            scheduler.update_run(run.run_id, **_run_to_dict(run))
            scheduler.update_schedule_last_run(
                schedule.schedule_id, run.status
            )

    return run


def _run_to_dict(run: ScheduleRun) -> dict[str, Any]:
    """将 ScheduleRun 转为 update_run 的 kwargs。"""
    result: dict[str, Any] = {
        "status": run.status,
        "traces_count": run.traces_count,
        "avg_score": run.avg_score,
        "badcase_count": run.badcase_count,
        "alert_count": run.alert_count,
    }
    if run.error_message:
        result["error_message"] = run.error_message
    if run.finished_at:
        from datetime import datetime as _dt
        result["finished_at"] = _dt.fromisoformat(run.finished_at)
    return result


def _get_trace_store(scheduler: Any = None) -> Any:
    """获取 TraceStore 实例。"""
    from agent_bench.trace_store import TraceStore
    import os
    db_path = os.environ.get("AGENT_BENCH_DB_PATH", "data/traces.db")
    return TraceStore(db_path=db_path)


def _get_scorer(schedule: EvalSchedule) -> Any:
    """获取 Scorer 实例。"""
    from agent_bench.scorer.scorer import Scorer
    from agent_bench.scorer.llm_judge import LLMJudge

    judge = None
    if schedule.scorer_type in ("llm_judge", "mixed"):
        judge = LLMJudge(model=schedule.judge_model, mock=True)

    return Scorer(judge=judge)


def _get_badcase_store(scheduler: Any = None) -> Any:
    """获取 BadCaseStore 实例。"""
    from agent_bench.badcase import BadCaseStore
    import os
    db_path = os.environ.get("AGENT_BENCH_BADCASE_DB_PATH", "data/badcases.db")
    return BadCaseStore(db_path=db_path)


def _get_alert_engine(scheduler: Any = None) -> Any:
    """获取 AlertEngine 实例。"""
    from agent_bench.alert import AlertEngine
    import os
    db_path = os.environ.get("AGENT_BENCH_ALERT_DB_PATH", "data/alerts.db")
    return AlertEngine(db_path=db_path)


def _summarize_failure(report: Any) -> str:
    """从评分报告中提取失败原因摘要。"""
    parts = []
    for dim_score in report.dimension_scores:
        pct = dim_score.score / dim_score.max_score * 100 if dim_score.max_score > 0 else 0
        if pct < 60:
            parts.append(f"{dim_score.dimension}: {pct:.0f}%")
    return "; ".join(parts) if parts else "低分"
