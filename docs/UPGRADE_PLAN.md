# AgentBench 企业级评测平台升级方案

> **版本**: v1.0  
> **创建时间**: 2026-06-08  
> **目标**: 从"可以跑的 Demo"变成"可以持续运营的评测平台"，核心补三块：**真实数据、持续监控、工程闭环**

---

## 0. 现状诊断

### 0.1 当前架构

```
TaskLoader(YAML) → EvalRunner(编排) → Adapter(Agent接口) → Sandbox(沙箱)
                                              ↓
                            AgentTrace ← 工具调用拦截
                                              ↓
                           Scorer(规则+LLM Judge) → Reporter(报告)
```

### 0.2 核心问题

| 问题 | 表现 | 影响 |
|------|------|------|
| **数据全靠 Mock** | 任务 YAML 手写，沙箱返回预设值，没有真实 Agent 运行数据 | 评测结果无法反映真实能力 |
| **跑一次看报告** | 没有定时任务、没有趋势对比、没有历史追踪 | 看不到 Agent 是否在进步 |
| **没有业务闭环** | 评测结果只输出 JSON，不接入 CI/CD，不影响发布决策 | 评测和开发割裂 |
| **LLM Judge 未校准** | 用 LLM 给 LLM 打分，没有人工标注校准集 | 评分可信度存疑 |
| **沙箱进程内隔离** | AST 检查可被绕过，无资源限制 | 安全性不足 |

### 0.3 保留的优势（不要动）

- **链式哈希审计日志** — 服务端不可篡改，这是核心差异化，必须保留并扩展到 Trace 上报场景
- **三正交维度体系** — Completion / Safety / Robustness 的拆解方式有理论支撑
- **Pass^k 鲁棒性指标** — 多 trial 量化偶然成功，工程上有价值
- **Cohen's d 效应量** — 统计显著性对比，比"分数高低"更有说服力

---

## 1. 第一阶段：真实 Trace 接入（2-3 周）

### 1.1 目标

评测不再依赖 Mock，能吃进真实 Agent 的运行数据。

### 1.2 架构变更

```
                          ┌─────────────────────┐
                          │  外部 Agent 进程     │
                          │  (pip install        │
                          │   agentbench-sdk)    │
                          └──────────┬──────────┘
                                     │ 异步上报 Trace
                                     ▼
┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐
│TaskLoader │───→│EvalRunner │───→│TraceStore │───→│ Scorer   │
│(YAML/DB)  │    │(编排执行)  │    │(持久化)   │    │(评分引擎) │
└──────────┘    └──────────┘    └──────────┘    └──────────┘
                                     │
                              ┌──────┴──────┐
                              │ 链式哈希审计  │
                              │ (防篡改校验)  │
                              └─────────────┘
```

### 1.3 Trace 上报 SDK (`agentbench-sdk`)

一个轻量 Python 包，外部 Agent 只需几行代码就能把运行数据上报到 AgentBench。

#### 1.3.1 包结构

```
agentbench-sdk/
├── pyproject.toml
├── src/
│   └── agentbench_sdk/
│       ├── __init__.py          # 导出 TraceClient, trace_action
│       ├── client.py            # TraceClient 核心类
│       ├── models.py            # TracePayload, ActionRecord 数据模型
│       ├── transport.py         # HTTP 传输层（异步批量上报）
│       ├── integrations/
│       │   ├── __init__.py
│       │   ├── openai.py        # OpenAI SDK 回调集成
│       │   ├── langchain.py     # LangChain 回调集成
│       │   └── base.py          # 通用回调基类
│       └── context.py           # trace_context 上下文管理器
└── tests/
```

#### 1.3.2 核心 API 设计

```python
from agentbench_sdk import TraceClient, trace_action

# 初始化（一次）
client = TraceClient(
    endpoint="http://localhost:8000/api/v1/traces",
    agent_name="my-agent",
    agent_version="1.2.0",
    api_key="...",           # 可选鉴权
)

# 方式一：上下文管理器（推荐）
with client.trace(task_id="task_001") as t:
    # 记录工具调用
    t.action(
        action_type="tool_call",
        tool_name="search",
        parameters={"query": "weather beijing"},
        result={"temp": 28, "condition": "sunny"},
    )
    # 记录思考
    t.action(action_type="thinking", content="需要先查天气再决定行程")
    # 记录最终回复
    t.action(action_type="response", content="北京今天晴天，28度")
    # 设置汇总信息
    t.set_summary(total_tokens=1500, final_response="北京今天晴天，28度")

# 方式二：装饰器
@trace_action(client, tool_name="database_query")
def query_db(sql: str):
    return db.execute(sql)

# 方式三：OpenAI SDK 集成（自动捕获）
from agentbench_sdk.integrations.openai import OpenAITracer
tracer = OpenAITracer(client)
tracer.wrap()  # monkey-patch openai.ChatCompletion.create
```

#### 1.3.3 传输层设计

```
Agent 进程                          AgentBench Server
──────────                          ─────────────────
Action 1 ──┐
Action 2 ──┤──→ 本地缓冲队列
Action 3 ──┘    (批量合并, 最多 50 条/批)
                  │
                  ├──→ 异步 HTTP POST /api/v1/traces
                  │    (失败重试 3 次, 指数退避)
                  │
                  └──→ 进程退出时 flush 剩余
```

- **异步非阻塞**: 上报在后台线程执行，不影响 Agent 主流程
- **批量合并**: 减少 HTTP 请求次数，每 50 条或每 2 秒发送一次
- **失败容忍**: 上报失败不抛异常，只记日志，不阻塞 Agent 运行
- **优雅关闭**: `atexit` 注册 flush，确保进程退出前上报剩余数据

#### 1.3.4 数据模型

```python
class ActionRecord(BaseModel):
    """单条 Action 上报记录"""
    action_type: Literal["tool_call", "response", "thinking"]
    tool_name: str | None = None
    parameters: dict[str, Any] | None = None
    result: Any | None = None
    content: str | None = None
    timestamp: float
    duration_ms: float | None = None  # 工具调用耗时

class TracePayload(BaseModel):
    """一次 Trace 的完整上报数据"""
    trace_id: str                       # 客户端生成的 UUID
    task_id: str                        # 关联的任务 ID
    agent_name: str                     # Agent 标识
    agent_version: str                  # Agent 版本
    actions: list[ActionRecord]         # 动作列表
    total_tokens: int = 0              # 总 token 消耗
    final_response: str = ""           # 最终回复
    execution_time: float = 0.0        # 总耗时(秒)
    success: bool = True               # 是否成功
    error: str | None = None           # 错误信息
    metadata: dict[str, Any] | None = None
    # 链式哈希
    prev_hash: str | None = None       # 前一条 Trace 的哈希
    payload_hash: str = ""             # 本条 Trace 的 SHA-256 哈希
```

### 1.4 Trace 存储层

#### 1.4.1 存储方案

- **起步**: SQLite（零配置，适合开发和单机部署）
- **迁移路径**: SQLAlchemy ORM 抽象，后续可无缝切换到 PostgreSQL

#### 1.4.2 数据库 Schema

```sql
-- Trace 主表
CREATE TABLE traces (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    trace_id      TEXT NOT NULL UNIQUE,          -- 客户端上报的 UUID
    task_id       TEXT NOT NULL,                  -- 关联任务
    agent_name    TEXT NOT NULL,                  -- Agent 标识
    agent_version TEXT NOT NULL DEFAULT '',       -- Agent 版本
    source        TEXT NOT NULL DEFAULT 'sdk',    -- 来源: sdk / runner
    total_tokens  INTEGER NOT NULL DEFAULT 0,
    total_steps   INTEGER NOT NULL DEFAULT 0,
    final_response TEXT NOT NULL DEFAULT '',
    execution_time REAL NOT NULL DEFAULT 0.0,
    success       INTEGER NOT NULL DEFAULT 1,    -- SQLite 用 0/1 表示 bool
    error         TEXT,
    metadata      TEXT,                           -- JSON 字符串
    prev_hash     TEXT,                           -- 链式哈希: 前一条的哈希
    payload_hash  TEXT NOT NULL,                  -- 链式哈希: 本条哈希
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Action 明细表
CREATE TABLE trace_actions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    trace_id      TEXT NOT NULL REFERENCES traces(trace_id),
    step          INTEGER NOT NULL,
    action_type   TEXT NOT NULL,                  -- tool_call / response / thinking
    tool_name     TEXT,
    parameters    TEXT,                           -- JSON 字符串
    result        TEXT,                           -- JSON 字符串
    content       TEXT,
    timestamp     REAL NOT NULL,
    duration_ms   REAL,
    metadata      TEXT                            -- JSON 字符串
);

-- 索引
CREATE INDEX idx_traces_task_id ON traces(task_id);
CREATE INDEX idx_traces_agent ON traces(agent_name, agent_version);
CREATE INDEX idx_traces_created ON traces(created_at);
CREATE INDEX idx_actions_trace_id ON trace_actions(trace_id);
```

#### 1.4.3 Trace 存储 API

```
POST   /api/v1/traces              # 上报 Trace（SDK 调用）
GET    /api/v1/traces              # 查询 Trace 列表（分页+过滤）
GET    /api/v1/traces/{trace_id}   # 获取 Trace 详情（含 Actions）
GET    /api/v1/traces/stats        # Trace 统计信息
POST   /api/v1/traces/verify       # 验证链式哈希完整性
```

查询参数支持:
- `task_id`: 按任务过滤
- `agent_name`: 按 Agent 过滤
- `agent_version`: 按版本过滤
- `success`: 按成功/失败过滤
- `start_time` / `end_time`: 按时间范围过滤
- `limit` / `offset`: 分页

### 1.5 基于真实 Trace 的评分

#### 1.5.1 评分流程扩展

```
现有流程:
  Task → EvalRunner → Adapter.run_task() → AgentTrace → Scorer

新增流程:
  已有 Trace → TraceStore.query() → AgentTrace → Scorer
```

新增 CLI 命令:
```bash
# 对已存储的真实 Trace 进行评分
agent-bench score-traces \
    --agent my-agent \
    --version 1.2.0 \
    --task task_001 \
    --dimension tool_use

# 对指定时间范围内的 Trace 评分
agent-bench score-traces \
    --agent my-agent \
    --from 2026-06-01 \
    --to 2026-06-08
```

新增 API:
```
POST /api/v1/score/traces    # 对已存储的 Trace 触发评分
```

#### 1.5.2 Scorer 适配

现有 [`Scorer.score_task()`](src/agent_bench/scorer/rules.py) 接受 `(AgentTrace, Task)` 参数，无需修改即可处理真实 Trace——只要 Trace 中有 `task_id` 能关联到 Task 的 rubric。

对于没有对应 Task YAML 的自由上报 Trace，新增"自由评分"模式:
- 只使用 LLM Judge 评分（无需 rubric）
- 或使用预设的通用评分模板

### 1.6 交付物

| 交付物 | 说明 |
|--------|------|
| `agentbench-sdk` 包 | `pip install agentbench-sdk` 可用 |
| Trace 存储 + 查询 API | SQLite 持久化，REST API 可查询 |
| OpenAI / LangChain 集成 | 自动捕获 Agent 运行数据 |
| 真实 Trace 评分 demo | `agent-bench score-traces` 命令 |
| 链式哈希扩展 | 上报的 Trace 同样防篡改 |

### 1.7 简历亮点

> 设计并实现了 Trace 采集 SDK，支持 OpenAI / LangChain / 自定义 Agent 的运行数据接入评测系统，异步批量上报不阻塞主流程，链式哈希保证上报数据不可篡改

---

## 2. 第二阶段：持续监控 + 数据回流（3-4 周）

### 2.1 目标

从"跑一次看报告"变成"持续运行，自动发现问题"。

### 2.2 架构变更

```
┌──────────────────────────────────────────────────────────┐
│                    调度引擎 (Scheduler)                    │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐                  │
│  │定时任务1 │  │定时任务2 │  │定时任务3 │  ...             │
│  │每天2点   │  │每小时    │  │每周一    │                  │
│  └────┬────┘  └────┬────┘  └────┬────┘                  │
└───────┼────────────┼────────────┼────────────────────────┘
        │            │            │
        ▼            ▼            ▼
┌──────────────────────────────────────────────────────────┐
│                    评测执行 (EvalRunner)                    │
│                                                          │
│  1. 拉取最新 Trace (按 agent + version + 时间范围)          │
│  2. Scorer 评分                                           │
│  3. 写入评分结果 (ScoreStore)                              │
│  4. 检查告警条件                                          │
│  5. 低分 Trace → BadCase 回流                              │
└──────────────────────────────────────────────────────────┘
        │                          │
        ▼                          ▼
┌──────────────┐          ┌──────────────┐
│ 告警通知      │          │ BadCase 数据集 │
│ (邮件/Webhook)│          │ (自动回流)     │
└──────────────┘          └──────────────┘
```

### 2.3 定时自动评估任务

#### 2.3.1 数据模型

```python
class EvalSchedule(BaseModel):
    """评估调度任务配置"""
    schedule_id: str                         # UUID
    name: str                                # 任务名称
    agent_name: str                          # Agent 标识
    agent_version: str | None = None         # 版本（None=最新）
    dimension: str | None = None             # 评测维度（None=全部）
    task_ids: list[str] | None = None        # 指定任务ID（None=全部）
    cron: str                                # Cron 表达式，如 "0 2 * * *"
    enabled: bool = True                     # 是否启用
    # 评分配置
    scorer_type: Literal["rules", "llm_judge", "mixed"] = "rules"
    judge_model: str = "gpt-4o"
    # 告警配置
    alert_on_score_drop: bool = True         # 分数下降时告警
    alert_threshold: float = 0.0             # 低于此分数告警
    alert_webhook: str | None = None         # Webhook URL
    alert_email: list[str] | None = None     # 告警邮件列表
    # 元数据
    created_at: str = ""
    updated_at: str = ""
    last_run_at: str | None = None
    last_run_status: str | None = None       # success / failed
```

#### 2.3.2 调度器实现

使用 `APScheduler` 库:

```python
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

scheduler = AsyncIOScheduler()

# 启动时从数据库加载所有 enabled 的调度任务
for schedule in db.load_schedules(enabled_only=True):
    trigger = CronTrigger.from_crontab(schedule.cron)
    scheduler.add_job(
        run_scheduled_eval,
        trigger=trigger,
        args=[schedule],
        id=schedule.schedule_id,
        replace_existing=True,
    )

scheduler.start()
```

#### 2.3.3 执行流程

```python
async def run_scheduled_eval(schedule: EvalSchedule):
    """执行一次定时评估"""
    # 1. 拉取 Trace
    traces = trace_store.query(
        agent_name=schedule.agent_name,
        agent_version=schedule.agent_version,
        since=schedule.last_run_at,  # 只看上次运行之后的新 Trace
    )

    if not traces:
        logger.info(f"调度 {schedule.name}: 无新 Trace，跳过")
        return

    # 2. 评分
    reports = []
    for trace in traces:
        task = task_loader.load_task_by_id(trace.task_id)
        report = await scorer.score_task(trace, task)
        reports.append(report)

    # 3. 存储评分结果
    score_store.save(schedule.schedule_id, reports)

    # 4. 检查告警
    await check_alerts(schedule, reports)

    # 5. BadCase 回流
    await reflux_bad_cases(schedule, reports, traces)

    # 6. 更新调度状态
    schedule.last_run_at = now()
    schedule.last_run_status = "success"
```

#### 2.3.4 管理接口

```
POST   /api/v1/schedules              # 创建调度任务
GET    /api/v1/schedules              # 列出调度任务
GET    /api/v1/schedules/{id}         # 获取调度详情
PUT    /api/v1/schedules/{id}         # 更新调度配置
DELETE /api/v1/schedules/{id}         # 删除调度任务
POST   /api/v1/schedules/{id}/trigger # 手动触发一次执行
GET    /api/v1/schedules/{id}/runs    # 获取执行历史
```

### 2.4 BadCase 自动回流

#### 2.4.1 回流策略

```python
class BadCaseReflux(BaseModel):
    """BadCase 回流配置"""
    enabled: bool = True
    score_threshold: float = 60.0      # 低于此分数视为 BadCase
    dimensions: list[str] | None = None  # 仅回流指定维度的 BadCase
    max_per_run: int = 50              # 单次回流上限
    auto_create_task: bool = False     # 是否自动创建评测任务
```

#### 2.4.2 回流数据模型

```sql
CREATE TABLE bad_cases (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    trace_id      TEXT NOT NULL REFERENCES traces(trace_id),
    task_id       TEXT NOT NULL,
    agent_name    TEXT NOT NULL,
    agent_version TEXT NOT NULL,
    score         REAL NOT NULL,                 -- 得分
    max_score     REAL NOT NULL,                 -- 满分
    percentage    REAL NOT NULL,                 -- 得分率
    dimension     TEXT,                          -- 失败维度
    failure_reason TEXT,                         -- 失败原因摘要
    reflux_source TEXT NOT NULL DEFAULT 'auto',  -- auto / manual
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    resolved      INTEGER NOT NULL DEFAULT 0     -- 是否已修复
);
```

#### 2.4.3 BadCase → 评测任务的自动生成

```python
async def reflux_bad_cases(schedule, reports, traces):
    """低分 Trace 自动回流为 BadCase"""
    for report, trace in zip(reports, traces):
        pct = report.percentage
        if pct < schedule.bad_case_config.score_threshold:
            # 存入 BadCase 表
            bad_case_store.save(BadCase(
                trace_id=trace.trace_id,
                task_id=trace.task_id,
                agent_name=trace.agent_name,
                score=report.score,
                max_score=report.max_score,
                percentage=pct,
                dimension=report.lowest_dimension,
                failure_reason=report.summarize_failures(),
            ))

            # 可选：自动创建评测任务
            if schedule.bad_case_config.auto_create_task:
                task_yaml = generate_task_from_bad_case(trace, report)
                task_loader.save_task(task_yaml)
```

### 2.5 告警机制

#### 2.5.1 告警规则

| 规则类型 | 条件 | 示例 |
|---------|------|------|
| **分数阈值** | 单次评分 < threshold | `tool_use 维度得分 45% < 60%` |
| **连续下降** | 连续 N 次评分下降 | `completion 维度连续 3 次下降` |
| **突变检测** | 评分环比下降超过 X% | `safety 维度环比下降 25%` |
| **异常率** | 失败 Trace 占比超阈值 | `失败率 30% > 10%` |

#### 2.5.2 告警通知渠道

```python
class AlertChannel(BaseModel):
    """告警通知渠道"""
    channel_type: Literal["webhook", "email", "log"]
    webhook_url: str | None = None
    email_to: list[str] | None = None
    template: str | None = None           # 自定义通知模板
```

#### 2.5.3 告警数据模型

```sql
CREATE TABLE alerts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    schedule_id   TEXT,
    alert_type    TEXT NOT NULL,            -- threshold / consecutive_drop / spike / error_rate
    severity      TEXT NOT NULL DEFAULT 'warning',  -- info / warning / critical
    agent_name    TEXT NOT NULL,
    dimension     TEXT,
    message       TEXT NOT NULL,            -- 告警内容
    current_value REAL,
    threshold     REAL,
    notified      INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    resolved_at   TEXT
);
```

### 2.6 前端可视化增强

#### 2.6.1 新增页面/组件

| 页面 | 核心组件 | 说明 |
|------|---------|------|
| **评分趋势页** | 折线图（时间轴） | X 轴=时间，Y 轴=分数，按维度分线，支持多版本叠加 |
| **版本对比页** | 对比表格 + 雷达图 | 选择两个版本，展示各维度分数差值 + Cohen's d |
| **BadCase 列表页** | 表格 + 筛选器 | 按维度/分数/时间筛选，支持一键回流到数据集 |
| **调度管理页** | 表格 + 表单 | 创建/编辑/启停调度任务，查看执行历史 |
| **告警历史页** | 时间线 | 查看告警记录，标记已处理 |

#### 2.6.2 关键图表规格

**评分趋势折线图:**
```
  分数
  100 ┤
   90 ┤     ●───●───●───●  v1.2.0
   80 ┤  ●───●                v1.1.0
   70 ┤●─╯
   60 ┤
      └──┬───┬───┬───┬───┬── 时间
        6/1 6/2 6/3 6/4 6/5
```

- 数据源: `GET /api/v1/scores/trend?agent=xxx&dimension=tool_use&from=...&to=...`
- 支持多版本叠加对比
- 点击数据点可展开查看对应 Trace

**版本对比表格:**
```
| 维度       | v1.1.0 | v1.2.0 | Δ     | Cohen's d | 显著? |
|-----------|--------|--------|-------|-----------|-------|
| tool_use  | 72.3%  | 84.1%  | +11.8 | 1.24      | ✅    |
| safety    | 91.0%  | 88.5%  | -2.5  | 0.31      | ❌    |
| reasoning | 65.0%  | 67.2%  | +2.2  | 0.18      | ❌    |
```

### 2.7 交付物

| 交付物 | 说明 |
|--------|------|
| 调度引擎 | 基于 APScheduler 的定时评估任务调度器 |
| BadCase 回流 | 低分 Trace 自动沉淀 + 可选自动生成评测任务 |
| 告警机制 | 阈值/连续下降/突变/异常率 四种规则 + Webhook/Email 通知 |
| 前端趋势页 | 评分趋势折线图 + 版本对比 + BadCase 列表 + 调度管理 |

### 2.8 简历亮点

> 实现了评分趋势监控和 BadCase 自动回流机制，线上真实的失败 Case 自动沉淀为离线测试集，数据集持续保鲜，覆盖更多边界场景；支持多维告警规则（阈值/连续下降/突变检测），确保 Agent 质量退化时及时预警

---

## 3. 第三阶段：工程闭环（2-3 周）

### 3.1 目标

评测结果嵌入发布流程，成为质量卡点。

### 3.2 CI/CD 集成

#### 3.2.1 CLI 命令

```bash
# CI 评测卡点命令
agent-bench ci-check \
    --agent my-agent \
    --version $GIT_SHA \
    --dimension tool_use \
    --threshold 80 \
    --min-pass-rate 0.7

# 退出码:
#   0 = 通过（所有维度达标）
#   1 = 不通过（有维度低于阈值）
#   2 = 执行异常

# 输出格式 (JSON):
{
  "passed": true,
  "summary": {
    "tool_use": {"score": 84.1, "threshold": 80, "passed": true},
    "safety":   {"score": 91.0, "threshold": 80, "passed": true}
  },
  "details_url": "http://localhost:3000/reports/run_xxx"
}
```

#### 3.2.2 GitHub Action

```yaml
# .github/workflows/agent-bench-ci.yml
name: AgentBench CI Check

on:
  pull_request:
    branches: [main]

jobs:
  eval-check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install AgentBench
        run: pip install -e ".[all]"

      - name: Run AgentBench CI Check
        uses: agent-bench/ci-action@v1
        with:
          agent: my-agent
          dimension: tool_use,safety
          threshold: "80"
          min-pass-rate: "0.7"
          server-url: ${{ secrets.AGENTBENCH_URL }}
          api-key: ${{ secrets.AGENTBENCH_API_KEY }}

      - name: Comment PR
        if: always()
        uses: actions/github-script@v7
        with:
          script: |
            const fs = require('fs');
            const result = JSON.parse(fs.readFileSync('agent-bench-result.json'));
            const body = `## AgentBench 评测结果\n` +
              Object.entries(result.summary).map(([dim, info]) =>
                `- **${dim}**: ${info.score}% (阈值: ${info.threshold}%) ${info.passed ? '✅' : '❌'}`
              ).join('\n') +
              `\n\n**总体**: ${result.passed ? '✅ 通过' : '❌ 不通过'}`;
            github.rest.issues.createComment({
              owner: context.repo.owner,
              repo: context.repo.repo,
              issue_number: context.issue.number,
              body
            });
```

#### 3.2.3 CI Action 发布

将 GitHub Action 打包发布到 GitHub Marketplace，项目可直接引用：

```
uses: agent-bench/ci-action@v1
```

### 3.3 成本 & 性能看板

#### 3.3.1 从 Trace 数据提取指标

```python
class CostMetrics(BaseModel):
    """成本指标"""
    agent_name: str
    agent_version: str
    period: str                        # 统计周期
    total_traces: int
    total_tokens: int
    # 按模型细分
    tokens_by_model: dict[str, int]    # {"gpt-4o": 50000, "gpt-3.5": 20000}
    # 预估费用
    estimated_cost_usd: float          # 按模型单价换算
    cost_by_model: dict[str, float]    # {"gpt-4o": 2.5, "gpt-3.5": 0.04}

class PerformanceMetrics(BaseModel):
    """性能指标"""
    agent_name: str
    agent_version: str
    period: str
    total_traces: int
    success_rate: float                # 成功率
    avg_execution_time: float          # 平均耗时
    p50_execution_time: float          # P50 耗时
    p95_execution_time: float          # P95 耗时
    avg_steps: float                   # 平均步数
    avg_tool_calls: float              # 平均工具调用次数
    tool_call_distribution: dict[str, int]  # {"search": 50, "database": 30}
    error_rate: float                  # 错误率
    error_types: dict[str, int]        # {"timeout": 5, "step_limit": 3}
```

#### 3.3.2 模型单价表

```python
MODEL_PRICING = {
    "gpt-4o":        {"input": 2.50,  "output": 10.00},  # per 1M tokens
    "gpt-4o-mini":   {"input": 0.15,  "output": 0.60},
    "gpt-3.5-turbo": {"input": 0.50,  "output": 1.50},
    "claude-3-opus": {"input": 15.00, "output": 75.00},
    "claude-3-sonnet":{"input": 3.00,  "output": 15.00},
}
```

#### 3.3.3 看板页面

```
┌─────────────────────────────────────────────────────────┐
│ 📊 成本看板                          2026-06-01 ~ 06-08 │
├────────────────────┬────────────────────────────────────┤
│ 本周总费用         │ Token 消耗趋势（折线图）             │
│   $12.50           │  1.2M ┤                            │
│   较上周 ↓15%      │       ├──╮──╮                      │
│                    │  0.8M ┤  │  │──╮                    │
│ 费用明细:          │  0.4M ┤╭─╯  ╰  ╰──                 │
│   gpt-4o: $10.00   │       └──┬──┬──┬──┬──              │
│   gpt-3.5: $2.50   │        6/1 6/3 6/5 6/7            │
├────────────────────┼────────────────────────────────────┤
│ 性能指标           │ 延迟分布（直方图）                    │
│   成功率: 92.3%    │                                    │
│   P50: 3.2s       │   ▓▓▓▓▓▓▓▓▓▓▓                      │
│   P95: 8.7s       │   ▓▓▓▓▓▓▓▓▓                        │
│   平均步数: 4.2    │   ▓▓▓▓▓▓                            │
│   平均工具调用: 2.8│   ▓▓▓▓                              │
│                    │   ▓▓                                │
│ 工具调用分布:      │   ▓                                 │
│   search: 120     │   └──┬──┬──┬──┬──┬──               │
│   database: 85    │    0s 2s 4s 6s 8s 10s               │
│   weather: 42     │                                    │
└────────────────────┴────────────────────────────────────┘
```

#### 3.3.4 API 端点

```
GET /api/v1/metrics/cost       # 成本指标
GET /api/v1/metrics/performance # 性能指标
GET /api/v1/metrics/summary    # 综合摘要
```

查询参数:
- `agent_name`: Agent 标识
- `agent_version`: 版本
- `from` / `to`: 时间范围
- `granularity`: 聚合粒度 (hour / day / week)

### 3.4 多租户支持

#### 3.4.1 数据模型

```python
class Project(BaseModel):
    """项目（租户）"""
    project_id: str
    name: str
    description: str = ""
    owner: str                       # 负责人
    members: list[str] = []          # 成员列表
    settings: dict[str, Any] = {}    # 项目配置
    created_at: str = ""
```

#### 3.4.2 数据隔离

所有数据表增加 `project_id` 字段:
- `traces.project_id`
- `bad_cases.project_id`
- `eval_schedules.project_id`
- `alerts.project_id`

查询时自动按 `project_id` 过滤。

#### 3.4.3 项目管理页面

```
┌─────────────────────────────────────────────────────┐
│ 🏢 项目管理                                         │
├──────────┬──────────┬──────────┬──────────┬─────────┤
│ 项目名称  │ Agent数  │ 最近评测  │ 健康度    │ 操作    │
├──────────┼──────────┼──────────┼──────────┼─────────┤
│ 客服Bot   │ 2       │ 2h ago   │ 🟢 92%   │ 详情 | 删│
│ 数据分析  │ 1       │ 1d ago   │ 🟡 78%   │ 详情 | 删│
│ 内容审核  │ 3       │ 3d ago   │ 🔴 45%   │ 详情 | 删│
└──────────┴──────────┴──────────┴──────────┴─────────┘
```

#### 3.4.4 项目管理 API

```
POST   /api/v1/projects              # 创建项目
GET    /api/v1/projects              # 列出项目
GET    /api/v1/projects/{id}         # 项目详情
PUT    /api/v1/projects/{id}         # 更新项目
DELETE /api/v1/projects/{id}         # 删除项目
GET    /api/v1/projects/{id}/health  # 项目健康度
```

### 3.5 交付物

| 交付物 | 说明 |
|--------|------|
| `agent-bench ci-check` 命令 | CLI 评测卡点，低于阈值返回非零退出码 |
| GitHub Action | 可直接在 Marketplace 搜索安装 |
| 成本看板 | Token 消耗 + 预估费用 + 按模型细分 |
| 性能看板 | P50/P95 延迟 + 成功率 + 工具调用分布 |
| 多租户 | 项目级数据隔离，多 Agent 项目并行接入 |

### 3.6 简历亮点

> 设计了 CI/CD 评测卡点，评分不达标自动阻断发布；实现了 Token 成本与延迟的实时监控看板；支持多项目并行接入，数据逻辑隔离

---

## 4. 整体演进图

```
  现在                     第一阶段                第二阶段                第三阶段
────────────────────────────────────────────────────────────────────────────────────
 Mock 离线跑批    →     真实 Trace 接入    →    持续监控+回流     →    CI/CD 卡点
 （玩具）               （能用了）              （持续运营）           （企业级）

 数据：Mock            数据：真实 Trace        数据：自动保鲜         数据：生产卡点
 评分：批量一次         评分：按需触发          评分：定时自动          评分：提交触发
 报告：静态 JSON        报告：可查询历史         报告：趋势+对比        报告：PR 评论
 安全：AST 检查         安全：链式哈希           安全：告警机制          安全：发布卡点
 隔离：无              隔离：SDK 独立进程       隔离：项目级            隔离：项目+环境
```

## 5. 工作量估算

| 阶段 | 预计周期 | 难度 | 优先级 | 核心风险 |
|------|---------|------|--------|---------|
| 第一阶段：Trace 接入 | 2-3 周 | ⭐⭐ | **必做** | SDK 兼容性（不同 Agent 框架的差异） |
| 第二阶段：持续监控 | 3-4 周 | ⭐⭐⭐ | **重要** | 调度器可靠性（长时间运行的稳定性） |
| 第三阶段：CI/CD 闭环 | 2-3 周 | ⭐⭐ | 加分项 | GitHub Action 发布流程 |

## 6. 依赖关系

```
第一阶段 ──→ 第二阶段 ──→ 第三阶段
  │              │              │
  │              │              └── 需要：评分结果可查询 (Phase 2)
  │              └── 需要：Trace 持久化 (Phase 1)
  └── 无前置依赖，可立即开始
```

## 7. 不要动的东西

| 模块 | 原因 |
|------|------|
| **链式哈希审计日志** | 核心差异化，保持并扩展到 Trace 上报场景 |
| **三正交维度体系** | Completion / Safety / Robustness 有理论支撑 |
| **Pass^k 指标** | 工程价值明确，鲁棒性量化的标准做法 |
| **Cohen's d 效应量** | 统计显著性对比，比"分数高低"更有说服力 |
| **规则引擎** | 确定性评分的基石，不依赖 LLM |

## 8. 全部完成后的简历描述

> 从零设计并实现了企业级 Agent 评测平台，支持真实 Trace 采集接入、持续监控、BadCase 自动回流和 CI/CD 质量卡点。设计了轻量级 Trace 采集 SDK，兼容 OpenAI / LangChain / 自定义 Agent 框架；实现了基于 APScheduler 的定时评估调度器，支持评分趋势追踪和多版本横向对比；低分 Case 自动回流机制使数据集持续保鲜；CI/CD 集成使评测成为发布质量卡点，评分不达标自动阻断合并。平台采用链式哈希审计日志保证评测数据不可篡改，三正交维度（Completion / Safety / Robustness）+ Pass^k 鲁棒性指标 + Cohen's d 效应量提供统计可信的评测结论。
