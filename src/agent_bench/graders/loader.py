"""Grader 动态加载器。

从任务目录中加载自定义 grader.py 文件。
约定：grader.py 中必须定义一个名为 Grader 的类，继承 AbstractGrader。

加载优先级：
1. 如果任务 YAML 同目录下有 grader_{task_id}.py → 加载该文件
2. 如果任务 YAML 同目录下有 grader.py → 加载该文件（该目录下所有任务共享）
3. 否则 → 返回 None（使用内置 Scorer）
"""

from __future__ import annotations

import importlib.util
import logging
from pathlib import Path

from agent_bench.graders.base import AbstractGrader

logger = logging.getLogger(__name__)


def load_grader(task_id: str, task_dir: Path) -> AbstractGrader | None:
    """尝试从任务目录加载自定义 Grader。

    Args:
        task_id: 任务 ID。
        task_dir: 任务 YAML 所在目录。

    Returns:
        AbstractGrader 实例，或 None（无自定义 grader）。
    """
    # 优先级 1: grader_{task_id}.py
    specific_path = task_dir / f"grader_{task_id}.py"
    if specific_path.exists():
        return _load_from_file(specific_path, task_id)

    # 优先级 2: grader.py
    shared_path = task_dir / "grader.py"
    if shared_path.exists():
        return _load_from_file(shared_path, task_id)

    return None


def _load_from_file(path: Path, task_id: str) -> AbstractGrader | None:
    """从 Python 文件动态加载 Grader 类。"""
    try:
        module_name = f"grader_{task_id}_{path.stem}"
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            logger.warning(f"无法加载 grader: {path}")
            return None

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        grader_cls = getattr(module, "Grader", None)
        if grader_cls is None:
            logger.warning(f"grader 文件 {path} 中未找到 Grader 类")
            return None

        if not issubclass(grader_cls, AbstractGrader):
            logger.warning(f"grader 文件 {path} 中的 Grader 类未继承 AbstractGrader")
            return None

        instance = grader_cls()
        logger.info(f"已加载自定义 grader: {path}")
        return instance

    except Exception as e:
        logger.error(f"加载 grader 失败 ({path}): {e}")
        return None
