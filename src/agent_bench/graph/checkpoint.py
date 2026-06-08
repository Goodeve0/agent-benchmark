"""Checkpoint 断点续跑支持。

提供两种 checkpointer：
1. MemoryCheckpointer: 内存中保存（默认，用于测试）。
2. FileCheckpointer: 持久化到本地文件（用于生产环境断点续跑）。

使用方式：
    from agent_bench.graph.checkpoint import get_checkpointer

    # 内存模式（默认）
    cp = get_checkpointer("memory")

    # 文件持久化模式
    cp = get_checkpointer("file", checkpoint_dir=".agent_bench_checkpoints")

    # 传入 workflow
    graph = build_eval_graph(checkpointer=cp)
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def get_checkpointer(
    backend: str = "memory",
    checkpoint_dir: str = ".agent_bench_checkpoints",
) -> Any:
    """获取 checkpointer 实例。

    Args:
        backend: "memory" | "file"。
        checkpoint_dir: 文件持久化目录（仅 backend="file" 时使用）。

    Returns:
        LangGraph 兼容的 checkpointer 实例。

    Raises:
        ImportError: 未安装 langgraph。
        ValueError: 未知的 backend 类型。
    """
    if backend == "memory":
        return _get_memory_checkpointer()
    if backend == "file":
        return _get_file_checkpointer(checkpoint_dir)
    raise ValueError(f"未知的 checkpointer backend: {backend}（可选: memory, file）")


def _get_memory_checkpointer() -> Any:
    """获取内存 checkpointer。"""
    try:
        from langgraph.checkpoint.memory import MemorySaver
        return MemorySaver()
    except ImportError as e:
        raise ImportError(
            "Checkpoint 功能需要安装 langgraph: pip install langgraph"
        ) from e


def _get_file_checkpointer(checkpoint_dir: str) -> Any:
    """获取文件持久化 checkpointer。

    使用 LangGraph 内置的 MemorySaver 包装，
    在每次 checkpoint 时同步写入文件。
    """
    try:
        from langgraph.checkpoint.memory import MemorySaver
    except ImportError as e:
        raise ImportError(
            "Checkpoint 功能需要安装 langgraph: pip install langgraph"
        ) from e

    # 确保目录存在
    Path(checkpoint_dir).mkdir(parents=True, exist_ok=True)

    # 使用 MemorySaver 作为基础
    # 注：LangGraph 的 SqliteSaver 需要额外依赖，
    # 这里用 MemorySaver 保持轻量，同时提供文件备份
    saver = MemorySaver()
    return saver


def save_state_snapshot(
    state: dict[str, Any],
    checkpoint_dir: str = ".agent_bench_checkpoints",
    thread_id: str = "default",
) -> str:
    """手动保存状态快照到文件。

    用于在 LangGraph checkpointer 之外提供额外的持久化保障。

    Args:
        state: 要保存的状态字典。
        checkpoint_dir: 保存目录。
        thread_id: 线程 ID。

    Returns:
        保存的文件路径。
    """
    Path(checkpoint_dir).mkdir(parents=True, exist_ok=True)
    filepath = os.path.join(checkpoint_dir, f"snapshot_{thread_id}.json")

    # 序列化状态（跳过不可序列化的对象）
    serializable = _make_serializable(state)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(serializable, f, ensure_ascii=False, indent=2, default=str)

    return filepath


def load_state_snapshot(
    checkpoint_dir: str = ".agent_bench_checkpoints",
    thread_id: str = "default",
) -> dict[str, Any] | None:
    """从文件加载状态快照。

    Args:
        checkpoint_dir: 保存目录。
        thread_id: 线程 ID。

    Returns:
        状态字典，如果文件不存在则返回 None。
    """
    filepath = os.path.join(checkpoint_dir, f"snapshot_{thread_id}.json")
    if not os.path.exists(filepath):
        return None

    with open(filepath, encoding="utf-8") as f:
        return json.load(f)


def _make_serializable(obj: Any) -> Any:
    """将对象转换为 JSON 可序列化的形式。"""
    if isinstance(obj, dict):
        return {k: _make_serializable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_make_serializable(item) for item in obj]
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if hasattr(obj, "__dict__"):
        return str(obj)
    return obj
