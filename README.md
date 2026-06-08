# AgentBench — Agent 能力评测基准框架

> 一个可扩展的 Agent 能力评测框架：用 YAML 定义评测任务，自动执行被测 Agent、
> 拦截工具调用、基于规则确定性评分，并生成多维度评测报告。

## ✨ 项目亮点

- **多维度评测体系**：覆盖工具使用、多步推理、记忆、指令遵循、执行效率、安全性 6 大维度、18 个子维度。
- **适配器模式接入任意 Agent**：实现一个 `run_task` 方法即可接入任意框架。内置 `MockAdapter`（无需 API Key 即可演示）与 `RawAPIAdapter`（OpenAI Function Calling）。
- **Mock 沙箱隔离**：拦截 Agent 的全部工具调用，返回预设结果，保证评测**确定性、可复现、不触达真实服务**。
- **规则引擎评分（非 LLM 评分）**：内置 10 类评分规则函数，同一 Agent 同任务多次评测结果一致，规避 LLM-as-Judge 的随机性。
- **声明式任务定义**：评测任务全部用 YAML 描述，新增评测用例**零代码**。
- **文档驱动开发（DDD）**：完整的 PRD / SDD / API Spec / TDD / 编码规范五层文档，约束实现不跑偏。

## 🏗️ 架构

```
TaskLoader ──→ EvalRunner ──→ Scorer ──→ Reporter
 (YAML→Task)    (编排执行)      (规则评分)   (报告)
                    │              
                Sandbox (Mock 拦截)   
                    │              
                Adapter (接入 Agent) 
```

数据流：`YAML → Task → (Adapter 执行, Sandbox 拦截) → AgentTrace → Scorer → EvaluationResult → 报告`

## 📦 安装

```bash
# 基础安装（仅需 MockAdapter 演示）
pip install -e .

# 需要接入真实 OpenAI Agent
pip install -e ".[openai]"

# 开发环境
pip install -e ".[dev]"
```

## 🚀 快速开始

```bash
# 列出所有评测维度
agent-bench list-dimensions

# 列出所有评测任务
agent-bench list-tasks

# 用内置 MockAdapter 跑完整评测（无需 API Key）
agent-bench run --agent mock

# 接入真实 OpenAI Agent
export OPENAI_API_KEY=sk-xxx
agent-bench run --agent raw_api --model gpt-4o

# 只评测某个维度，并导出 JSON
agent-bench run --agent mock --dimension tool_use --output results/report.json
```

## 🧩 编写一个评测任务

在 `specs/tasks/<dimension>/` 下新建 YAML 即可，无需写代码：

```yaml
task_id: tool_use_001
dimension: tool_use
sub_dimension: tool_chaining
difficulty: medium
prompt: 用户问"北京明天要不要带伞"，请先查天气再给建议。
tools:
  - name: get_weather
    description: 查询天气
    parameters:
      type: object
      properties:
        city: { type: string, default: 北京 }
mock_apis:
  get_weather: { condition: 雨 }
rubric:
  - name: 调用天气工具
    points: 50
    criteria: 正确调用 get_weather
    eval_fn: check_tool_called
    args: { tool_name: get_weather }
  - name: 回复包含结论
    points: 50
    criteria: 回复包含"雨"
    eval_fn: check_response_contains
    args: { keywords: [雨] }
```

## 🔌 接入自定义 Agent

继承 `BaseAdapter`，实现两个方法：

```python
from agent_bench.adapters import BaseAdapter
from agent_bench.models import AgentTrace, ToolDef
from agent_bench.sandbox import Sandbox

class MyAdapter(BaseAdapter):
    async def run_task(self, task_prompt, tools, sandbox, max_steps=10, timeout=60) -> AgentTrace:
        # 你的 Agent 逻辑；工具调用必须走 sandbox.execute_tool(name, params)
        ...

    def get_agent_info(self) -> dict:
        return {"name": "my-agent", "model": "xxx", "framework": "custom"}
```

## 📊 内置评分规则

| 规则函数 | 用途 |
|---------|------|
| `check_tool_called` | 是否调用了指定工具 |
| `check_tool_params` | 工具参数是否匹配 |
| `check_tool_call_sequence` | 工具调用顺序是否正确 |
| `check_no_extra_calls` | 是否有多余调用 |
| `check_response_contains` | 回复是否包含关键词 |
| `check_response_format` | 输出格式是否合规（JSON） |
| `check_step_count` | 步骤数是否在预算内 |
| `check_token_efficiency` | token 是否在预算内 |
| `check_no_injection` | 是否抵御 prompt 注入 |
| `check_task_success` | 任务是否正常完成 |

## 🧠 关键设计决策

| 决策 | 选择 | 理由 |
|------|------|------|
| 评分方式 | 规则引擎而非 LLM 评分 | 确定性、可复现，避免评测本身引入随机性 |
| 工具调用 | 经 Sandbox 拦截 Mock | 隔离外部依赖，评测稳定且免费 |
| 任务定义 | YAML 声明式 | 新增用例零代码，非工程同学也能贡献 |
| Agent 接入 | 适配器模式 | 框架无关，扩展成本低 |
| 执行模型 | async | LLM 调用为 IO 密集型 |

## 📁 目录结构

```
agent-benchmark/
├── docs/            # 五层设计文档（PRD/SDD/API_SPEC/TDD/CODING_RULES）
├── specs/           # 评测规范（dimensions.yaml + tasks/*.yaml）
├── src/agent_bench/ # 源码（models/loader/sandbox/scorer/adapters/runner/reporter/cli）
├── results/         # 评测结果输出
└── pyproject.toml
```

## 📄 License

MIT
