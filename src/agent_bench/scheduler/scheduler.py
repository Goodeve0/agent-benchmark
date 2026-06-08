"""评估调度器 — 基于 APScheduler 的定时评估任务调度。"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from agent_bench.scheduler.models import (
    Base,
    EvalSchedule,
    EvalScheduleORM,
    ScheduleRun,
    ScheduleRunORM,
    ScheduleRunStatus,
)

logger = logging.getLogger(__name__)


class EvalScheduler:
    """评估调度器：管理定时评估任务的创建、调度、执行和结果存储。"""

    def __init__(self, db_path: str = "data/scheduler.db"):
        self._engine = create_engine(f"sqlite:///{db_path}", echo=False)
        Base.metadata.create_all(self._engine)
        self._session_factory = sessionmaker(bind=self._engine, expire_on_commit=False)
        self._apscheduler = AsyncIOScheduler()
        self._running = False

    # ---- 调度任务 CRUD ----

    def create_schedule(self, schedule: EvalSchedule) -> str:
        """创建调度任务并注册到 APScheduler。"""
        session = self._session_factory()
        try:
            now = datetime.now(timezone.utc)
            row = EvalScheduleORM(
                schedule_id=schedule.schedule_id,
                name=schedule.name,
                agent_name=schedule.agent_name,
                agent_version=schedule.agent_version,
                dimension=schedule.dimension,
                task_ids_json=json.dumps(schedule.task_ids) if schedule.task_ids else None,
                cron=schedule.cron,
                enabled=1 if schedule.enabled else 0,
                scorer_type=schedule.scorer_type,
                judge_model=schedule.judge_model,
                badcase_enabled=1 if schedule.badcase_enabled else 0,
                badcase_threshold=schedule.badcase_threshold,
                badcase_max_per_run=schedule.badcase_max_per_run,
                alert_on_score_drop=1 if schedule.alert_on_score_drop else 0,
                alert_threshold=schedule.alert_threshold,
                alert_webhook=schedule.alert_webhook,
                alert_emails_json=json.dumps(schedule.alert_emails) if schedule.alert_emails else None,
                created_at=now,
                updated_at=now,
            )
            session.add(row)
            session.commit()

            # 注册到 APScheduler
            if schedule.enabled:
                self._add_aps_job(schedule)

            logger.info("调度任务创建成功: %s (%s)", schedule.schedule_id, schedule.name)
            return schedule.schedule_id

        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def get_schedule(self, schedule_id: str) -> EvalSchedule | None:
        """获取调度任务详情。"""
        session = self._session_factory()
        try:
            row = session.query(EvalScheduleORM).filter(
                EvalScheduleORM.schedule_id == schedule_id
            ).first()
            if row is None:
                return None
            return self._orm_to_model(row)
        finally:
            session.close()

    def list_schedules(self, enabled_only: bool = False) -> list[EvalSchedule]:
        """列出所有调度任务。"""
        session = self._session_factory()
        try:
            stmt = select(EvalScheduleORM).order_by(EvalScheduleORM.id.asc())
            if enabled_only:
                stmt = stmt.where(EvalScheduleORM.enabled == 1)
            rows = session.execute(stmt).scalars().all()
            return [self._orm_to_model(r) for r in rows]
        finally:
            session.close()

    def update_schedule(self, schedule_id: str, **kwargs: Any) -> bool:
        """更新调度任务配置。"""
        session = self._session_factory()
        try:
            row = session.query(EvalScheduleORM).filter(
                EvalScheduleORM.schedule_id == schedule_id
            ).first()
            if row is None:
                return False

            # 映射字段
            field_map = {
                "name": "name",
                "cron": "cron",
                "enabled": "enabled",
                "scorer_type": "scorer_type",
                "judge_model": "judge_model",
                "badcase_enabled": "badcase_enabled",
                "badcase_threshold": "badcase_threshold",
                "alert_on_score_drop": "alert_on_score_drop",
                "alert_threshold": "alert_threshold",
                "alert_webhook": "alert_webhook",
            }
            for key, col_name in field_map.items():
                if key in kwargs and kwargs[key] is not None:
                    val = kwargs[key]
                    if isinstance(val, bool):
                        val = 1 if val else 0
                    setattr(row, col_name, val)

            if "alert_emails" in kwargs and kwargs["alert_emails"] is not None:
                row.alert_emails_json = json.dumps(kwargs["alert_emails"])

            row.updated_at = datetime.now(timezone.utc)
            session.commit()

            # 更新 APScheduler job
            schedule = self._orm_to_model(row)
            self._remove_aps_job(schedule_id)
            if schedule.enabled:
                self._add_aps_job(schedule)

            logger.info("调度任务更新成功: %s", schedule_id)
            return True

        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def delete_schedule(self, schedule_id: str) -> bool:
        """删除调度任务。"""
        session = self._session_factory()
        try:
            row = session.query(EvalScheduleORM).filter(
                EvalScheduleORM.schedule_id == schedule_id
            ).first()
            if row is None:
                return False

            session.delete(row)
            session.commit()
            self._remove_aps_job(schedule_id)

            logger.info("调度任务删除成功: %s", schedule_id)
            return True

        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    # ---- 执行历史 ----

    def save_run(self, run: ScheduleRun) -> str:
        """保存一次调度执行记录。"""
        session = self._session_factory()
        try:
            row = ScheduleRunORM(
                run_id=run.run_id,
                schedule_id=run.schedule_id,
                status=run.status,
                traces_count=run.traces_count,
                avg_score=run.avg_score,
                badcase_count=run.badcase_count,
                alert_count=run.alert_count,
                error_message=run.error_message,
                started_at=datetime.fromisoformat(run.started_at) if run.started_at else datetime.now(timezone.utc),
                finished_at=datetime.fromisoformat(run.finished_at) if run.finished_at else None,
            )
            session.add(row)
            session.commit()
            return run.run_id

        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def update_run(self, run_id: str, **kwargs: Any) -> bool:
        """更新执行记录状态。"""
        session = self._session_factory()
        try:
            row = session.query(ScheduleRunORM).filter(
                ScheduleRunORM.run_id == run_id
            ).first()
            if row is None:
                return False

            for key, val in kwargs.items():
                if hasattr(row, key):
                    setattr(row, key, val)

            session.commit()
            return True

        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def list_runs(self, schedule_id: str, limit: int = 20) -> list[ScheduleRun]:
        """获取调度任务的执行历史。"""
        session = self._session_factory()
        try:
            rows = session.query(ScheduleRunORM).filter(
                ScheduleRunORM.schedule_id == schedule_id
            ).order_by(ScheduleRunORM.id.desc()).limit(limit).all()

            return [
                ScheduleRun(
                    run_id=r.run_id,
                    schedule_id=r.schedule_id,
                    status=r.status,
                    traces_count=r.traces_count,
                    avg_score=r.avg_score,
                    badcase_count=r.badcase_count,
                    alert_count=r.alert_count,
                    error_message=r.error_message,
                    started_at=r.started_at.isoformat() if r.started_at else "",
                    finished_at=r.finished_at.isoformat() if r.finished_at else None,
                )
                for r in rows
            ]
        finally:
            session.close()

    def update_schedule_last_run(self, schedule_id: str, status: str) -> None:
        """更新调度任务的上次运行信息。"""
        session = self._session_factory()
        try:
            row = session.query(EvalScheduleORM).filter(
                EvalScheduleORM.schedule_id == schedule_id
            ).first()
            if row:
                row.last_run_at = datetime.now(timezone.utc)
                row.last_run_status = status
                session.commit()
        except Exception:
            session.rollback()
        finally:
            session.close()

    # ---- APScheduler 管理 ----

    def start(self) -> None:
        """启动调度器，加载所有 enabled 的调度任务。"""
        if self._running:
            return

        schedules = self.list_schedules(enabled_only=True)
        for schedule in schedules:
            self._add_aps_job(schedule)

        self._apscheduler.start()
        self._running = True
        logger.info("调度器启动，已加载 %d 个调度任务", len(schedules))

    def stop(self) -> None:
        """停止调度器。"""
        if self._running:
            self._apscheduler.shutdown(wait=False)
            self._running = False
            logger.info("调度器已停止")

    def trigger_run(self, schedule_id: str) -> str | None:
        """手动触发一次调度执行。返回 run_id 或 None。"""
        schedule = self.get_schedule(schedule_id)
        if schedule is None:
            return None

        from agent_bench.scheduler.executor import run_scheduled_eval
        run_id = uuid.uuid4().hex
        # 同步执行（不通过 APScheduler）
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # 如果在 async 上下文中，用 create_task
                import threading
                result_holder = {}
                def _run():
                    new_loop = asyncio.new_event_loop()
                    try:
                        new_loop.run_until_complete(
                            run_scheduled_eval(schedule, run_id, self)
                        )
                    except Exception as e:
                        result_holder["error"] = str(e)
                    finally:
                        new_loop.close()
                t = threading.Thread(target=_run, daemon=True)
                t.start()
                t.join(timeout=300)
            else:
                loop.run_until_complete(run_scheduled_eval(schedule, run_id, self))
        except RuntimeError:
            asyncio.run(run_scheduled_eval(schedule, run_id, self))

        return run_id

    def _add_aps_job(self, schedule: EvalSchedule) -> None:
        """注册 APScheduler job。"""
        try:
            trigger = CronTrigger.from_crontab(schedule.cron)
            from agent_bench.scheduler.executor import run_scheduled_eval

            self._apscheduler.add_job(
                run_scheduled_eval,
                trigger=trigger,
                args=[schedule, None, self],
                id=schedule.schedule_id,
                replace_existing=True,
                name=f"eval-{schedule.name}",
            )
            logger.info("APScheduler job 注册: %s (cron=%s)", schedule.schedule_id, schedule.cron)
        except Exception as e:
            logger.error("APScheduler job 注册失败: %s - %s", schedule.schedule_id, e)

    def _remove_aps_job(self, schedule_id: str) -> None:
        """移除 APScheduler job。"""
        try:
            self._apscheduler.remove_job(schedule_id)
        except Exception:
            pass  # job 可能不存在

    # ---- 内部工具 ----

    @staticmethod
    def _orm_to_model(row: EvalScheduleORM) -> EvalSchedule:
        """ORM → Pydantic 模型。"""
        return EvalSchedule(
            schedule_id=row.schedule_id,
            name=row.name,
            agent_name=row.agent_name,
            agent_version=row.agent_version,
            dimension=row.dimension,
            task_ids=json.loads(row.task_ids_json) if row.task_ids_json else None,
            cron=row.cron,
            enabled=bool(row.enabled),
            scorer_type=row.scorer_type,
            judge_model=row.judge_model,
            badcase_enabled=bool(row.badcase_enabled),
            badcase_threshold=row.badcase_threshold,
            badcase_max_per_run=row.badcase_max_per_run,
            alert_on_score_drop=bool(row.alert_on_score_drop),
            alert_threshold=row.alert_threshold,
            alert_webhook=row.alert_webhook,
            alert_emails=json.loads(row.alert_emails_json) if row.alert_emails_json else None,
            created_at=row.created_at.isoformat() if row.created_at else "",
            updated_at=row.updated_at.isoformat() if row.updated_at else "",
            last_run_at=row.last_run_at.isoformat() if row.last_run_at else None,
            last_run_status=row.last_run_status,
        )
