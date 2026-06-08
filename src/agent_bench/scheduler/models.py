"""调度器数据模型 — Pydantic + SQLAlchemy ORM。"""

from __future__ import annotations

import uuid
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


# ---- SQLAlchemy ORM ----


class EvalScheduleORM(Base):
    """评估调度任务 ORM。"""

    __tablename__ = "eval_schedules"

    id = Column(Integer, primary_key=True, autoincrement=True)
    schedule_id = Column(String(64), unique=True, nullable=False, index=True)
    name = Column(String(256), nullable=False)
    agent_name = Column(String(128), nullable=False, index=True)
    agent_version = Column(String(64), nullable=True)
    dimension = Column(String(64), nullable=True)
    task_ids_json = Column(Text, nullable=True)  # JSON list
    cron = Column(String(128), nullable=False)
    enabled = Column(Integer, nullable=False, default=1)
    # 评分配置
    scorer_type = Column(String(32), nullable=False, default="rules")
    judge_model = Column(String(128), nullable=False, default="gpt-4o")
    # BadCase 配置
    badcase_enabled = Column(Integer, nullable=False, default=1)
    badcase_threshold = Column(Float, nullable=False, default=60.0)
    badcase_max_per_run = Column(Integer, nullable=False, default=50)
    # 告警配置
    alert_on_score_drop = Column(Integer, nullable=False, default=1)
    alert_threshold = Column(Float, nullable=False, default=0.0)
    alert_webhook = Column(Text, nullable=True)
    alert_emails_json = Column(Text, nullable=True)  # JSON list
    # 元数据
    created_at = Column(
        DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    updated_at = Column(
        DateTime, nullable=False, default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    last_run_at = Column(DateTime, nullable=True)
    last_run_status = Column(String(32), nullable=True)


class ScheduleRunORM(Base):
    """调度执行历史 ORM。"""

    __tablename__ = "schedule_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String(64), unique=True, nullable=False, index=True)
    schedule_id = Column(String(64), nullable=False, index=True)
    status = Column(String(32), nullable=False, default="pending")
    traces_count = Column(Integer, nullable=False, default=0)
    avg_score = Column(Float, nullable=True)
    badcase_count = Column(Integer, nullable=False, default=0)
    alert_count = Column(Integer, nullable=False, default=0)
    error_message = Column(Text, nullable=True)
    started_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    finished_at = Column(DateTime, nullable=True)


# ---- Pydantic 模型 ----


class EvalSchedule(BaseModel):
    """评估调度任务配置。"""

    schedule_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    name: str = ""
    agent_name: str = ""
    agent_version: str | None = None
    dimension: str | None = None
    task_ids: list[str] | None = None
    cron: str = "0 2 * * *"  # 默认每天凌晨2点
    enabled: bool = True
    # 评分配置
    scorer_type: Literal["rules", "llm_judge", "mixed"] = "rules"
    judge_model: str = "gpt-4o"
    # BadCase 配置
    badcase_enabled: bool = True
    badcase_threshold: float = 60.0
    badcase_max_per_run: int = 50
    # 告警配置
    alert_on_score_drop: bool = True
    alert_threshold: float = 0.0
    alert_webhook: str | None = None
    alert_emails: list[str] | None = None
    # 元数据
    created_at: str = ""
    updated_at: str = ""
    last_run_at: str | None = None
    last_run_status: str | None = None


class ScheduleRunStatus:
    """调度运行状态常量。"""

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"


class ScheduleRun(BaseModel):
    """调度执行历史。"""

    run_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    schedule_id: str = ""
    status: str = "pending"
    traces_count: int = 0
    avg_score: float | None = None
    badcase_count: int = 0
    alert_count: int = 0
    error_message: str | None = None
    started_at: str = ""
    finished_at: str | None = None


class ScheduleCreateRequest(BaseModel):
    """创建调度任务请求。"""

    name: str
    agent_name: str
    agent_version: str | None = None
    dimension: str | None = None
    task_ids: list[str] | None = None
    cron: str = "0 2 * * *"
    scorer_type: Literal["rules", "llm_judge", "mixed"] = "rules"
    judge_model: str = "gpt-4o"
    badcase_enabled: bool = True
    badcase_threshold: float = 60.0
    alert_on_score_drop: bool = True
    alert_threshold: float = 0.0
    alert_webhook: str | None = None
    alert_emails: list[str] | None = None


class ScheduleUpdateRequest(BaseModel):
    """更新调度任务请求。"""

    name: str | None = None
    cron: str | None = None
    enabled: bool | None = None
    scorer_type: Literal["rules", "llm_judge", "mixed"] | None = None
    judge_model: str | None = None
    badcase_enabled: bool | None = None
    badcase_threshold: float | None = None
    alert_on_score_drop: bool | None = None
    alert_threshold: float | None = None
    alert_webhook: str | None = None
    alert_emails: list[str] | None = None
