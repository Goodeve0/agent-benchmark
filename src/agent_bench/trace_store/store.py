"""TraceStore 核心存储管理器。"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import TYPE_CHECKING

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from agent_bench.trace_store.models import (
    Base,
    TraceActionORM,
    TraceDetail,
    TraceORM,
    TraceQuery,
    TraceStats,
    TraceSummary,
)

if TYPE_CHECKING:
    from agent_bench.trace_store.models import ActionRecord, IntegrityReport, TracePayload

logger = logging.getLogger(__name__)


class TraceStore:
    """Trace 持久化存储管理器。

    负责:
    - 数据库初始化（建表）
    - Trace 写入（含链式哈希计算）
    - Trace 查询（分页 + 过滤）
    - 链式哈希完整性验证
    - Trace → AgentTrace 转换（供 Scorer 使用）
    """

    def __init__(self, db_path: str = "traces.db") -> None:
        """初始化 TraceStore。

        Args:
            db_path: SQLite 数据库文件路径。
        """
        if not db_path.startswith("sqlite:///"):
            db_path = f"sqlite:///{db_path}"
        self._engine = create_engine(db_path, echo=False)
        self._SessionLocal = sessionmaker(bind=self._engine)
        # 建表
        Base.metadata.create_all(self._engine)
        logger.info("TraceStore 初始化完成: %s", db_path)

    def _get_session(self) -> Session:
        return self._SessionLocal()

    # ---- 写入 ----

    def save_trace(self, payload: TracePayload) -> str:
        """保存一条 Trace。

        自动计算链式哈希：payload_hash = SHA-256(payload JSON + prev_hash)。

        Args:
            payload: 上报的 Trace 数据。

        Returns:
            trace_id
        """
        session = self._get_session()
        try:
            # 如果没有 prev_hash，取数据库中最后一条 Trace 的 payload_hash
            if payload.prev_hash is None:
                last_trace = session.query(TraceORM).order_by(
                    TraceORM.id.desc()
                ).first()
                payload.prev_hash = last_trace.payload_hash if last_trace else "GENESIS"

            # 计算 payload_hash
            payload_dict = payload.model_dump(exclude={"payload_hash", "prev_hash"})
            payload_json = json.dumps(payload_dict, ensure_ascii=False, sort_keys=True, default=str)
            hash_input = f"{payload_json}:{payload.prev_hash}"
            payload.payload_hash = hashlib.sha256(hash_input.encode()).hexdigest()

            # 写入 Trace 主表
            trace_row = TraceORM(
                trace_id=payload.trace_id,
                task_id=payload.task_id,
                agent_name=payload.agent_name,
                agent_version=payload.agent_version,
                source=payload.source,
                project_id=payload.project_id,
                total_tokens=payload.total_tokens,
                total_steps=payload.total_steps or len(payload.actions),
                final_response=payload.final_response,
                execution_time=payload.execution_time,
                success=1 if payload.success else 0,
                error=payload.error,
                metadata_json=json.dumps(payload.metadata, ensure_ascii=False) if payload.metadata else None,
                canonical_json=payload_json,
                prev_hash=payload.prev_hash,
                payload_hash=payload.payload_hash,
            )
            session.add(trace_row)

            # 写入 Action 明细
            for i, action in enumerate(payload.actions, 1):
                action_row = TraceActionORM(
                    trace_id=payload.trace_id,
                    step=i,
                    action_type=action.action_type,
                    tool_name=action.tool_name,
                    parameters_json=json.dumps(action.parameters, ensure_ascii=False) if action.parameters else None,
                    result_json=json.dumps(action.result, ensure_ascii=False, default=str) if action.result is not None else None,
                    content=action.content,
                    timestamp=action.timestamp,
                    duration_ms=action.duration_ms,
                )
                session.add(action_row)

            session.commit()
            logger.info(
                "Trace 保存成功: %s (agent=%s, task=%s)",
                payload.trace_id, payload.agent_name, payload.task_id,
            )
            return payload.trace_id

        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def save_traces_batch(self, payloads: list[TracePayload]) -> list[str]:
        """批量保存 Trace（顺序写入以维护链式哈希）。"""
        trace_ids = []
        for payload in payloads:
            tid = self.save_trace(payload)
            trace_ids.append(tid)
        return trace_ids

    # ---- 查询 ----

    def query_traces(self, query: TraceQuery) -> tuple[list[TraceSummary], int]:
        """查询 Trace 列表（分页 + 过滤）。

        Returns:
            (结果列表, 总数)
        """
        session = self._get_session()
        try:
            stmt = select(TraceORM)

            # 过滤条件
            if query.task_id:
                stmt = stmt.where(TraceORM.task_id == query.task_id)
            if query.agent_name:
                stmt = stmt.where(TraceORM.agent_name == query.agent_name)
            if query.agent_version:
                stmt = stmt.where(TraceORM.agent_version == query.agent_version)
            if query.project_id:
                stmt = stmt.where(TraceORM.project_id == query.project_id)
            if query.source:
                stmt = stmt.where(TraceORM.source == query.source)
            if query.success is not None:
                stmt = stmt.where(TraceORM.success == (1 if query.success else 0))
            if query.start_time:
                from datetime import datetime
                start_dt = datetime.fromisoformat(query.start_time)
                stmt = stmt.where(TraceORM.created_at >= start_dt)
            if query.end_time:
                from datetime import datetime
                end_dt = datetime.fromisoformat(query.end_time)
                stmt = stmt.where(TraceORM.created_at <= end_dt)

            # 总数
            count_stmt = select(func.count()).select_from(stmt.subquery())
            total = session.execute(count_stmt).scalar() or 0

            # 分页
            stmt = stmt.order_by(TraceORM.created_at.desc()).offset(query.offset).limit(query.limit)
            rows = session.execute(stmt).scalars().all()

            results = [
                TraceSummary(
                    trace_id=r.trace_id,
                    task_id=r.task_id,
                    agent_name=r.agent_name,
                    agent_version=r.agent_version,
                    source=r.source,
                    project_id=r.project_id,
                    total_tokens=r.total_tokens,
                    total_steps=r.total_steps,
                    final_response=r.final_response[:200] if r.final_response else "",
                    execution_time=r.execution_time,
                    success=bool(r.success),
                    error=r.error,
                    payload_hash=r.payload_hash,
                    created_at=r.created_at.isoformat() if r.created_at else "",
                )
                for r in rows
            ]
            return results, total

        finally:
            session.close()

    def get_trace_detail(self, trace_id: str) -> TraceDetail | None:
        """获取 Trace 详情（含 actions 明细）。"""
        session = self._get_session()
        try:
            trace_row = session.query(TraceORM).filter(
                TraceORM.trace_id == trace_id
            ).first()
            if trace_row is None:
                return None

            # 查询 actions
            action_rows = session.query(TraceActionORM).filter(
                TraceActionORM.trace_id == trace_id
            ).order_by(TraceActionORM.step).all()

            from agent_bench.trace_store.models import ActionRecord
            actions = [
                ActionRecord(
                    action_type=a.action_type,
                    tool_name=a.tool_name,
                    parameters=json.loads(a.parameters_json) if a.parameters_json else None,
                    result=json.loads(a.result_json) if a.result_json else None,
                    content=a.content,
                    timestamp=a.timestamp,
                    duration_ms=a.duration_ms,
                )
                for a in action_rows
            ]

            return TraceDetail(
                trace_id=trace_row.trace_id,
                task_id=trace_row.task_id,
                agent_name=trace_row.agent_name,
                agent_version=trace_row.agent_version,
                source=trace_row.source,
                project_id=trace_row.project_id,
                total_tokens=trace_row.total_tokens,
                total_steps=trace_row.total_steps,
                final_response=trace_row.final_response,
                execution_time=trace_row.execution_time,
                success=bool(trace_row.success),
                error=trace_row.error,
                payload_hash=trace_row.payload_hash,
                created_at=trace_row.created_at.isoformat() if trace_row.created_at else "",
                actions=actions,
                metadata=json.loads(trace_row.metadata_json) if trace_row.metadata_json else None,
                prev_hash=trace_row.prev_hash,
            )

        finally:
            session.close()

    def get_stats(self, project_id: str | None = None) -> TraceStats:
        """获取 Trace 统计信息。"""
        session = self._get_session()
        try:
            base = session.query(TraceORM)
            if project_id:
                base = base.filter(TraceORM.project_id == project_id)

            total = base.count()
            success_count = base.filter(TraceORM.success == 1).count()
            avg_time = session.query(func.avg(TraceORM.execution_time)).scalar() or 0.0
            avg_tokens = session.query(func.avg(TraceORM.total_tokens)).scalar() or 0.0
            total_actions = session.query(TraceActionORM).count()

            # Agent 分布
            agent_rows = session.query(
                TraceORM.agent_name, func.count(TraceORM.id)
            ).group_by(TraceORM.agent_name).all()
            agent_counts = {name: count for name, count in agent_rows}

            return TraceStats(
                total_traces=total,
                total_actions=total_actions,
                success_rate=success_count / total if total > 0 else 0.0,
                avg_execution_time=round(avg_time, 4),
                avg_tokens=round(avg_tokens, 1),
                agent_counts=agent_counts,
            )

        finally:
            session.close()

    # ---- 链式哈希验证 ----

    def verify_integrity(self, project_id: str | None = None) -> IntegrityReport:
        """验证链式哈希完整性。"""
        from agent_bench.trace_store.models import IntegrityReport

        session = self._get_session()
        try:
            stmt = select(TraceORM).order_by(TraceORM.id.asc())
            if project_id:
                stmt = stmt.where(TraceORM.project_id == project_id)

            rows = session.execute(stmt).scalars().all()

            broken_ids: list[str] = []
            prev_hash = "GENESIS"

            for row in rows:
                # 检查 prev_hash 链接
                if row.prev_hash != prev_hash:
                    broken_ids.append(row.trace_id)
                    prev_hash = row.payload_hash
                    continue

                # 使用存储的 canonical_json 重新计算 payload_hash 验证
                hash_input = f"{row.canonical_json}:{row.prev_hash}"
                expected_hash = hashlib.sha256(hash_input.encode()).hexdigest()

                if row.payload_hash != expected_hash:
                    broken_ids.append(row.trace_id)

                prev_hash = row.payload_hash

            verified = len(rows) - len(broken_ids)
            return IntegrityReport(
                total_traces=len(rows),
                verified=verified,
                broken=len(broken_ids),
                broken_trace_ids=broken_ids,
                is_valid=len(broken_ids) == 0,
            )

        finally:
            session.close()

    # ---- Trace → AgentTrace 转换 ----

    def trace_to_agent_trace(self, trace_id: str) -> "object | None":
        """将存储的 Trace 转换为 AgentTrace 模型（供 Scorer 使用）。"""
        from agent_bench.models import AgentAction, AgentTrace

        detail = self.get_trace_detail(trace_id)
        if detail is None:
            return None

        actions = [
            AgentAction(
                step=i,
                action_type=a.action_type,
                tool_name=a.tool_name,
                parameters=a.parameters,
                result=a.result,
                content=a.content,
                timestamp=a.timestamp,
            )
            for i, a in enumerate(detail.actions, 1)
        ]

        return AgentTrace(
            task_id=detail.task_id,
            actions=actions,
            total_tokens=detail.total_tokens,
            total_steps=detail.total_steps,
            final_response=detail.final_response,
            execution_time=detail.execution_time,
            success=detail.success,
            error=detail.error,
            metadata=detail.metadata,
        )
