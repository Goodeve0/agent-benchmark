"""BadCase 数据模型 — Pydantic + SQLAlchemy ORM。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import (
    Column,
    DateTime,
    Float,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class BadCaseORM(Base):
    """BadCase ORM。"""

    __tablename__ = "bad_cases"

    id = Column(Integer, primary_key=True, autoincrement=True)
    trace_id = Column(String(64), nullable=False, index=True)
    task_id = Column(String(128), nullable=False)
    agent_name = Column(String(128), nullable=False, index=True)
    agent_version = Column(String(64), nullable=False, default="")
    score = Column(Float, nullable=False)
    max_score = Column(Float, nullable=False)
    percentage = Column(Float, nullable=False)
    dimension = Column(String(64), nullable=True)
    failure_reason = Column(Text, nullable=True)
    reflux_source = Column(String(16), nullable=False, default="auto")
    resolved = Column(Integer, nullable=False, default=0)
    created_at = Column(
        DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    resolved_at = Column(DateTime, nullable=True)


class BadCase(BaseModel):
    """BadCase 记录。"""

    trace_id: str = ""
    task_id: str = ""
    agent_name: str = ""
    agent_version: str = ""
    score: float = 0.0
    max_score: float = 100.0
    percentage: float = 0.0
    dimension: str | None = None
    failure_reason: str | None = None
    reflux_source: Literal["auto", "manual"] = "auto"
    resolved: bool = False
    created_at: str = ""
    resolved_at: str | None = None


class BadCaseQuery(BaseModel):
    """BadCase 查询参数。"""

    agent_name: str | None = None
    agent_version: str | None = None
    dimension: str | None = None
    reflux_source: str | None = None
    resolved: bool | None = None
    min_percentage: float | None = None
    max_percentage: float | None = None
    limit: int = 50
    offset: int = 0


class BadCaseSummary(BaseModel):
    """BadCase 统计摘要。"""

    total: int = 0
    unresolved: int = 0
    by_agent: dict[str, int] = Field(default_factory=dict)
    by_dimension: dict[str, int] = Field(default_factory=dict)
    avg_percentage: float = 0.0
