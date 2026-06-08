"""HTTP 传输层 — 异步批量上报。"""

from __future__ import annotations

import atexit
import logging
import threading
import time
from typing import Any

import httpx

from agentbench_sdk.models import TracePayload

logger = logging.getLogger(__name__)

# 默认配置
DEFAULT_BATCH_SIZE = 50
DEFAULT_FLUSH_INTERVAL = 2.0  # 秒
DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_DELAY = 1.0  # 秒


class Transport:
    """异步批量上报传输层。

    - 后台线程定时 flush
    - 批量合并减少 HTTP 请求
    - 失败重试（指数退避）
    - atexit 保证退出前 flush
    """

    def __init__(
        self,
        endpoint: str,
        api_key: str | None = None,
        batch_size: int = DEFAULT_BATCH_SIZE,
        flush_interval: float = DEFAULT_FLUSH_INTERVAL,
        max_retries: int = DEFAULT_MAX_RETRIES,
        timeout: float = 10.0,
    ) -> None:
        self._endpoint = endpoint.rstrip("/")
        self._api_key = api_key
        self._batch_size = batch_size
        self._flush_interval = flush_interval
        self._max_retries = max_retries
        self._timeout = timeout

        # 缓冲队列
        self._buffer: list[TracePayload] = []
        self._lock = threading.Lock()

        # 后台 flush 线程
        self._stop_event = threading.Event()
        self._flush_thread = threading.Thread(
            target=self._flush_loop, daemon=True, name="agentbench-sdk-flush"
        )
        self._flush_thread.start()

        # 退出时 flush
        atexit.register(self.flush)

    def _flush_loop(self) -> None:
        """后台线程：定时 flush 缓冲区。"""
        while not self._stop_event.is_set():
            self._stop_event.wait(self._flush_interval)
            self._try_flush()

    def _try_flush(self) -> None:
        """尝试 flush 缓冲区（线程安全）。"""
        with self._lock:
            if not self._buffer:
                return
            batch = self._buffer[:self._batch_size]
            self._buffer = self._buffer[self._batch_size:]

        if batch:
            self._send_batch(batch)

    def _send_batch(self, batch: list[TracePayload]) -> None:
        """发送一批 Trace（带重试）。"""
        for i in range(self._max_retries):
            try:
                self._do_post(batch)
                return
            except Exception as e:
                delay = DEFAULT_RETRY_DELAY * (2 ** i)
                logger.warning(
                    "Trace 上报失败 (重试 %d/%d): %s, %0.1fs 后重试",
                    i + 1, self._max_retries, e, delay,
                )
                time.sleep(delay)

        logger.error("Trace 上报最终失败，丢弃 %d 条 Trace", len(batch))

    def _do_post(self, batch: list[TracePayload]) -> None:
        """执行 HTTP POST。"""
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        # 逐条发送（服务端 API 是单条上报）
        with httpx.Client(timeout=self._timeout) as client:
            for payload in batch:
                resp = client.post(
                    self._endpoint,
                    json=payload.model_dump(),
                    headers=headers,
                )
                resp.raise_for_status()

    def enqueue(self, payload: TracePayload) -> None:
        """将 Trace 加入缓冲队列。"""
        with self._lock:
            self._buffer.append(payload)

        # 缓冲区满时立即 flush
        if len(self._buffer) >= self._batch_size:
            self._try_flush()

    def flush(self) -> None:
        """手动 flush 所有缓冲数据。"""
        with self._lock:
            remaining = list(self._buffer)
            self._buffer = []

        if remaining:
            self._send_batch(remaining)

    def shutdown(self) -> None:
        """关闭传输层：停止后台线程 + flush 剩余数据。"""
        self._stop_event.set()
        self.flush()
        if self._flush_thread.is_alive():
            self._flush_thread.join(timeout=5.0)
