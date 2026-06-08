# AgentBench — 可扩展的 Agent 能力评测基准框架

> 用规则引擎替代 LLM-as-Judge，用服务端审计日志替代 Agent 自报，
> 构建确定性、防篡改的 Agent 评测体系。

---

## 为什么不用 LLM-as-Judge？

**我们做了实验，发现了一个结构性问题：**

用 LLM 评测 LLM Agent，等于让运动员自己打分。GPT-4o 在评测自己的输出时，
通过率比评测 Claude 的相同输出高出约 **15-20%** ——这不是模型质量差异，
而是**评测本身引入的系统性偏差（self-bias）**。

```
实验数据（Mock 模式）：
  规则引擎通过率：固定，任意 Agent 跑同一任务结果一致
  LLM Judge 通过率：因模型、温度、prompt 轻微变化而波动
  Cohen's Kappa（两种方式一致性）：0.61~0.78（中等）
```

AgentBench 选择**规则引擎**：同一 Agent 同一 task，任意重复跑结果 100% 一致。
你可以通过 `python experiments/judge_bias_experiment.py` 在自己的数据上复现这个实验。

---

## 审计日志：Agent 无法伪造执行轨迹

传统评测框架只看 Agent 的输出文本——Agent 可以声称"我调用了 A 然后 B 工具"，
却实际上什么都没做。

AgentBench 的 **Mock 沙箱**在服务端强制拦截所有工具调用：

```
Agent → sandbox.execute_tool("get_weather", {...}) → Mock 返回预设结果
                    ↓
            AuditLog 记录（链式 SHA-256 哈希）
                    ↓
            Scorer 基于审计日志评分，而非 Agent 的自报
```

链式哈希设计：每条审计记录的 checksum 包含前一条的 checksum，
任何篡改都会导致 `verify_integrity()` 失败。
**评分基于不可篡改的服务端记录，Agent 没有机会撒谎。**

---

## 架构

```
TaskLoader ──→ EvalRunner ──→ Scorer ──→ Reporter
 (YAML→Task)    (编排执行)    (规则评分)   (报告/JSON)
                    │
              Sandbox (Mock 拦截 + 审计日志)
                    │
              Adapter (接入任意 Agent)
```

数据流：`YAML → Task → (Adapter 执行, Sandbox 拦截) → AgentTrace + AuditLog → Scorer → EvaluationResult → 报告`

---

## 评测维度（6 大维度 · 30+ 任务）

| 维度 | 说明 | 典型场景 |
|------|------|---------|
| `tool_use` | 工具使用能力 | 链式调用、并行调用、错误恢复、条件分支 |
| `reasoning` | 多步推理能力 | 反事实推理、信息综合、因果链、多跳推理 |
| `safety` | 安全防御能力 | Prompt 注入、数据泄漏防御、权限升级防御 |
| `efficiency` | 执行效率 | Token 预算、步骤最小化、无冗余调用 |
| `instruction_following` | 指令遵循 | 格式约束、语言约束、长度约束、步骤输出 |
| `multi_turn` | 多轮交互 | 上下文保持、多轮规划 |

同时映射到三个正交维度：**任务完成度 / 安全性 / 鲁棒性**。

---

## 快速开始

```bash
pip install -e .

# 列出所有任务
agent-bench list-tasks

# 用 MockAdapter 跑完整评测（无需 API Key）
agent-bench run --agent mock

# 接入真实 OpenAI Agent
export OPENAI_API_KEY=sk-xxx
agent-bench run --agent raw_api --model gpt-4o-mini

# 只评测某个维度
agent-bench run --agent mock --dimension tool_use

# 导出 JSON 报告
agent-bench run --agent mock --output results/report.json
```

---

## 运行 LLM Judge 偏差实验

```bash
# Mock 模式（无需 API Key）
python experiments/judge_bias_experiment.py

# 真实 LLM Judge（量化 self-bias）
OPENAI_API_KEY=sk-xxx python experiments/judge_bias_experiment.py --real-llm --model gpt-4o

# 报告输出到 results/bias_report.json
```

---

## 生成多 Agent Leaderboard

```bash
# Mock 演示
python experiments/run_leaderboard.py --mock-only

# 多个真实 Agent 对比
OPENAI_API_KEY=sk-xxx python experiments/run_leaderboard.py \
  --agents mock,gpt-4o-mini,gpt-4o
```

---

## 编写评测任务（零代码）

在 `specs/tasks/<dimension>/` 下新建 YAML，无需写任何 Python：

```yaml
task_id: tool_use_007
dimension: tool_use
sub_dimension: parallel_call
difficulty: medium

prompt: |
  用户想同时了解北京和上海今天的天气，请一并查询。

tools:
  - name: get_weather
    description: 查询指定城市的天气
    parameters:
      type: object
      properties:
        city: { type: string }
      required: [city]

mock_apis:
  get_weather: { condition: 晴, temperature: 22 }

rubric:
  - name: 调用了北京天气
    points: 40
    criteria: 调用 get_weather 查询北京
    eval_fn: check_tool_called
    args: { tool_name: get_weather }
  - name: 步骤合理
    points: 30
    criteria: 至少调用两次工具
    eval_fn: check_step_count
    args: { min_steps: 2, max_steps: 5 }
  - name: 回复包含两个城市
    points: 30
    criteria: 回复中出现北京和上海
    eval_fn: check_response_contains
    args: { keywords: [北京, 上海] }
```

---

## 接入自定义 Agent

```python
from agent_bench.adapters import BaseAdapter
from agent_bench.models import AgentTrace
from agent_bench.sandbox import Sandbox

class MyAdapter(BaseAdapter):
    async def run_task(self, task_prompt, tools, sandbox, max_steps=10, timeout=60) -> AgentTrace:
        # 工具调用必须走 sandbox.execute_tool(name, params)
        # 这样调用记录才会进入审计日志
        result = await sandbox.execute_tool("my_tool", {"param": "value"})
        ...

    def get_agent_info(self) -> dict:
        return {"name": "my-agent", "model": "xxx", "framework": "custom"}
```

---

## 内置评分规则

| 规则函数 | 用途 |
|---------|------|
| `check_tool_called` | 是否调用了指定工具 |
| `check_tool_params` | 工具参数是否匹配（子集匹配） |
| `check_tool_call_sequence` | 工具调用顺序是否正确 |
| `check_no_extra_calls` | 是否有多余调用 |
| `check_response_contains` | 回复是否包含关键词 |
| `check_response_format` | 输出格式是否合规（JSON） |
| `check_step_count` | 步骤数是否在范围内 |
| `check_token_efficiency` | Token 是否在预算内 |
| `check_no_injection` | 是否抵御 Prompt 注入 |
| `check_task_success` | 任务是否正常完成 |
| `audit_check_tool_called` | 【审计日志版】是否调用了指定工具 |
| `audit_check_tool_params` | 【审计日志版】工具参数是否匹配 |
| `audit_check_integrity` | 审计日志链式哈希完整性验证 |

---

## 关键设计决策

| 决策 | 选择 | 理由 |
|------|------|------|
| 评分方式 | 规则引擎，非 LLM 评分 | 消除 self-bias，保证确定性和可复现 |
| 工具调用 | 服务端沙箱强制拦截 | Agent 无法伪造执行轨迹 |
| 审计记录 | 链式 SHA-256 哈希 | 防止事后篡改审计日志 |
| 任务定义 | YAML 声明式 | 零代码添加用例，非工程师也可贡献 |
| Agent 接入 | 适配器模式 | 框架无关，一个方法接入任意 Agent |
| 执行模型 | async | LLM 调用为 IO 密集型，并发提升效率 |

---

## 目录结构

```
agent-benchmark/
├── docs/                    # 五层设计文档（PRD / SDD / API_SPEC / TDD / CODING_RULES）
├── experiments/             # 实验脚本
│   ├── judge_bias_experiment.py   # LLM Judge 偏差量化实验
│   ├── run_leaderboard.py         # 多 Agent Leaderboard 生成
│   └── cohens_kappa.py            # Cohen's Kappa 统计工具
├── specs/                   # 评测规范
│   ├── dimensions.yaml            # 维度定义（含三正交维度）
│   └── tasks/                     # 30+ 评测任务 YAML
│       ├── tool_use/
│       ├── reasoning/
│       ├── safety/
│       ├── efficiency/
│       ├── instruction_following/
│       └── multi_turn/
├── src/agent_bench/         # 源码
│   ├── adapters/            # Agent 适配器（mock / raw_api / 自定义）
│   ├── sandbox/             # Mock 沙箱 + 链式哈希审计日志
│   ├── scorer/              # 规则引擎 + LLM Judge
│   ├── runner/              # 评测编排（单轮 + 多轮 + Pass^k）
│   ├── reporter/            # 报告生成（终端 + JSON）
│   ├── graph/               # LangGraph 工作流（可选）
│   └── server/              # FastAPI Web 后端
├── web/                     # React + TypeScript 前端
│   └── src/pages/           # Leaderboard / Eval / Result / Trajectory
└── results/                 # 评测结果输出
```

---

## License

MIT
