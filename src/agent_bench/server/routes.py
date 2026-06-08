"""API 路由定义 — REST + WebSocket。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect

from agent_bench.server.state import AppState


def _get_state_from_request(request: Request) -> AppState:
    """从 FastAPI Request 获取 AppState。"""
    return request.app.state.app_state


def _get_state_from_ws(ws: WebSocket) -> AppState:
    """从 WebSocket 获取 AppState。"""
    return ws.app.state.app_state


# ---- REST API 路由 ----

api_router = APIRouter()


@api_router.get("/tasks")
async def list_tasks(request: Request):
    """获取任务列表摘要。"""
    state = _get_state_from_request(request)
    return {"tasks": state.get_tasks_summary(), "total": len(state.tasks)}


@api_router.get("/tasks/{task_id}")
async def get_task_detail(task_id: str, request: Request):
    """获取单个任务的完整信息。"""
    state = _get_state_from_request(request)
    task = state.get_task_by_id(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"任务 {task_id} 不存在")
    return task.model_dump(exclude_none=True)


@api_router.post("/runs")
async def create_run(config: dict, request: Request):
    """创建并启动一次评测运行。

    请求体示例：
    {
        "adapter_type": "mock",
        "num_trials": 1,
        "max_parallel": 4,
        "judge_mock": true,
        "tasks": []  // 空列表表示运行全部任务
    }
    """
    state = _get_state_from_request(request)
    run_id = await state.start_run(config)
    return {"run_id": run_id, "status": "running"}


@api_router.get("/runs/{run_id}")
async def get_run_status(run_id: str, request: Request):
    """获取评测运行状态。"""
    state = _get_state_from_request(request)
    run = state.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"运行 {run_id} 不存在")
    return run.to_dict()


@api_router.get("/runs/{run_id}/result")
async def get_run_result(run_id: str, request: Request):
    """获取评测运行的完整结果。"""
    state = _get_state_from_request(request)
    result = state.get_result_json(run_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"运行 {run_id} 的结果不存在")
    return result


@api_router.post("/runs/{run_id}/cancel")
async def cancel_run(run_id: str, request: Request):
    """取消评测运行。"""
    state = _get_state_from_request(request)
    success = await state.cancel_run(run_id)
    if not success:
        raise HTTPException(status_code=400, detail=f"无法取消运行 {run_id}")
    return {"run_id": run_id, "status": "cancelled"}


@api_router.get("/leaderboard")
async def get_leaderboard(request: Request):
    """获取排行榜数据。"""
    state = _get_state_from_request(request)
    return {"leaderboard": state.get_leaderboard()}


@api_router.get("/config/options")
async def get_config_options(request: Request):
    """获取评测配置的可用选项。"""
    state = _get_state_from_request(request)
    task_ids = state.get_task_ids()
    return {
        "adapter_types": ["mock", "raw_api"],
        "tasks": task_ids,
        "num_trials_range": {"min": 1, "max": 10, "default": 1},
        "max_parallel_range": {"min": 1, "max": 16, "default": 4},
    }


# ---- WebSocket 路由 ----

ws_router = APIRouter()


@ws_router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket 端点 — 实时推送评测进度。

    客户端连接后，每次评测进度变化都会收到 JSON 消息：
    {
        "type": "progress",
        "data": {
            "run_id": "...",
            "status": "running",
            "progress": 50.0,
            "current_task": "tool_use_001",
            "completed_tasks": 5,
            "total_tasks": 10
        }
    }
    """
    state = _get_state_from_ws(websocket)
    await state.connect_ws(websocket)
    try:
        while True:
            # 保持连接，接收客户端心跳
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        state.disconnect_ws(websocket)
