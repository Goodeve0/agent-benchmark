# CODING_RULES: AgentBench — 编码规范

> AI 编码时必须严格遵守此规范。每条规则都是对"跑偏"的防护栏。

---

## 1. 通用原则

### 1.1 文档驱动
- **先读文档再写代码**：每次开始实现一个模块前，先阅读对应的 API Spec 和 TDD
- **实现不得超出 API Spec**：签名、参数、返回类型严格一致。如有变更需求，先改文档再改代码
- **测试先行**：先写 TDD 中定义的测试用例，再写实现代码

### 1.2 最小实现
- **只做当前任务要求的功能**，不做"顺便也做了"的额外功能
- **YAGNI 原则**：You Aren't Gonna Need It，不为未来可能的需求预留代码
- **边界在 PRD 中已定义**，任何超出 PRD 第3节（核心功能）的代码都不写

### 1.3 一致性
- 命名风格、文件组织、错误处理方式全项目统一
- 遇到不确定的地方，参考已有代码的做法，不自行发明新风格

---

## 2. Python 编码规范

### 2.1 风格
- 遵循 PEP 8
- 使用 `ruff` 作为 linter 和 formatter
- 行宽限制 120 字符
- 缩进 4 空格

### 2.2 类型注解
- **所有公开函数必须有完整的类型注解**
- 私有函数也尽量加类型注解
- 使用 Python 3.10+ 语法：`str | None` 而非 `Optional[str]`，`list[X]` 而非 `List[X]`

```python
# ✅ 正确
async def run_task(self, task_prompt: str, tools: list[ToolDef]) -> AgentTrace:
    ...

# ❌ 错误
async def run_task(self, task_prompt, tools):
    ...
```

### 2.3 命名规范

| 类型 | 风格 | 示例 |
|------|------|------|
| 文件名 | snake_case | `task_loader.py` |
| 类名 | PascalCase | `TaskLoader`, `AgentTrace` |
| 函数/方法 | snake_case | `load_all_tasks()` |
| 常量 | UPPER_SNAKE | `MAX_STEPS`, `DEFAULT_TIMEOUT` |
| 私有方法 | _前缀 | `_validate_yaml()` |
| Pydantic 模型 | PascalCase | `Task`, `ScoreReport` |

### 2.4 Docstring
- 所有公开类和函数必须有 docstring
- 使用 Google 风格

```python
async def run_task(
    self,
    task_prompt: str,
    tools: list[ToolDef],
    sandbox: Sandbox,
    max_steps: int = 10,
    timeout: int = 60,
) -> AgentTrace:
    """运行一个评测任务，返回执行轨迹。

    Args:
        task_prompt: 任务描述，直接传给 Agent。
        tools: 可用工具定义列表。
        sandbox: 沙箱实例，Agent 调用工具时必须通过 sandbox。
        max_steps: 最大步数限制，默认 10。
        timeout: 超时秒数，默认 60。

    Returns:
        AgentTrace: 完整执行轨迹。

    Raises:
        AgentTimeoutError: 执行超过 timeout 秒。
        AgentStepLimitError: 执行超过 max_steps 步。
    """
    ...
```

---

## 3. 项目结构规范

### 3.1 模块组织
- 每个模块一个目录，包含 `__init__.py`
- `__init__.py` 只做显式导出，不放逻辑代码

```python
# src/agent_bench/loader/__init__.py
from .task_loader import TaskLoader

__all__ = ["TaskLoader"]
```

### 3.2 导入顺序
```python
# 1. 标准库
import asyncio
from pathlib import Path

# 2. 第三方库
import yaml
from pydantic import BaseModel

# 3. 本项目
from agent_bench.models.task import Task, ToolDef
```

### 3.3 禁止循环导入
- models 之间不得互相导入
- models 被其他所有模块导入，但不导入任何其他模块
- 如需跨模块引用类型，使用 `TYPE_CHECKING`

```python
from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent_bench.sandbox import Sandbox
```

---

## 4. 错误处理规范

### 4.1 自定义异常
- 只使用 `docs/API_SPEC.md` 第5节定义的异常类型
- 不新增异常类，除非先更新 API Spec

### 4.2 异常传播
- 底层模块抛出具体异常，上层模块捕获后转为项目异常

```python
# ✅ 正确
try:
    with open(path) as f:
        data = yaml.safe_load(f)
except FileNotFoundError as e:
    raise TaskLoadError(f"Task file not found: {path}") from e
except yaml.YAMLError as e:
    raise TaskLoadError(f"Invalid YAML in {path}: {e}") from e
```

### 4.3 不要吞掉异常
```python
# ❌ 错误
try:
    await adapter.run_task(...)
except Exception:
    pass  # 绝对不行

# ✅ 正确
try:
    await adapter.run_task(...)
except AgentTimeoutError:
    trace.success = False
    trace.error = "Agent execution timed out"
```

---

## 5. 异步编程规范

### 5.1 所有 IO 操作用 async
- LLM API 调用、文件 IO（大文件）使用 async
- `run_task`, `execute_tool` 等必须是 `async def`

### 5.2 不要混用 sync 和 async
```python
# ❌ 错误：在 async 函数中使用 sync IO
async def run_task(self, ...):
    data = yaml.safe_load(open("config.yaml"))  # 阻塞！

# ✅ 正确：在 __init__ 等 sync 入口预加载，async 函数中使用已加载的数据
class TaskLoader:
    def load_all_tasks(self) -> list[Task]:  # sync，启动时调用
        ...
    
    async def do_something(self):  # async，运行时调用
        tasks = self._tasks  # 使用预加载的数据
```

---

## 6. 测试规范

### 6.1 测试文件命名
- `test_{module_name}.py`，与源码模块一一对应

### 6.2 测试函数命名
- `test_{功能描述}`，用下划线分隔
- 描述要具体，不用 `test_run` 这种模糊命名

```python
# ✅ 正确
def test_load_yaml_with_missing_required_field():
    ...

# ❌ 错误
def test_loader_error():
    ...
```

### 6.3 测试隔离
- 每个测试独立，不依赖其他测试的执行顺序
- 使用 `tmp_path` fixture 代替真实文件系统
- 使用 fixture 创建测试数据，不在测试中硬编码路径

### 6.4 Mock 原则
- Adapter 测试 mock httpx（不调真实 API）
- 外部服务一律 mock
- 内部模块间不 mock（如 Scorer 不 mock TaskLoader）

---

## 7. 配置规范

### 7.1 YAML 任务文件格式
```yaml
# 必填字段
task_id: string          # 格式: {dimension}_{3位编号}
dimension: string        # 维度ID
sub_dimension: string    # 子维度ID
difficulty: easy|medium|hard
prompt: string           # 任务描述
tools:                   # 至少1个
  - name: string
    description: string
    parameters: object   # JSON Schema
rubric:                  # 至少1个
  - name: string
    points: number (>0)
    criteria: string

# 可选字段
expected_tool_calls: []
mock_apis: {}
```

### 7.2 配置与代码分离
- 所有评测任务定义在 `specs/tasks/` 下的 YAML 中
- 代码中不硬编码任务内容
- 评分规则函数名在 YAML 的 `eval_fn` 字段指定，代码中实现对应函数

---

## 8. Git 规范

### 8.1 Commit Message
```
<type>(<scope>): <description>

类型:
  feat:     新功能
  fix:      修复 bug
  test:     添加/修改测试
  docs:     文档变更
  refactor: 重构（不改功能）
  chore:    构建/工具变更
```

### 8.2 分支
- `main`: 稳定代码
- `feat/{module-name}`: 功能开发分支
- 开发完成提 PR，合并到 main

---

## 9. AI 编码时的特殊约束

### 9.1 一次只做一个模块
- 严格按照 SDD 的模块顺序实现：TaskLoader → Sandbox → Scorer → Adapter → EvalRunner → Reporter
- 每完成一个模块，跑完该模块的测试再进入下一个

### 9.2 不要优化未实现的代码
- 先让测试通过，再做优化
- 不要在实现阶段提前做性能优化

### 9.3 不要引入新依赖
- 只使用 SDD 第7节列出的依赖
- 如需新依赖，先更新 SDD，确认后再引入

### 9.4 遇到不确定的地方
- 以 API Spec 为准
- API Spec 未覆盖的，以 PRD 为准
- PRD 未覆盖的，以最小实现原则处理
- 不要猜测需求，不要自行扩展

### 9.5 代码长度限制
- 单个函数不超过 50 行
- 单个文件不超过 300 行
- 超出时必须拆分
