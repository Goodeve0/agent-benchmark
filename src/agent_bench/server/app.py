"""FastAPI 应用创建与生命周期管理。"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from agent_bench.alert import AlertEngine
from agent_bench.badcase import BadCaseStore
from agent_bench.scheduler import EvalScheduler
from agent_bench.server.routes import api_router, ws_router
from agent_bench.server.schedule_routes import router as schedule_router
from agent_bench.server.badcase_routes import router as badcase_router
from agent_bench.server.alert_routes import router as alert_router
from agent_bench.server.state import AppState
from agent_bench.server.trace_routes import trace_router
from agent_bench.trace_store import TraceStore

# 全局 app 引用（供路由中获取实例）
_app_instance: FastAPI | None = None


def get_app() -> FastAPI:
    """获取全局 FastAPI 实例。"""
    if _app_instance is None:
        raise RuntimeError("App 尚未初始化")
    return _app_instance


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动时初始化状态，关闭时清理资源。"""
    global _app_instance
    _app_instance = app

    state: AppState = app.state.app_state  # type: ignore[attr-defined]
    state.load_tasks()

    # 启动调度器
    scheduler: EvalScheduler = app.state.scheduler  # type: ignore[attr-defined]
    scheduler.start()

    yield

    # 停止调度器
    scheduler.stop()

    # 清理：取消所有运行中的评测
    await state.cancel_all()


def create_app(
    spec_dir: str | None = None,
    db_path: str | None = None,
    scheduler_db_path: str | None = None,
    badcase_db_path: str | None = None,
    alert_db_path: str | None = None,
) -> FastAPI:
    """创建 FastAPI 应用实例。

    Args:
        spec_dir: 任务规范目录路径。默认使用内置 specs/。
        db_path: Trace 数据库路径。默认使用环境变量或 data/traces.db。
        scheduler_db_path: 调度器数据库路径。
        badcase_db_path: BadCase 数据库路径。
        alert_db_path: 告警数据库路径。
    """
    app = FastAPI(
        title="AgentBench API",
        description="Agent 行为评测基准框架 — Web API",
        version="0.2.0",
        lifespan=lifespan,
    )

    # CORS：通过环境变量控制允许的来源，生产环境应限制具体域名
    cors_origins = os.getenv("CORS_ORIGINS", "*").split(",")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=cors_origins != ["*"],  # 通配符时禁用凭证
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 初始化应用状态
    if spec_dir is None:
        spec_dir = str(Path(__file__).parent.parent.parent.parent / "specs")
    app.state.app_state = AppState(spec_dir=spec_dir)

    # 初始化 TraceStore
    if db_path is None:
        db_path = os.getenv("AGENT_BENCH_DB_PATH", str(Path("data") / "traces.db"))
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    app.state.trace_store = TraceStore(db_path=db_path)

    # 初始化调度器
    if scheduler_db_path is None:
        scheduler_db_path = os.getenv("AGENT_BENCH_SCHEDULER_DB_PATH", str(Path("data") / "scheduler.db"))
    Path(scheduler_db_path).parent.mkdir(parents=True, exist_ok=True)
    app.state.scheduler = EvalScheduler(db_path=scheduler_db_path)

    # 初始化 BadCaseStore
    if badcase_db_path is None:
        badcase_db_path = os.getenv("AGENT_BENCH_BADCASE_DB_PATH", str(Path("data") / "badcases.db"))
    Path(badcase_db_path).parent.mkdir(parents=True, exist_ok=True)
    app.state.badcase_store = BadCaseStore(db_path=badcase_db_path)

    # 初始化 AlertEngine
    if alert_db_path is None:
        alert_db_path = os.getenv("AGENT_BENCH_ALERT_DB_PATH", str(Path("data") / "alerts.db"))
    Path(alert_db_path).parent.mkdir(parents=True, exist_ok=True)
    app.state.alert_engine = AlertEngine(db_path=alert_db_path)

    # 注册路由
    app.include_router(api_router, prefix="/api/v1")
    app.include_router(trace_router, prefix="/api/v1")
    app.include_router(schedule_router, prefix="/api/v1")
    app.include_router(badcase_router, prefix="/api/v1")
    app.include_router(alert_router, prefix="/api/v1")
    app.include_router(ws_router)

    return app
