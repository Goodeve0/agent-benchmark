# API Spec: AgentBench — 接口规范

> 本文档定义了模块间的接口契约。所有实现必须严格遵守签名、参数类型和返回类型。

## 1. 数据模型接口

### 1.1 ToolDef

```python
class ToolDef(BaseModel):
    """工具定义"""
    name: str                              # 工具名称，全局唯一
    description: str                       # 工具描述（Agent 可见）
    parameters: dict                       # JSON Schema 格式的参数定义
```

### 1.2 RubricItem

```python
class RubricItem(BaseModel):
    """评分项"""
    name: str                              # 评分项名称
    points: float                          # 分值（>0）
    criteria: str                          # 评分标准描述
    eval_fn: str | None = None             # 可选：自定义评分函数名
```

### 1.3 Task

```python
class Task(BaseModel):
    """评测任务"""
    task_id: str                           # 任务唯一ID，格式: {dimension}_{编号}
    dimension: str                         # 所属维度
    sub_dimension: str                     # 所属子维度
    difficulty: Literal["easy", "medium", "hard"]
    prompt: str                            # 给 Agent 的任务描述
    tools: list[ToolDef]                   # 可用工具列表
    expected_tool_calls: list[dict]        # 预期工具调用序列（可选，用于评分）
    rubric: list[RubricItem]               # 评分标准列表
    mock_apis: dict                        # Mock API 配置 {tool_name: response}
```

### 1.4 AgentAction

```python
class AgentAction(BaseModel):
    """Agent 的一个动作"""
    step: int                              # 步骤序号（从1开始）
    action_type: Literal["tool_call", "response", "thinking"]
    tool_name: str | None = None           # action_type=tool_call 时必填
    parameters: dict | None = None         # 工具调用参数
    result: Any | None = None              # 工具返回结果
    content: str | None = None             # 文本内容
    timestamp: float                       # Unix 时间戳
```

### 1.5 AgentTrace

```python
class AgentTrace(BaseModel):
    """Agent 执行一次任务的完整轨迹"""
    task_id: str
    actions: list[AgentAction]             # 按时间排序的动作列表
    total_tokens: int                      # 总 token 消耗
    total_steps: int                       # 总步骤数
    final_response: str                    # Agent 的最终文本回复
    execution_time: float                  # 执行耗时（秒）
    success: bool                          # 是否在限制内完成
    error: str | None = None               # 错误信息
```

### 1.6 ScoreDetail

```python
class ScoreDetail(BaseModel):
    """单个评分项的详情"""
    rubric_name: str                       # 对应的 RubricItem.name
    points: float                          # 实际得分
    max_points: float                      # 满分
    passed: bool                           # 是否达标
    reason: str                            # 评分理由
```

### 1.7 ScoreReport

```python
class ScoreReport(BaseModel):
    """单个任务的评分报告"""
    task_id: str
    dimension: str
    sub_dimension: str
    difficulty: str
    scores: list[ScoreDetail]              # 各评分项详情
    total_score: float                     # 总得分
    max_score: float                       # 总满分
```

### 1.8 DimensionScore

```python
class DimensionScore(BaseModel):
    """维度汇总分数"""
    dimension: str
    score: float
    max_score: float
    percentage: float                      # 得分率 0-100
    task_count: int                        # 该维度下任务数
```

### 1.9 EvaluationResult

```python
class EvaluationResult(BaseModel):
    """完整评测结果"""
    agent_name: str
    agent_model: str
    timestamp: str                         # ISO 8601 格式
    task_reports: list[ScoreReport]
    dimension_scores: list[DimensionScore]
    overall_score: float
    overall_max_score: float
    overall_percentage: float
```

---

## 2. 模块接口

### 2.1 TaskLoader

```python
class TaskLoader:
    """评测任务加载器"""

    def __init__(self, spec_dir: str) -> None:
        """
        Args:
            spec_dir: YAML 规范文件目录路径
        """
        ...

    def load_all_tasks(self) -> list[Task]:
        """加载 spec_dir 下所有 YAML 任务文件，返回 Task 列表
        
        Raises:
            TaskLoadError: YAML 格式错误或必填字段缺失
        """
        ...

    def load_tasks_by_dimension(self, dimension: str) -> list[Task]:
        """按维度加载任务
        
        Args:
            dimension: 维度ID，如 "tool_use"
        """
        ...

    def load_task_by_id(self, task_id: str) -> Task:
        """按 ID 加载单个任务
        
        Raises:
            TaskNotFoundError: 任务ID不存在
        """
        ...

    def validate_task(self, task_yaml: dict) -> ValidationResult:
        """校验单个任务 YAML 是否合法"""
        ...
```

### 2.2 BaseAdapter（抽象基类）

```python
class BaseAdapter(ABC):
    """Agent 适配器基类，所有适配器必须继承此类"""

    @abstractmethod
    async def run_task(
        self,
        task_prompt: str,
        tools: list[ToolDef],
        sandbox: "Sandbox",
        max_steps: int = 10,
        timeout: int = 60,
    ) -> AgentTrace:
        """
        运行一个评测任务，返回执行轨迹。
        
        Args:
            task_prompt: 任务描述（直接传给 Agent）
            tools: 可用工具定义列表
            sandbox: 沙箱实例（Agent 调用工具时必须通过 sandbox）
            max_steps: 最大步数限制
            timeout: 超时秒数
            
        Returns:
            AgentTrace: 完整执行轨迹
            
        Raises:
            AgentTimeoutError: 超过 timeout 秒
            AgentStepLimitError: 超过 max_steps 步
        """
        ...

    @abstractmethod
    def get_agent_info(self) -> dict:
        """返回 Agent 元信息
        
        Returns:
            {"name": str, "model": str, "framework": str}
        """
        ...
```

### 2.3 Sandbox

```python
class Sandbox:
    """Mock 沙箱，拦截 Agent 的工具调用"""

    def __init__(self, mock_apis: dict[str, Any]) -> None:
        """
        Args:
            mock_apis: {tool_name: response} 映射
        """
        ...

    async def execute_tool(self, tool_name: str, params: dict) -> dict:
        """
        执行工具调用（返回 Mock 结果）。
        
        Args:
            tool_name: 工具名称
            params: 调用参数
            
        Returns:
            Mock 结果字典
            
        Note:
            - 如果 tool_name 在 mock_apis 中，返回预设结果
            - 如果未配置，返回 {"result": "unknown", "warning": "unmocked_tool"}
            - 每次调用都会记录到 call_log 中
        """
        ...

    def get_call_log(self) -> list[dict]:
        """获取所有工具调用记录
        
        Returns:
            [{"tool_name": str, "params": dict, "result": dict, "timestamp": float}]
        """
        ...

    def reset(self) -> None:
        """重置沙箱状态（清空调用记录）"""
        ...
```

### 2.4 EvalRunner

```python
class EvalRunner:
    """评测执行器"""

    def __init__(
        self,
        adapter: BaseAdapter,
        max_steps: int = 10,
        timeout: int = 60,
        retry_on_error: bool = False,
    ) -> None:
        """
        Args:
            adapter: Agent 适配器实例
            max_steps: 单任务最大步数
            timeout: 单任务超时秒数
            retry_on_error: 出错时是否重试一次
        """
        ...

    async def run_single_task(self, task: Task) -> AgentTrace:
        """运行单个评测任务
        
        流程:
        1. 创建 Sandbox（注入 task.mock_apis）
        2. 调用 adapter.run_task()
        3. 捕获超时/步数超限异常，记录到 trace.error
        4. 返回 AgentTrace
        """
        ...

    async def run_evaluation(
        self,
        tasks: list[Task],
    ) -> list[AgentTrace]:
        """运行一批评测任务（串行执行）
        
        流程:
        1. 逐个调用 run_single_task
        2. 显示进度条
        3. 返回所有 AgentTrace
        """
        ...
```

### 2.5 Scorer

```python
class Scorer:
    """评分引擎"""

    def score_task(self, trace: AgentTrace, task: Task) -> ScoreReport:
        """
        对单个任务的执行轨迹评分。
        
        评分流程:
        1. 遍历 task.rubric 中每个 RubricItem
        2. 如果有 eval_fn，调用对应的内置评分函数
        3. 如果没有 eval_fn，记 0 分并标记需人工复核
        4. 汇总各项得分
        
        Args:
            trace: Agent 执行轨迹
            task: 原始任务（提供 rubric 及 dimension/sub_dimension 等元信息）
            
        Returns:
            ScoreReport
        """
        ...

    def score_evaluation(
        self,
        traces: list[AgentTrace],
        tasks: list[Task],
    ) -> list[ScoreReport]:
        """批量评分
        
        Args:
            traces: 与 tasks 一一对应的执行轨迹
            tasks: 原始任务列表（包含 rubric）
        """
        ...

    def aggregate_by_dimension(
        self,
        reports: list[ScoreReport],
    ) -> list[DimensionScore]:
        """按维度汇总分数"""
        ...
```

### 2.6 Reporter

```python
class Reporter:
    """报告生成器"""

    def print_table(self, result: EvaluationResult) -> None:
        """在终端输出评测结果表格（使用 rich）"""
        ...

    def export_json(self, result: EvaluationResult, output_path: str) -> None:
        """导出 JSON 格式的评测结果
        
        Args:
            result: 评测结果
            output_path: 输出文件路径
        """
        ...
```

---

## 3. 内置评分规则函数

所有规则函数签名统一为 `fn(trace: AgentTrace, args: dict) -> tuple[bool, str]`，
返回 `(是否通过, 评分理由)`。`args` 来自 `RubricItem.args`。

| 函数名 | 用途 | args 字段 |
|--------|------|----------|
| `check_tool_called` | 检查是否调用了指定工具 | `tool_name` |
| `check_tool_params` | 检查工具调用参数是否匹配（子集） | `tool_name`, `expected_params` |
| `check_tool_call_sequence` | 检查工具调用顺序（子序列） | `expected_sequence` |
| `check_no_extra_calls` | 检查无多余调用 | `allowed_tools` |
| `check_response_contains` | 检查最终回复包含关键词 | `keywords`, `match_all` |
| `check_response_format` | 检查输出格式合规 | `format` |
| `check_step_count` | 检查步骤数在范围内 | `min_steps`, `max_steps` |
| `check_token_efficiency` | 检查 token 效率 | `max_tokens` |
| `check_no_injection` | 检查未被 prompt 注入 | `sensitive_info` |
| `check_task_success` | 检查任务正常完成（未超时/超步） | （无） |

---

## 4. CLI 接口

```bash
# 运行完整评测
agent-bench run --agent raw_api --model gpt-4o

# 只跑特定维度
agent-bench run --agent langchain --dimension tool_use

# 只跑特定任务
agent-bench run --agent raw_api --task tool_use_001

# 指定输出路径
agent-bench run --agent raw_api --output results/report.json

# 列出所有可用任务
agent-bench list-tasks

# 列出所有维度
agent-bench list-dimensions
```

---

## 5. 错误类型

```python
class AgentBenchError(Exception):
    """基础异常"""

class TaskLoadError(AgentBenchError):
    """任务加载失败"""

class TaskNotFoundError(AgentBenchError):
    """任务不存在"""

class AgentTimeoutError(AgentBenchError):
    """Agent 执行超时"""

class AgentStepLimitError(AgentBenchError):
    """Agent 超出步数限制"""

class SandboxError(AgentBenchError):
    """沙箱执行错误"""

class ScoringError(AgentBenchError):
    """评分错误"""
```
