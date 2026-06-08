"""Trace 上下文管理器 — with client.trace() 的实现。"""

from __future__ import annotations

import time
from typing import Any

from agentbench_sdk.models import ActionRecord, TracePayload


class TraceContext:
    """一次 Trace 的上下文管理器。

    用法::

        with client.trace(task_id="task_001") as t:
            t.action(action_type="tool_call", tool_name="search", ...)
            t.action(action_type="response", content="结果")
            t.set_summary(total_tokens=1500)
    """

    def __init__(
        self,
        client: Any,  # TraceClient，避免循环引用用 Any
        task_id: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self._client = client
        self._payload = TracePayload(
            task_id=task_id,
            agent_name=client.agent_name,
            agent_version=client.agent_version,
            project_id=client.project_id,
            metadata=metadata,
        )
        self._start_time = time.time()
        self._closed = False

    def action(
        self,
        action_type: str,
        tool_name: str | None = None,
        parameters: dict[str, Any] | None = None,
        result: Any = None,
        content: str | None = None,
        duration_ms: float | None = None,
    ) -> None:
        """记录一条 Action。"""
        if self._closed:
            raise RuntimeError("Trace 已关闭，不能继续记录 action")

        record = ActionRecord(
            action_type=action_type,  # type: ignore[arg-type]
            tool_name=tool_name,
            parameters=parameters,
            result=result,
            content=content,
            duration_ms=duration_ms,
        )
        self._payload.actions.append(record)

    def set_summary(
        self,
        total_tokens: int | None = None,
        final_response: str | None = None,
        success: bool | None = None,
        error: str | None = None,
    ) -> None:
        """设置汇总信息。"""
        if total_tokens is not None:
            self._payload.total_tokens = total_tokens
        if final_response is not None:
            self._payload.final_response = final_response
        if success is not None:
            self._payload.success = success
        if error is not None:
            self._payload.error = error
            self._payload.success = False

    def __enter__(self) -> TraceContext:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self._closed = True
        self._payload.execution_time = round(time.time() - self._start_time, 4)
        self._payload.total_steps = len(self._payload.actions)

        if exc_type is not None:
            self._payload.success = False
            self._payload.error = f"{exc_type.__name__}: {exc_val}"

        # 如果没有设置 final_response，取最后一条 response action
        if not self._payload.final_response:
            for a in reversed(self._payload.actions):
                if a.action_type == "response" and a.content:
                    self._payload.final_response = a.content
                    break

        # 上报
        self._client._enqueue_trace(self._payload)


# 全局上下文（用于 trace_context 模块级 API）
_current_context: TraceContext | None = None


def get_current() -> TraceContext | None:
    """获取当前活跃的 TraceContext。"""
    return _current_context


def set_current(ctx: TraceContext | None) -> None:
    """设置当前活跃的 TraceContext。"""
    global _current_context
    _current_context = ctx
