"""TraceClient — SDK 核心类。"""

from __future__ import annotations

import functools
import time
from typing import Any, Callable

from agentbench_sdk.context import TraceContext, set_current
from agentbench_sdk.models import TracePayload
from agentbench_sdk.transport import Transport


class TraceClient:
    """AgentBench Trace 上报客户端。

    用法::

        client = TraceClient(
            endpoint="http://localhost:8000/api/v1/traces",
            agent_name="my-agent",
            agent_version="1.0.0",
        )

        # 方式一：上下文管理器
        with client.trace(task_id="task_001") as t:
            t.action(action_type="tool_call", tool_name="search",
                     parameters={"query": "weather"}, result={"temp": 28})
            t.action(action_type="response", content="北京今天28度")
            t.set_summary(total_tokens=1500)

        # 方式二：装饰器
        @client.trace_action(tool_name="database_query")
        def query_db(sql: str):
            return db.execute(sql)
    """

    def __init__(
        self,
        endpoint: str = "http://localhost:8000/api/v1/traces",
        agent_name: str = "unknown",
        agent_version: str = "",
        project_id: str = "default",
        api_key: str | None = None,
        batch_size: int = 50,
        flush_interval: float = 2.0,
        max_retries: int = 3,
        timeout: float = 10.0,
    ) -> None:
        self.agent_name = agent_name
        self.agent_version = agent_version
        self.project_id = project_id

        self._transport = Transport(
            endpoint=endpoint,
            api_key=api_key,
            batch_size=batch_size,
            flush_interval=flush_interval,
            max_retries=max_retries,
            timeout=timeout,
        )

    def trace(
        self,
        task_id: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> TraceContext:
        """创建一次 Trace 上下文。

        Args:
            task_id: 关联的任务 ID。
            metadata: 附加元数据。

        Returns:
            TraceContext 上下文管理器。
        """
        ctx = TraceContext(client=self, task_id=task_id, metadata=metadata)
        return ctx

    def trace_action(
        self,
        tool_name: str | None = None,
        action_type: str = "tool_call",
    ) -> Callable:
        """装饰器：自动记录函数调用为 Trace Action。

        用法::

            @client.trace_action(tool_name="database_query")
            def query_db(sql: str):
                return db.execute(sql)

            result = query_db("SELECT * FROM users")
            # 自动记录: action_type="tool_call", tool_name="database_query",
            #           parameters={"sql": "SELECT * FROM users"}, result=<返回值>
        """

        def decorator(func: Callable) -> Callable:
            @functools.wraps(func)
            def wrapper(*args, **kwargs):
                # 获取当前活跃的 TraceContext
                from agentbench_sdk.context import get_current
                ctx = get_current()

                if ctx is None:
                    # 没有活跃 trace，直接执行
                    return func(*args, **kwargs)

                # 记录工具调用
                params = dict(zip(func.__code__.co_varnames, args))
                params.update(kwargs)

                start = time.time()
                try:
                    result = func(*args, **kwargs)
                    duration = (time.time() - start) * 1000
                    ctx.action(
                        action_type=action_type,
                        tool_name=tool_name or func.__name__,
                        parameters=params,
                        result=result,
                        duration_ms=duration,
                    )
                    return result
                except Exception as e:
                    duration = (time.time() - start) * 1000
                    ctx.action(
                        action_type=action_type,
                        tool_name=tool_name or func.__name__,
                        parameters=params,
                        content=f"执行失败: {e}",
                        duration_ms=duration,
                    )
                    raise

            return wrapper

        return decorator

    def _enqueue_trace(self, payload: TracePayload) -> None:
        """将 TracePayload 加入上报队列（由 TraceContext 调用）。"""
        self._transport.enqueue(payload)

    def flush(self) -> None:
        """手动 flush 缓冲区。"""
        self._transport.flush()

    def shutdown(self) -> None:
        """关闭客户端：flush 剩余数据 + 停止后台线程。"""
        self._transport.shutdown()
