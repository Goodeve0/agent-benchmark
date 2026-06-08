"""真实工具沙箱 — 工具调用触达真实外部 API。

与 MockSandbox（Sandbox）互补：
- MockSandbox：拦截所有工具调用，返回预设数据，保证确定性和隔离性。
- RealSandbox：将工具调用路由到真实实现函数，验证 Agent 在真实环境下的表现。

安全策略：
1. 白名单机制：只允许注册过的工具执行真实调用，未注册工具返回 Mock 降级结果。
2. 预算控制：单次评测 API 调用次数上限，防止 Agent 死循环导致超额消耗。
3. 超时保护：单次工具调用超时后返回错误信息，而非无限等待。
4. 降级策略：真实调用失败时可选择 fallback 到 Mock 数据。
"""

from __future__ import annotations

import asyncio
import copy
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from agent_bench.exceptions import BudgetExceededError, ToolNotFoundError
from agent_bench.sandbox.sandbox import AuditEntry, AuditLog, _compute_checksum

logger = logging.getLogger(__name__)

# 工具实现函数类型：接收关键字参数，返回结果字典
ToolImpl = Callable[..., Awaitable[dict[str, Any]]]


class RealSandbox:
    """真实工具沙箱。

    Agent 的工具调用被路由到真实实现函数，触达真实外部 API。
    同时保留审计日志和预算控制，确保评测的可观测性和安全性。

    使用示例::

        from agent_bench.sandbox.real_sandbox import RealSandbox
        from agent_bench.tools import get_weather_impl, search_web_impl

        sandbox = RealSandbox(
            tool_implementations={
                "get_weather": get_weather_impl,
                "search_web": search_web_impl,
            },
            mock_apis={"get_weather": {"temp": 25, "city": "fallback"}},
            budget=100,
            fallback_on_error=True,
        )
    """

    def __init__(
        self,
        tool_implementations: dict[str, ToolImpl],
        mock_apis: dict[str, Any] | None = None,
        budget: int = 100,
        tool_timeout: float = 30.0,
        fallback_on_error: bool = True,
    ) -> None:
        """
        Args:
            tool_implementations: 工具名 → 真实异步实现函数的映射。
            mock_apis: 降级用的 Mock 数据 {tool_name: response}。
            budget: 单次评测最大工具调用次数。
            tool_timeout: 单次工具调用超时秒数。
            fallback_on_error: 真实调用失败时是否降级到 Mock 数据。
        """
        self._tool_impls = tool_implementations
        self._mock_apis = mock_apis or {}
        self._budget = budget
        self._tool_timeout = tool_timeout
        self._fallback_on_error = fallback_on_error
        self._call_count = 0
        self._audit_log = AuditLog()

    async def execute_tool(self, tool_name: str, params: dict[str, Any]) -> dict[str, Any]:
        """执行工具调用，优先路由到真实实现，失败时降级到 Mock。

        Args:
            tool_name: 工具名称。
            params: 调用参数。

        Returns:
            工具执行结果字典。结果中 ``_source`` 字段标识来源：
            - "real_api": 真实 API 调用成功
            - "mock_fallback": 降级到 Mock 数据
            - "error": 调用失败且无降级数据

        Raises:
            RuntimeError: 审计日志已冻结。
            BudgetExceededError: 超过调用预算。
            ToolNotFoundError: 工具未注册且无 Mock 降级。
        """
        if self._audit_log.frozen:
            raise RuntimeError("审计日志已冻结，不允许再执行工具调用")

        if self._call_count >= self._budget:
            raise BudgetExceededError(f"已超过调用预算 {self._budget} 次")

        self._call_count += 1
        result: dict[str, Any]

        if tool_name in self._tool_impls:
            result = await self._execute_real(tool_name, params)
        elif tool_name in self._mock_apis:
            mock_result = self._mock_apis[tool_name]
            result = copy.deepcopy(mock_result) if isinstance(mock_result, dict) else {"result": mock_result}
            result["_source"] = "mock_fallback"
            logger.debug(f"工具 {tool_name} 无真实实现，使用 Mock 降级")
        else:
            raise ToolNotFoundError(f"工具 {tool_name} 未注册真实实现，也无 Mock 降级数据")

        # 记录审计日志
        self._record_audit(tool_name, params, result)
        return result

    async def _execute_real(self, tool_name: str, params: dict[str, Any]) -> dict[str, Any]:
        """执行真实工具调用，带超时和错误处理。"""
        impl = self._tool_impls[tool_name]
        try:
            result = await asyncio.wait_for(
                impl(**params),
                timeout=self._tool_timeout,
            )
            if not isinstance(result, dict):
                result = {"result": result}
            result["_source"] = "real_api"
            logger.debug(f"工具 {tool_name} 真实调用成功")
            return result
        except asyncio.TimeoutError:
            error_msg = f"工具 {tool_name} 调用超时（{self._tool_timeout}s）"
            logger.warning(error_msg)
            return self._handle_error(tool_name, error_msg)
        except Exception as e:
            error_msg = f"工具 {tool_name} 调用失败: {e}"
            logger.warning(error_msg)
            return self._handle_error(tool_name, error_msg)

    def _handle_error(self, tool_name: str, error_msg: str) -> dict[str, Any]:
        """处理真实调用失败的情况。"""
        if self._fallback_on_error and tool_name in self._mock_apis:
            mock_result = self._mock_apis[tool_name]
            result = copy.deepcopy(mock_result) if isinstance(mock_result, dict) else {"result": mock_result}
            result["_source"] = "mock_fallback"
            result["_error"] = error_msg
            logger.info(f"工具 {tool_name} 真实调用失败，降级到 Mock 数据")
            return result

        return {
            "_source": "error",
            "_error": error_msg,
            "success": False,
        }

    def _record_audit(self, tool_name: str, params: dict[str, Any], result: dict[str, Any]) -> None:
        """记录审计日志（复用 Sandbox 的链式哈希机制）。"""
        params_copy = copy.deepcopy(params)
        result_copy = copy.deepcopy(result)
        ts = time.time()
        seq = len(self._audit_log.entries) + 1
        prev_checksum = (
            self._audit_log.entries[-1].checksum
            if self._audit_log.entries
            else ""
        )
        checksum = _compute_checksum(seq, tool_name, params_copy, result_copy, ts, prev_checksum)

        self._audit_log.entries.append(
            AuditEntry(
                seq=seq,
                tool_name=tool_name,
                params=params_copy,
                result=result_copy,
                timestamp=ts,
                checksum=checksum,
            )
        )

    def get_audit_log(self, freeze: bool = True) -> AuditLog:
        """获取审计日志的只读副本。"""
        if freeze:
            self._audit_log.frozen = True
        return self._audit_log.model_copy(deep=True)

    def get_call_log(self) -> list[dict[str, Any]]:
        """获取所有工具调用记录。"""
        return [
            {
                "tool_name": e.tool_name,
                "params": copy.deepcopy(e.params),
                "result": copy.deepcopy(e.result),
                "timestamp": e.timestamp,
            }
            for e in self._audit_log.entries
        ]

    @property
    def call_count(self) -> int:
        """已执行的工具调用次数。"""
        return self._call_count

    @property
    def remaining_budget(self) -> int:
        """剩余调用预算。"""
        return self._budget - self._call_count
