"""评测任务加载器。

对应 docs/API_SPEC.md 第2.1节。

职责：解析 YAML → Task 对象；校验格式；默认值填充。
不做：执行任务、评分、关心 Agent 实现。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from agent_bench.exceptions import TaskLoadError, TaskNotFoundError
from agent_bench.models import Task


@dataclass
class ValidationResult:
    """任务 YAML 校验结果。

    Attributes:
        valid: 是否合法。
        errors: 错误信息列表，valid=True 时为空。
    """

    valid: bool
    errors: list[str] = field(default_factory=list)


class TaskLoader:
    """从 YAML 规范目录加载评测任务。"""

    def __init__(self, spec_dir: str) -> None:
        """
        Args:
            spec_dir: YAML 规范文件目录路径。
        """
        self.spec_dir = Path(spec_dir)

    def load_all_tasks(self) -> list[Task]:
        """加载 spec_dir 下所有 YAML 任务文件。

        Returns:
            Task 列表（已校验、已填默认值）。

        Raises:
            TaskLoadError: 目录不存在、YAML 格式错误、必填字段缺失或 task_id 重复。
        """
        if not self.spec_dir.exists():
            raise TaskLoadError(f"任务目录不存在: {self.spec_dir}")

        tasks: list[Task] = []
        seen_ids: set[str] = set()
        load_errors: list[str] = []
        for yaml_path in sorted(self.spec_dir.rglob("*.yaml")):
            # 跳过非任务文件（如 dimensions.yaml、rubrics/ 下的文件）
            try:
                raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
            except yaml.YAMLError as e:
                load_errors.append(f"YAML 解析失败 {yaml_path}: {e}")
                continue

            if not isinstance(raw, dict) or "task_id" not in raw:
                continue

            try:
                task = self._load_one(yaml_path)
            except TaskLoadError as e:
                load_errors.append(str(e))
                continue

            if task.task_id in seen_ids:
                raise TaskLoadError(f"task_id 重复: {task.task_id} (来自 {yaml_path})")
            seen_ids.add(task.task_id)
            tasks.append(task)

        if load_errors:
            import logging
            logger = logging.getLogger(__name__)
            for err in load_errors:
                logger.warning("跳过任务文件: %s", err)

        return tasks

    def load_tasks_by_dimension(self, dimension: str) -> list[Task]:
        """按维度筛选任务。

        Args:
            dimension: 维度 ID，如 "tool_use"。
        """
        return [t for t in self.load_all_tasks() if t.dimension == dimension]

    def load_task_by_id(self, task_id: str) -> Task:
        """按 ID 加载单个任务。

        Raises:
            TaskNotFoundError: 指定 task_id 不存在。
        """
        for task in self.load_all_tasks():
            if task.task_id == task_id:
                return task
        raise TaskNotFoundError(f"未找到任务: {task_id}")

    def validate_task(self, task_yaml: dict[str, Any]) -> ValidationResult:
        """校验单个任务字典是否合法（不抛异常）。

        Args:
            task_yaml: 从 YAML 解析得到的字典。

        Returns:
            ValidationResult。
        """
        try:
            Task.model_validate(task_yaml)
            return ValidationResult(valid=True)
        except ValidationError as e:
            errors = [self._format_error(err) for err in e.errors()]
            return ValidationResult(valid=False, errors=errors)

    # ---- 内部方法 ----

    def _load_one(self, yaml_path: Path) -> Task:
        """加载并解析单个 YAML 文件为 Task。"""
        try:
            with open(yaml_path, encoding="utf-8") as f:
                data = yaml.safe_load(f)
        except FileNotFoundError as e:
            raise TaskLoadError(f"任务文件不存在: {yaml_path}") from e
        except yaml.YAMLError as e:
            raise TaskLoadError(f"YAML 解析失败 {yaml_path}: {e}") from e

        if not isinstance(data, dict):
            raise TaskLoadError(f"任务文件格式错误（应为字典）: {yaml_path}")

        try:
            return Task.model_validate(data)
        except ValidationError as e:
            details = "; ".join(self._format_error(err) for err in e.errors())
            raise TaskLoadError(f"任务校验失败 {yaml_path}: {details}") from e

    @staticmethod
    def _format_error(err: dict[str, Any]) -> str:
        """格式化 pydantic 错误信息。"""
        loc = ".".join(str(x) for x in err.get("loc", ()))
        msg = err.get("msg", "未知错误")
        return f"{loc}: {msg}"
