"""告警引擎 — 四种告警规则检测 + 通知。"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from agent_bench.alert.models import (
    Alert,
    AlertORM,
    AlertQuery,
    AlertSeverity,
    AlertStats,
    AlertType,
    Base,
)

logger = logging.getLogger(__name__)


class AlertEngine:
    """告警引擎：规则检测 + 通知 + 存储。"""

    def __init__(self, db_path: str = "data/alerts.db"):
        self._engine = create_engine(f"sqlite:///{db_path}", echo=False)
        Base.metadata.create_all(self._engine)
        self._session_factory = sessionmaker(bind=self._engine, expire_on_commit=False)

    # ---- 告警规则检测 ----

    def check_and_alert(
        self,
        agent_name: str,
        agent_version: str | None = None,
        current_score: float = 0.0,
        schedule: Any = None,
    ) -> list[Alert]:
        """执行所有告警规则检查，返回触发的告警列表。"""
        alerts: list[Alert] = []

        # 规则1: 分数阈值
        if schedule and schedule.alert_threshold > 0:
            alert = self._check_threshold(
                agent_name, agent_version, current_score,
                schedule.alert_threshold, schedule.schedule_id,
            )
            if alert:
                alerts.append(alert)

        # 规则2: 连续下降
        if schedule and schedule.alert_on_score_drop:
            alert = self._check_consecutive_drop(
                agent_name, agent_version, schedule.schedule_id,
            )
            if alert:
                alerts.append(alert)

        # 规则3: 突变检测
        alert = self._check_spike(
            agent_name, agent_version, current_score,
        )
        if alert:
            alerts.append(alert)

        # 规则4: 错误率
        alert = self._check_error_rate(
            agent_name, agent_version,
        )
        if alert:
            alerts.append(alert)

        # 存储并通知
        for alert in alerts:
            self.save(alert)
            self._notify(alert, schedule)

        return alerts

    def _check_threshold(
        self,
        agent_name: str,
        agent_version: str | None,
        current_score: float,
        threshold: float,
        schedule_id: str | None = None,
    ) -> Alert | None:
        """规则1: 分数阈值检测。"""
        if current_score < threshold:
            severity = AlertSeverity.CRITICAL if current_score < threshold * 0.5 else AlertSeverity.WARNING
            return Alert(
                schedule_id=schedule_id,
                alert_type=AlertType.THRESHOLD,
                severity=severity,
                agent_name=agent_name,
                agent_version=agent_version,
                message=f"Agent '{agent_name}' 得分 {current_score:.1f}% 低于阈值 {threshold:.1f}%",
                current_value=current_score,
                threshold_value=threshold,
            )
        return None

    def _check_consecutive_drop(
        self,
        agent_name: str,
        agent_version: str | None,
        schedule_id: str | None = None,
        consecutive_count: int = 3,
    ) -> Alert | None:
        """规则2: 连续 N 次评分下降检测。"""
        session = self._session_factory()
        try:
            # 查询最近 N 次评分记录（通过 schedule_runs）
            from agent_bench.scheduler.models import ScheduleRunORM
            # 用独立查询：直接看最近 N 次告警是否都是 threshold 类型
            recent_alerts = session.query(AlertORM).filter(
                AlertORM.agent_name == agent_name,
                AlertORM.alert_type == AlertType.THRESHOLD,
            ).order_by(AlertORM.id.desc()).limit(consecutive_count).all()

            if len(recent_alerts) >= consecutive_count:
                # 检查是否连续下降（每条 current_value < 上一条）
                is_consecutive = True
                for i in range(len(recent_alerts) - 1):
                    if recent_alerts[i].current_value is None or recent_alerts[i + 1].current_value is None:
                        is_consecutive = False
                        break
                    if recent_alerts[i].current_value >= recent_alerts[i + 1].current_value:
                        is_consecutive = False
                        break

                if is_consecutive:
                    return Alert(
                        schedule_id=schedule_id,
                        alert_type=AlertType.CONSECUTIVE_DROP,
                        severity=AlertSeverity.CRITICAL,
                        agent_name=agent_name,
                        agent_version=agent_version,
                        message=f"Agent '{agent_name}' 连续 {consecutive_count} 次评分下降",
                        current_value=recent_alerts[0].current_value,
                    )
            return None
        finally:
            session.close()

    def _check_spike(
        self,
        agent_name: str,
        agent_version: str | None,
        current_score: float,
        spike_threshold: float = 25.0,
    ) -> Alert | None:
        """规则3: 突变检测 — 环比下降超过 spike_threshold%。"""
        session = self._session_factory()
        try:
            # 查找上一次同 agent 的 threshold 告警作为历史参考
            last_alert = session.query(AlertORM).filter(
                AlertORM.agent_name == agent_name,
                AlertORM.current_value.isnot(None),
            ).order_by(AlertORM.id.desc()).first()

            if last_alert and last_alert.current_value is not None:
                prev_score = last_alert.current_value
                if prev_score > 0:
                    drop_pct = (prev_score - current_score) / prev_score * 100
                    if drop_pct > spike_threshold:
                        return Alert(
                            alert_type=AlertType.SPIKE,
                            severity=AlertSeverity.CRITICAL,
                            agent_name=agent_name,
                            agent_version=agent_version,
                            message=(
                                f"Agent '{agent_name}' 评分突变："
                                f"从 {prev_score:.1f}% 降至 {current_score:.1f}%（下降 {drop_pct:.1f}%）"
                            ),
                            current_value=current_score,
                            threshold_value=spike_threshold,
                        )
            return None
        finally:
            session.close()

    def _check_error_rate(
        self,
        agent_name: str,
        agent_version: str | None,
        error_rate_threshold: float = 30.0,
    ) -> Alert | None:
        """规则4: 错误率检测 — 失败 Trace 占比超阈值。"""
        try:
            from agent_bench.trace_store import TraceStore
            import os
            trace_store = TraceStore(db_path=os.environ.get("AGENT_BENCH_DB_PATH", "data/traces.db"))

            from agent_bench.trace_store.models import TraceQuery
            query = TraceQuery(agent_name=agent_name, agent_version=agent_version, limit=1000)
            all_traces, total = trace_store.query_traces(query)

            if total < 5:  # 样本太少不检测
                return None

            failed = sum(1 for t in all_traces if not t.success)
            error_rate = failed / total * 100

            if error_rate > error_rate_threshold:
                return Alert(
                    alert_type=AlertType.ERROR_RATE,
                    severity=AlertSeverity.WARNING if error_rate < 50 else AlertSeverity.CRITICAL,
                    agent_name=agent_name,
                    agent_version=agent_version,
                    message=(
                        f"Agent '{agent_name}' 错误率 {error_rate:.1f}% 超过阈值 "
                        f"{error_rate_threshold:.1f}%（{failed}/{total} 失败）"
                    ),
                    current_value=error_rate,
                    threshold_value=error_rate_threshold,
                )
            return None

        except Exception as e:
            logger.warning("错误率检测失败: %s", e)
            return None

    # ---- 存储 ----

    def save(self, alert: Alert) -> int:
        """保存告警记录。"""
        session = self._session_factory()
        try:
            row = AlertORM(
                schedule_id=alert.schedule_id,
                alert_type=alert.alert_type,
                severity=alert.severity,
                agent_name=alert.agent_name,
                agent_version=alert.agent_version,
                dimension=alert.dimension,
                message=alert.message,
                current_value=alert.current_value,
                threshold_value=alert.threshold_value,
                notified=1 if alert.notified else 0,
            )
            session.add(row)
            session.commit()
            logger.info("告警保存: %s (%s) - %s", alert.alert_type, alert.severity, alert.message[:60])
            return row.id

        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def query(self, query: AlertQuery) -> tuple[list[Alert], int]:
        """查询告警记录。"""
        session = self._session_factory()
        try:
            stmt = select(AlertORM)

            if query.schedule_id:
                stmt = stmt.where(AlertORM.schedule_id == query.schedule_id)
            if query.alert_type:
                stmt = stmt.where(AlertORM.alert_type == query.alert_type)
            if query.severity:
                stmt = stmt.where(AlertORM.severity == query.severity)
            if query.agent_name:
                stmt = stmt.where(AlertORM.agent_name == query.agent_name)
            if query.resolved is not None:
                if query.resolved:
                    stmt = stmt.where(AlertORM.resolved_at.isnot(None))
                else:
                    stmt = stmt.where(AlertORM.resolved_at.is_(None))

            count_stmt = select(func.count()).select_from(stmt.subquery())
            total = session.execute(count_stmt).scalar() or 0

            stmt = stmt.order_by(AlertORM.created_at.desc()).offset(query.offset).limit(query.limit)
            rows = session.execute(stmt).scalars().all()

            results = [self._orm_to_model(r) for r in rows]
            return results, total

        finally:
            session.close()

    def resolve(self, alert_id: int) -> bool:
        """标记告警为已处理。"""
        session = self._session_factory()
        try:
            row = session.query(AlertORM).filter(AlertORM.id == alert_id).first()
            if row is None:
                return False
            row.resolved_at = datetime.now(timezone.utc)
            session.commit()
            return True
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def get_stats(self, agent_name: str | None = None) -> AlertStats:
        """获取告警统计。"""
        session = self._session_factory()
        try:
            base = session.query(AlertORM)
            if agent_name:
                base = base.filter(AlertORM.agent_name == agent_name)

            total = base.count()
            unresolved = base.filter(AlertORM.resolved_at.is_(None)).count()

            # 按类型
            type_rows = session.query(
                AlertORM.alert_type, func.count(AlertORM.id)
            ).group_by(AlertORM.alert_type).all()
            by_type = {t or "unknown": c for t, c in type_rows}

            # 按严重级别
            sev_rows = session.query(
                AlertORM.severity, func.count(AlertORM.id)
            ).group_by(AlertORM.severity).all()
            by_severity = {s or "unknown": c for s, c in sev_rows}

            return AlertStats(
                total=total,
                unresolved=unresolved,
                by_type=by_type,
                by_severity=by_severity,
            )
        finally:
            session.close()

    # ---- 通知 ----

    def _notify(self, alert: Alert, schedule: Any = None) -> None:
        """发送告警通知。"""
        # Webhook 通知
        webhook_url = None
        if schedule and hasattr(schedule, "alert_webhook") and schedule.alert_webhook:
            webhook_url = schedule.alert_webhook

        if webhook_url:
            self._send_webhook(alert, webhook_url)

        # Email 通知（日志占位）
        if schedule and hasattr(schedule, "alert_emails") and schedule.alert_emails:
            logger.info(
                "告警邮件通知: %s → %s",
                alert.message[:60],
                ", ".join(schedule.alert_emails),
            )

        alert.notified = True

    @staticmethod
    def _send_webhook(alert: Alert, webhook_url: str) -> None:
        """发送 Webhook 通知。"""
        try:
            import httpx
            payload = {
                "alert_type": alert.alert_type,
                "severity": alert.severity,
                "agent_name": alert.agent_name,
                "message": alert.message,
                "current_value": alert.current_value,
                "threshold_value": alert.threshold_value,
                "timestamp": alert.created_at or datetime.now(timezone.utc).isoformat(),
            }
            # 同步发送（生产环境可用异步）
            with httpx.Client(timeout=5.0) as client:
                resp = client.post(webhook_url, json=payload)
                if resp.status_code >= 400:
                    logger.warning("Webhook 通知失败: %s → %d", webhook_url, resp.status_code)
                else:
                    logger.info("Webhook 通知成功: %s", webhook_url)
        except Exception as e:
            logger.warning("Webhook 通知异常: %s - %s", webhook_url, e)

    @staticmethod
    def _orm_to_model(row: AlertORM) -> Alert:
        """ORM → Pydantic。"""
        return Alert(
            schedule_id=row.schedule_id,
            alert_type=row.alert_type,
            severity=row.severity,
            agent_name=row.agent_name,
            agent_version=row.agent_version,
            dimension=row.dimension,
            message=row.message,
            current_value=row.current_value,
            threshold_value=row.threshold_value,
            notified=bool(row.notified),
            created_at=row.created_at.isoformat() if row.created_at else "",
            resolved_at=row.resolved_at.isoformat() if row.resolved_at else None,
        )
