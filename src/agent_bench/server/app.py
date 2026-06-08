"""FastAPI 应用创建与生命周期管理。"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from agent_bench.server.routes import api_router, ws_router
from agent_bench.server.state import AppState
from agent_bench.server.trace_routes import trace_router
from agent_bench.trace_store import TraceStore


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动时初始化状态，关闭时清理资源。"""
    state: AppState = app.state.app_state  # type: ignore[attr-defined]
    state.load_tasks()
    yield
    # 清理：取消所有运行中的评测
    await state.cancel_all()


def create_app(spec_dir: str | None = None, db_path: str | None = None) -> FastAPI:
    """创建 FastAPI 应用实例。

    Args:
        spec_dir: 任务规范目录路径。默认使用内置 specs/。
        db_path: Trace 数据库路径。默认使用环境变量或 data/traces.db。
    """
    app = FastAPI(
        title="AgentBench API",
        description="Agent 行为评测基准框架 — Web API",
        version="0.1.0",
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
    # 确保目录存在
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    app.state.trace_store = TraceStore(db_path=db_path)

    # 注册路由
    app.include_router(api_router, prefix="/api/v1")
    app.include_router(trace_router, prefix="/api/v1")
    app.include_router(ws_router)

    return app
