"""Trace 数据模型 — Pydantic（API 层）+ SQLAlchemy ORM（存储层）。"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import (
    Column,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    create_engine,
)
from sqlalchemy.orm import declarative_base, sessionmaker

Base = declarative_base()


# ---- SQLAlchemy ORM 模型 ----


class TraceORM(Base):
    """Trace 主表 ORM 模型。"""

    __tablename__ = "traces"

    id = Column(Integer, primary_key=True, autoincrement=True)
    trace_id = Column(String(64), unique=True, nullable=False, index=True)
    task_id = Column(String(128), nullable=False, index=True)
    agent_name = Column(String(128), nullable=False, index=True)
    agent_version = Column(String(64), nullable=False, default="")
    source = Column(String(32), nullable=False, default="sdk")  # sdk / runner
    project_id = Column(String(64), nullable=False, default="default", index=True)
    total_tokens = Column(Integer, nullable=False, default=0)
    total_steps = Column(Integer, nullable=False, default=0)
    final_response = Column(Text, nullable=False, default="")
    execution_time = Column(Float, nullable=False, default=0.0)
    success = Column(Integer, nullable=False, default=1)  # 0/1 for SQLite bool
    error = Column(Text, nullable=True)
    metadata_json = Column(Text, nullable=True)  # JSON 字符串
    canonical_json = Column(Text, nullable=False)  # 计算 payload_hash 时的原始 JSON
    prev_hash = Column(String(64), nullable=True)
    payload_hash = Column(String(64), nullable=False)
    created_at = Column(
        DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    updated_at = Column(
        DateTime, nullable=False, default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class TraceActionORM(Base):
    """Trace Action 明细表 ORM 模型。"""

    __tablename__ = "trace_actions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    trace_id = Column(String(64), nullable=False, index=True)
    step = Column(Integer, nullable=False)
    action_type = Column(String(32), nullable=False)
    tool_name = Column(String(128), nullable=True)
    parameters_json = Column(Text, nullable=True)
    result_json = Column(Text, nullable=True)
    content = Column(Text, nullable=True)
    timestamp = Column(Float, nullable=False)
    duration_ms = Column(Float, nullable=True)
    metadata_json = Column(Text, nullable=True)


# 索引
Index("idx_traces_agent_version", TraceORM.agent_name, TraceORM.agent_version)
Index("idx_traces_created", TraceORM.created_at)
Index("idx_actions_trace_id", TraceActionORM.trace_id)


# ---- Pydantic 数据模型（API 层使用）----


class ActionRecord(BaseModel):
    """单条 Action 上报记录（SDK → Server）。"""

    action_type: Literal["tool_call", "response", "thinking"]
    tool_name: str | None = None
    parameters: dict[str, Any] | None = None
    result: Any | None = None
    content: str | None = None
    timestamp: float
    duration_ms: float | None = None


class TracePayload(BaseModel):
    """一次 Trace 的完整上报数据（SDK → Server）。"""

    trace_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    task_id: str = ""
    agent_name: str = ""
    agent_version: str = ""
    project_id: str = "default"
    source: Literal["sdk", "runner"] = "sdk"
    actions: list[ActionRecord] = Field(default_factory=list)
    total_tokens: int = 0
    total_steps: int = 0
    final_response: str = ""
    execution_time: float = 0.0
    success: bool = True
    error: str | None = None
    metadata: dict[str, Any] | None = None
    # 链式哈希
    prev_hash: str | None = None
    payload_hash: str = ""


class TraceQuery(BaseModel):
    """Trace 查询参数。"""

    task_id: str | None = None
    agent_name: str | None = None
    agent_version: str | None = None
    project_id: str | None = None
    source: str | None = None
    success: bool | None = None
    start_time: str | None = None  # ISO 8601
    end_time: str | None = None  # ISO 8601
    limit: int = 50
    offset: int = 0


class TraceSummary(BaseModel):
    """Trace 查询结果摘要（不含 actions 明细）。"""

    trace_id: str
    task_id: str
    agent_name: str
    agent_version: str
    source: str
    project_id: str
    total_tokens: int
    total_steps: int
    final_response: str
    execution_time: float
    success: bool
    error: str | None = None
    payload_hash: str
    created_at: str = ""


class TraceDetail(TraceSummary):
    """Trace 详情（含 actions 明细）。"""

    actions: list[ActionRecord] = Field(default_factory=list)
    metadata: dict[str, Any] | None = None
    prev_hash: str | None = None


class TraceStats(BaseModel):
    """Trace 统计信息。"""

    total_traces: int
    total_actions: int
    success_rate: float
    avg_execution_time: float
    avg_tokens: float
    agent_counts: dict[str, int]  # agent_name → count


class IntegrityReport(BaseModel):
    """链式哈希完整性校验报告。"""

    total_traces: int
    verified: int
    broken: int
    broken_trace_ids: list[str]
    is_valid: bool
