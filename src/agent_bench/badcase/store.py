"""BadCase 存储 — CRUD + 统计 + 回流。"""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from agent_bench.badcase.models import (
    Base,
    BadCase,
    BadCaseORM,
    BadCaseQuery,
    BadCaseSummary,
)

logger = logging.getLogger(__name__)


class BadCaseStore:
    """BadCase 存储管理。"""

    def __init__(self, db_path: str = "data/badcases.db"):
        self._engine = create_engine(f"sqlite:///{db_path}", echo=False)
        Base.metadata.create_all(self._engine)
        self._session_factory = sessionmaker(bind=self._engine, expire_on_commit=False)

    def save(self, badcase: BadCase) -> int:
        """保存一条 BadCase 记录。"""
        session = self._session_factory()
        try:
            from datetime import datetime, timezone
            row = BadCaseORM(
                trace_id=badcase.trace_id,
                task_id=badcase.task_id,
                agent_name=badcase.agent_name,
                agent_version=badcase.agent_version,
                score=badcase.score,
                max_score=badcase.max_score,
                percentage=badcase.percentage,
                dimension=badcase.dimension,
                failure_reason=badcase.failure_reason,
                reflux_source=badcase.reflux_source,
                resolved=1 if badcase.resolved else 0,
            )
            session.add(row)
            session.commit()
            logger.info(
                "BadCase 保存: trace_id=%s, agent=%s, score=%.1f%%",
                badcase.trace_id, badcase.agent_name, badcase.percentage,
            )
            return row.id

        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def save_batch(self, badcases: list[BadCase]) -> list[int]:
        """批量保存 BadCase。"""
        return [self.save(bc) for bc in badcases]

    def query(self, query: BadCaseQuery) -> tuple[list[BadCase], int]:
        """查询 BadCase（分页 + 过滤）。

        Returns:
            (结果列表, 总数)
        """
        session = self._session_factory()
        try:
            stmt = select(BadCaseORM)

            if query.agent_name:
                stmt = stmt.where(BadCaseORM.agent_name == query.agent_name)
            if query.agent_version:
                stmt = stmt.where(BadCaseORM.agent_version == query.agent_version)
            if query.dimension:
                stmt = stmt.where(BadCaseORM.dimension == query.dimension)
            if query.reflux_source:
                stmt = stmt.where(BadCaseORM.reflux_source == query.reflux_source)
            if query.resolved is not None:
                stmt = stmt.where(BadCaseORM.resolved == (1 if query.resolved else 0))
            if query.min_percentage is not None:
                stmt = stmt.where(BadCaseORM.percentage >= query.min_percentage)
            if query.max_percentage is not None:
                stmt = stmt.where(BadCaseORM.percentage <= query.max_percentage)

            # 总数
            count_stmt = select(func.count()).select_from(stmt.subquery())
            total = session.execute(count_stmt).scalar() or 0

            # 分页
            stmt = stmt.order_by(BadCaseORM.created_at.desc()).offset(query.offset).limit(query.limit)
            rows = session.execute(stmt).scalars().all()

            results = [self._orm_to_model(r) for r in rows]
            return results, total

        finally:
            session.close()

    def resolve(self, trace_id: str) -> bool:
        """标记 BadCase 为已解决。"""
        session = self._session_factory()
        try:
            from datetime import datetime, timezone
            row = session.query(BadCaseORM).filter(
                BadCaseORM.trace_id == trace_id,
                BadCaseORM.resolved == 0,
            ).first()
            if row is None:
                return False
            row.resolved = 1
            row.resolved_at = datetime.now(timezone.utc)
            session.commit()
            return True
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def get_stats(self, agent_name: str | None = None) -> BadCaseSummary:
        """获取 BadCase 统计摘要。"""
        session = self._session_factory()
        try:
            base = session.query(BadCaseORM)
            if agent_name:
                base = base.filter(BadCaseORM.agent_name == agent_name)

            total = base.count()
            unresolved = base.filter(BadCaseORM.resolved == 0).count()

            # 按 agent 分布
            agent_rows = session.query(
                BadCaseORM.agent_name, func.count(BadCaseORM.id)
            ).group_by(BadCaseORM.agent_name).all()
            by_agent = {name: count for name, count in agent_rows}

            # 按 dimension 分布
            dim_rows = session.query(
                BadCaseORM.dimension, func.count(BadCaseORM.id)
            ).filter(BadCaseORM.dimension.isnot(None)).group_by(BadCaseORM.dimension).all()
            by_dimension = {dim or "unknown": count for dim, count in dim_rows}

            # 平均得分率
            avg_pct = session.query(func.avg(BadCaseORM.percentage)).scalar() or 0.0

            return BadCaseSummary(
                total=total,
                unresolved=unresolved,
                by_agent=by_agent,
                by_dimension=by_dimension,
                avg_percentage=round(avg_pct, 4),
            )
        finally:
            session.close()

    @staticmethod
    def _orm_to_model(row: BadCaseORM) -> BadCase:
        """ORM → Pydantic。"""
        return BadCase(
            trace_id=row.trace_id,
            task_id=row.task_id,
            agent_name=row.agent_name,
            agent_version=row.agent_version,
            score=row.score,
            max_score=row.max_score,
            percentage=row.percentage,
            dimension=row.dimension,
            failure_reason=row.failure_reason,
            reflux_source=row.reflux_source,
            resolved=bool(row.resolved),
            created_at=row.created_at.isoformat() if row.created_at else "",
            resolved_at=row.resolved_at.isoformat() if row.resolved_at else None,
        )
