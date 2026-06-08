"""SDK 内部数据模型 — 与 Server 端 TracePayload / ActionRecord 兼容。"""

from __future__ import annotations

import time
import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field


class ActionRecord(BaseModel):
    """单条 Action 记录。"""

    action_type: Literal["tool_call", "response", "thinking"]
    tool_name: str | None = None
    parameters: dict[str, Any] | None = None
    result: Any | None = None
    content: str | None = None
    timestamp: float = Field(default_factory=time.time)
    duration_ms: float | None = None


class TracePayload(BaseModel):
    """一次 Trace 的完整上报数据。"""

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
    # 链式哈希（由服务端计算，SDK 不填）
    prev_hash: str | None = None
    payload_hash: str = ""
