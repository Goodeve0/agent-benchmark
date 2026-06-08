"""Mock 沙箱 + 服务端审计日志。

对应 docs/API_SPEC.md 第2.3节。

v2: 新增 AuditEntry / AuditLog 模型，评分基于沙箱审计日志而非 Agent 自报结果。

职责：拦截工具调用；根据 mock_apis 配置返回预设结果；记录防篡改审计日志。
不做：让 Agent 真实调用外部 API；复杂的状态管理。
"""

from __future__ import annotations

import copy
import hashlib
import json
import time
from typing import Any

from pydantic import BaseModel, Field


class AuditEntry(BaseModel):
    """单条审计记录（不可变）。

    Attributes:
        seq: 序号（从 1 开始递增）。
        tool_name: 调用的工具名。
        params: 调用参数。
        result: 返回结果。
        timestamp: 调用时间戳（Unix epoch）。
        checksum: 该条记录的 SHA-256 校验和（含前一条的 checksum，形成链式校验）。
    """

    seq: int
    tool_name: str
    params: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] = Field(default_factory=dict)
    timestamp: float
    checksum: str = ""


class AuditLog(BaseModel):
    """防篡改审计日志。

    设计要点:
    - 每条 AuditEntry 的 checksum 包含前一条的 checksum（链式哈希）。
    - 一旦 frozen=True，不再接受新记录。
    - 评分引擎只能通过 get_audit_log() 获取冻结后的只读副本。

    Attributes:
        entries: 审计记录列表。
        frozen: 是否已冻结（冻结后不可追加）。
    """

    entries: list[AuditEntry] = Field(default_factory=list)
    frozen: bool = False

    @property
    def tool_names(self) -> list[str]:
        """所有被调用的工具名列表（按调用顺序）。"""
        return [e.tool_name for e in self.entries]

    @property
    def tool_call_count(self) -> int:
        """工具调用总次数。"""
        return len(self.entries)

    def get_calls_for_tool(self, tool_name: str) -> list[AuditEntry]:
        """获取指定工具的所有调用记录。"""
        return [e for e in self.entries if e.tool_name == tool_name]

    def verify_integrity(self) -> bool:
        """验证链式哈希完整性。

        Returns:
            True 表示日志未被篡改。
        """
        prev_checksum = ""
        for entry in self.entries:
            expected = _compute_checksum(
                entry.seq, entry.tool_name, entry.params,
                entry.result, entry.timestamp, prev_checksum,
            )
            if entry.checksum != expected:
                return False
            prev_checksum = entry.checksum
        return True


def _compute_checksum(
    seq: int,
    tool_name: str,
    params: dict,
    result: dict,
    timestamp: float,
    prev_checksum: str,
) -> str:
    """计算单条审计记录的 SHA-256 校验和。"""
    payload = json.dumps(
        {
            "seq": seq,
            "tool_name": tool_name,
            "params": params,
            "result": result,
            "timestamp": timestamp,
            "prev_checksum": prev_checksum,
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class Sandbox:
    """Mock 沙箱。

    Agent 的所有工具调用都必须通过本沙箱，沙箱根据预设的 mock_apis
    返回结果，从而保证评测的确定性与隔离性（不触达真实外部服务）。

    v2: 内置 AuditLog，评分基于审计日志而非 Agent 自报结果。
    """

    UNMOCKED_RESULT: dict[str, Any] = {"result": "unknown", "warning": "unmocked_tool"}

    def __init__(self, mock_apis: dict[str, Any]) -> None:
        """
        Args:
            mock_apis: {tool_name: response} 映射。
        """
        self._mock_apis = mock_apis
        self._audit_log = AuditLog()

    async def execute_tool(self, tool_name: str, params: dict[str, Any]) -> dict[str, Any]:
        """执行工具调用，返回 Mock 结果并记录审计日志。

        Args:
            tool_name: 工具名称。
            params: 调用参数。

        Returns:
            Mock 结果字典（深拷贝，避免外部修改污染配置）。
            若 tool_name 未配置，返回 UNMOCKED_RESULT 的拷贝。

        Raises:
            RuntimeError: 审计日志已冻结时不允许再执行工具调用。
        """
        if self._audit_log.frozen:
            raise RuntimeError("审计日志已冻结，不允许再执行工具调用")

        if tool_name in self._mock_apis:
            result = copy.deepcopy(self._mock_apis[tool_name])
        else:
            result = copy.deepcopy(self.UNMOCKED_RESULT)

        if not isinstance(result, dict):
            result = {"result": result}

        # 记录审计日志（链式哈希）
        params_copy = copy.deepcopy(params)
        result_copy = copy.deepcopy(result)
        ts = time.time()
        seq = len(self._audit_log.entries) + 1
        prev_checksum = (
            self._audit_log.entries[-1].checksum
            if self._audit_log.entries
            else ""
        )
        checksum = _compute_checksum(
            seq, tool_name, params_copy, result_copy, ts, prev_checksum
        )

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

        return result

    def get_audit_log(self, freeze: bool = True) -> AuditLog:
        """获取审计日志的只读副本。

        Args:
            freeze: 是否同时冻结日志（默认 True）。
                    冻结后不再接受新的工具调用。

        Returns:
            AuditLog 的深拷贝。
        """
        if freeze:
            self._audit_log.frozen = True
        return self._audit_log.model_copy(deep=True)

    def get_call_log(self) -> list[dict[str, Any]]:
        """获取所有工具调用记录（向后兼容）。

        Returns:
            记录列表，每项含 tool_name / params / result / timestamp。
        """
        return [
            {
                "tool_name": e.tool_name,
                "params": copy.deepcopy(e.params),
                "result": copy.deepcopy(e.result),
                "timestamp": e.timestamp,
            }
            for e in self._audit_log.entries
        ]

    def reset(self) -> None:
        """重置沙箱状态（清空审计日志，保留 mock_apis 配置）。"""
        self._audit_log = AuditLog()
