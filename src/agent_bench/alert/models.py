"""告警数据模型 — Pydantic + SQLAlchemy ORM。"""

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


class AlertType:
    """告警类型常量。"""

    THRESHOLD = "threshold"           # 分数阈值
    CONSECUTIVE_DROP = "consecutive_drop"  # 连续下降
    SPIKE = "spike"                   # 突变检测（环比下降超 X%）
    ERROR_RATE = "error_rate"         # 异常率


class AlertSeverity:
    """告警严重级别常量。"""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class AlertORM(Base):
    """告警记录 ORM。"""

    __tablename__ = "alerts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    schedule_id = Column(String(64), nullable=True, index=True)
    alert_type = Column(String(32), nullable=False)
    severity = Column(String(16), nullable=False, default="warning")
    agent_name = Column(String(128), nullable=False, index=True)
    agent_version = Column(String(64), nullable=True)
    dimension = Column(String(64), nullable=True)
    message = Column(Text, nullable=False)
    current_value = Column(Float, nullable=True)
    threshold_value = Column(Float, nullable=True)
    notified = Column(Integer, nullable=False, default=0)
    created_at = Column(
        DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    resolved_at = Column(DateTime, nullable=True)


class Alert(BaseModel):
    """告警记录。"""

    schedule_id: str | None = None
    alert_type: str = AlertType.THRESHOLD
    severity: str = AlertSeverity.WARNING
    agent_name: str = ""
    agent_version: str | None = None
    dimension: str | None = None
    message: str = ""
    current_value: float | None = None
    threshold_value: float | None = None
    notified: bool = False
    created_at: str = ""
    resolved_at: str | None = None


class AlertQuery(BaseModel):
    """告警查询参数。"""

    schedule_id: str | None = None
    alert_type: str | None = None
    severity: str | None = None
    agent_name: str | None = None
    resolved: bool | None = None
    limit: int = 50
    offset: int = 0


class AlertStats(BaseModel):
    """告警统计。"""

    total: int = 0
    unresolved: int = 0
    by_type: dict[str, int] = Field(default_factory=dict)
    by_severity: dict[str, int] = Field(default_factory=dict)
