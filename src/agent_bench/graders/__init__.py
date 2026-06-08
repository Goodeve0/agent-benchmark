"""自定义 Grader 模块。

支持两种评分模式并存：
1. YAML 声明式规则（简单任务）→ 使用内置 Scorer
2. 自定义 grader.py（复杂任务）→ 继承 AbstractGrader
"""

from agent_bench.graders.base import AbstractGrader
from agent_bench.graders.loader import load_grader

__all__ = ["AbstractGrader", "load_grader"]
