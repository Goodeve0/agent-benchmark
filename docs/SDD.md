# SDD: AgentBench — 系统设计文档

## 1. 系统架构总览

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│  TaskLoader  │────→│  EvalRunner   │────→│   Scorer    │
│ (YAML→Task)  │     │  (编排执行)    │     │  (评分引擎)  │
└─────────────┘     └──────┬───────┘     └─────────────┘
                           │                     │
                    ┌──────┴───────┐      ┌──────┴──────┐
                    │   Sandbox    │      │   Reporter  │
                    │ (Mock 沙箱)   │      │ (报告生成)   │
                    └──────────────┘      └─────────────┘
                           │
                    ┌──────┴───────┐
                    │   Adapter    │  ← 适配不同 Agent
                    │  (Agent 接口) │
                    └──────────────┘
```

## 2. 核心数据流

```
1. 用户在 CLI 指定: Agent 类型 + 评测维度/任务集
2. TaskLoader 读取 YAML → 解析为 Task 对象列表
3. EvalRunner 遍历 Task 列表:
   a. 将 Task 交给 Adapter，调用被测 Agent
   b. Agent 的 tool_call 请求被 Sandbox 拦截
   c. Sandbox 根据 Mock 配置返回预设结果
   d. 收集 AgentTrace（完整执行轨迹：每步动作、token、耗时）
4. Scorer 接收 AgentTrace + Rubric → 逐项评分
5. Reporter 汇总所有评分 → 输出报告（终端表格 + JSON）
```

## 3. 模块职责与边界

### 3.1 TaskLoader

| 项目 | 内容 |
|------|------|
| 输入 | YAML 文件目录路径 |
| 输出 | `list[Task]` |
| 职责 | 解析 YAML → Task 对象；校验 YAML 格式；默认值填充 |
| 不做 | 不执行任务；不关心评分逻辑；不关心 Agent 实现 |

### 3.2 EvalRunner

| 项目 | 内容 |
|------|------|
| 输入 | `list[Task]` + `BaseAdapter` 实例 |
| 输出 | `EvaluationResult`（包含所有 AgentTrace） |
| 职责 | 编排执行流程；超时控制；步数上限；错误重试（可选）；进度展示 |
| 不做 | 不关心具体评分规则；不关心 Agent 内部实现；不做并行调度 |

### 3.3 Sandbox

| 项目 | 内容 |
|------|------|
| 输入 | Agent 的 tool_call 请求（工具名 + 参数） |
| 输出 | `MockResult`（预设的返回值） |
| 职责 | 拦截工具调用；根据 Task 的 mock_apis 配置返回结果；记录调用日志 |
| 不做 | 不让 Agent 真实调用外部 API；不做复杂的状态管理 |

### 3.4 Adapter（接口 + 实现）

| 项目 | 内容 |
|------|------|
| 输入 | `task_prompt: str` + `tools: list[ToolDef]` + Sandbox 实例 |
| 输出 | `AgentTrace` |
| 职责 | 对接具体 Agent 框架；将框架的调用格式转为统一的 AgentTrace |
| 不做 | 不做通用逻辑（通用逻辑在 EvalRunner）；不做评分 |

**内置适配器**：
- `RawAPIAdapter`：直接调用 OpenAI ChatCompletion API + Function Calling
- `LangChainAdapter`：对接 LangChain Agent Executor

### 3.5 Scorer

| 项目 | 内容 |
|------|------|
| 输入 | `AgentTrace` + `list[RubricItem]` |
| 输出 | `ScoreReport` |
| 职责 | 逐项评分（规则引擎）；加权汇总；按维度聚合 |
| 不做 | 不用 LLM 评分；不关心任务执行方式；不修改分数 |

### 3.6 Reporter

| 项目 | 内容 |
|------|------|
| 输入 | `EvaluationResult`（所有 trace + score） |
| 输出 | 终端表格 + JSON 文件 |
| 职责 | 格式化输出；按维度汇总；对比展示 |
| 不做 | 不做 HTML 报告（非 MVP）；不做图表 |

## 4. 核心数据模型

```python
# ===== Task 定义 =====

class ToolDef:
    """工具定义"""
    name: str
    description: str
    parameters: dict  # JSON Schema 格式

class RubricItem:
    """评分项"""
    name: str
    points: float
    criteria: str
    eval_fn: str | None  # 可选：自定义评分函数名

class Task:
    """评测任务"""
    task_id: str
    dimension: str           # 所属维度
    sub_dimension: str       # 所属子维度
    difficulty: str          # easy / medium / hard
    prompt: str              # 给 Agent 的任务描述
    tools: list[ToolDef]     # 可用工具列表
    expected_tool_calls: list[dict]  # 预期工具调用序列（可选）
    rubric: list[RubricItem] # 评分标准
    mock_apis: dict          # Mock API 配置

# ===== 执行轨迹 =====

class AgentAction:
    """Agent 的一个动作"""
    step: int
    action_type: str         # "tool_call" | "response" | "thinking"
    tool_name: str | None
    parameters: dict | None
    result: Any | None       # 工具返回结果
    content: str | None      # 文本内容
    timestamp: float

class AgentTrace:
    """Agent 执行一次任务的完整轨迹"""
    task_id: str
    actions: list[AgentAction]
    total_tokens: int
    total_steps: int
    final_response: str
    execution_time: float
    success: bool            # 是否在步数内完成
    error: str | None        # 错误信息

# ===== 评分 =====

class ScoreDetail:
    """单个评分项的详情"""
    rubric_name: str
    points: float
    max_points: float
    passed: bool
    reason: str

class ScoreReport:
    """单个任务的评分报告"""
    task_id: str
    dimension: str
    sub_dimension: str
    difficulty: str
    scores: list[ScoreDetail]
    total_score: float
    max_score: float

# ===== 汇总 =====

class DimensionScore:
    """维度汇总分数"""
    dimension: str
    score: float
    max_score: float
    percentage: float
    task_count: int

class EvaluationResult:
    """完整评测结果"""
    agent_name: str
    agent_model: str
    timestamp: str
    task_reports: list[ScoreReport]
    dimension_scores: list[DimensionScore]
    overall_score: float
    overall_max_score: float
    overall_percentage: float
```

## 5. 关键技术决策

| 决策点 | 选择 | 理由 |
|--------|------|------|
| 配置格式 | YAML | 支持注释，人类可读，适合手写评测用例 |
| 执行模式 | async | Agent 调用 LLM API 是 IO 密集型 |
| Mock 方式 | 装饰器模式 | Sandbox 拦截工具调用，可替换为真实 API |
| 评分方式 | 规则引擎 | 可复现，不依赖 LLM，确定性评分 |
| CLI 框架 | typer | 类型安全，自动生成帮助文档 |
| 数据校验 | pydantic v2 | 运行时类型校验 + JSON Schema 生成 |
| 进度展示 | rich | 终端友好，进度条 + 表格 |

## 6. 目录结构

```
agent-benchmark/
├── docs/                          # 文档层
│   ├── PRD.md
│   ├── SDD.md
│   ├── API_SPEC.md
│   ├── TDD.md
│   └── CODING_RULES.md
│
├── specs/                         # 评测规范
│   ├── dimensions.yaml            # 维度定义
│   ├── tasks/                     # 评测任务 YAML
│   │   ├── tool_use/
│   │   ├── reasoning/
│   │   ├── memory/
│   │   ├── instruction_following/
│   │   ├── efficiency/
│   │   └── safety/
│   └── rubrics/                   # 通用评分标准模板
│
├── src/agent_bench/               # 源代码
│   ├── __init__.py
│   ├── cli.py                     # CLI 入口
│   ├── models/                    # 数据模型（pydantic）
│   │   ├── __init__.py
│   │   ├── task.py
│   │   ├── trace.py
│   │   └── score.py
│   ├── loader/                    # TaskLoader
│   │   ├── __init__.py
│   │   └── task_loader.py
│   ├── runner/                    # EvalRunner
│   │   ├── __init__.py
│   │   └── eval_runner.py
│   ├── sandbox/                   # Sandbox
│   │   ├── __init__.py
│   │   └── sandbox.py
│   ├── adapters/                  # Agent 适配器
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── raw_api_adapter.py
│   │   └── langchain_adapter.py
│   ├── scorer/                    # 评分引擎
│   │   ├── __init__.py
│   │   ├── scorer.py
│   │   └── rules/                 # 内置评分规则
│   └── reporter/                  # 报告生成
│       ├── __init__.py
│       ├── reporter.py
│       └── formatters/
│
├── tests/                         # 测试
│   ├── test_loader.py
│   ├── test_runner.py
│   ├── test_sandbox.py
│   ├── test_scorer.py
│   ├── test_adapters.py
│   └── fixtures/                  # 测试用 YAML fixture
│
├── results/                       # 评测结果输出
├── pyproject.toml
└── README.md
```

## 7. 外部依赖

```toml
[project]
dependencies = [
    "pyyaml>=6.0",
    "pydantic>=2.0",
    "openai>=1.0",
    "langchain>=0.1",
    "langchain-openai>=0.1",
    "typer>=0.9",
    "rich>=13.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=7.0",
    "pytest-asyncio>=0.21",
    "pytest-cov>=4.0",
    "ruff>=0.1",
    "mypy>=1.0",
]
```

## 8. 错误处理策略

| 场景 | 策略 |
|------|------|
| Agent 超时 | EvalRunner 记录超时，该任务记 0 分，继续下一个 |
| Agent 死循环（超步数） | 强制停止，记录已有 trace，按实际完成度评分 |
| YAML 格式错误 | TaskLoader 校验失败时抛出明确错误，提示修复 |
| Mock API 未命中 | Sandbox 返回默认值 `{"result": "unknown"}`，记录警告 |
| Agent 抛出异常 | EvalRunner 捕获异常，记录 error，该任务记 0 分 |
| 评分规则不匹配 | Scorer 记录 warning，该项记 0 分，不影响其他评分项 |
