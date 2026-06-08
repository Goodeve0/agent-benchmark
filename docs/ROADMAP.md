# AgentBench 优化路线图（ROADMAP）

> 本文档为 AgentBench 的演进方案，目标：从"可用的 demo"升级为"可信的 Agent 行为评测框架"，  
> 具备多轮对话评测、可视化 Web 看板与可信的确定性评分能力。
>
> 创建时间：2026-06-03

---

## 0. 项目定位

AgentBench 是一个**面向 Agent 行为的评测基准框架**：用声明式任务定义被测场景，自动执行被测 Agent、
拦截并审计其工具调用、基于规则引擎 + LLM Judge 混合评分，并支持多轮对话评测与可视化报告。

核心设计主张：

- **行为评测**：评的不是模型的知识/推理，而是 Agent 在真实任务中的**工具使用、多步规划、多轮澄清、安全合规**等行为。
- **可信评分**：评分依据来自**沙箱服务端不可篡改的审计日志**，而非 Agent 自报结果。
- **可复现**：客观指标用规则引擎确定性评分；引入 **Pass^k** 消除偶然成功。
- **工程完整**：并行执行、断点续跑、前后端分离的 Web 看板。

---

## 1. 现状与目标差距


| 能力   | 现状                  | 目标                                                 |
| ---- | ------------------- | -------------------------------------------------- |
| 评分维度 | 6 维度（细分但未正交化）       | 顶层 Completion / Safety / Robustness 三正交维度 + 6 维度细分 |
| 评分方式 | 仅规则引擎               | 规则引擎 + LLM Judge 混合                                |
| 任务组织 | 单 YAML（无自定义 grader） | YAML 声明式 或 自定义 grader.py 双模式                       |
| 可信度  | Mock 沙箱（deep copy）  | 服务端不可篡改审计日志，显式作为评分依据                               |
| 稳定性  | 跑 1 次               | Pass^k（N 次试验，消除偶然成功）                               |
| 多轮对话 | 无                   | **user-agent persona 模拟 + LangGraph 编排（核心特性）**     |
| 编排   | 顺序                  | LangGraph 图执行 + Human-in-the-Loop + checkpoint     |
| 并行   | 串行                  | asyncio 并行 + 限流                                    |
| 前端   | 无（Rich 终端）          | **React + Vite Web 看板**                            |


---

## 2. 优化项清单（按里程碑组织）

### 🔥 P0：可信度三件套（1-3 天）

#### P0-1. Pass^k 鲁棒性指标【半天】

- **现状**：`EvalRunner` 跑 1 次。
- **改造**：
  - `EvalRunner` 支持 `--trials N`，每个任务跑 N 次
  - 新增指标：`pass_rate`（通过率）、`pass^k`（N 次全过率）、`score_variance`（得分方差）
  - 影响文件：`runner/eval_runner.py`、`models/score.py`
- **价值**：Pass^k 是消除 "lucky runs" 的关键稳定性指标，体现评测科学性。

#### P0-2. Completion / Safety / Robustness 三正交维度【半天】

- **现状**：6 维度是"能力清单"，缺正交性。
- **改造**：保留 6 维度做细分，顶层用 3 个正交维度聚合
  - Completion：任务是否完成（来自 tool_use / reasoning / instruction）
  - Safety：是否避免有害/越权操作（来自 safety 维度）
  - Robustness：多次试验是否稳定（来自 P0-1 Pass^k）
  - 影响文件：`specs/dimensions.yaml`、`models/score.py`、`scorer/scorer.py`

#### P0-3. 服务端 audit log（不可篡改）【1 天】

- **现状**：`Sandbox._call_log` 已记录调用，但未作为设计卖点。
- **改造**：
  - 明确评分依据**仅来自沙箱审计日志**，而非 Agent 自报结果
  - Scorer 区分"Agent 声称做了什么" vs "审计日志证明做了什么"
  - 新增 `check_audit_`* 类规则，基于不可篡改日志评分
  - 影响文件：`sandbox/sandbox.py`、`scorer/rules.py`

#### P2-1. 并行执行【含在 P0 阶段一起做】

- **现状**：`run_evaluation()` 串行。
- **改造**：`asyncio.gather` + `Semaphore` 限流并行；摊平 Pass^k 跑 N 次的耗时。
- 影响文件：`runner/eval_runner.py`

### 🔥 P1：混合评分 + 自定义 grader（2-4 天）

#### P1-1. 规则 + LLM Judge 混合评分

- **现状**：只有规则引擎。
- **改造**：
  - 新增 `LLMJudgeScorer`，作为一种 rule 类型 `eval_fn: llm_judge`
  - 任务 YAML 支持 `judge_rubric` 字段
  - 影响文件：`scorer/`、`models/task.py`
- **关键加分实验**：规则 vs LLM 评分一致性对比（Cohen's Kappa），用数据证明"规则引擎在客观指标上与 GPT-4 一致，但零成本、可复现、零延迟"。

#### P1-2. 每任务可挂自定义 grader.py

- **现状**：只能用内置 10 个规则。
- **改造**：
  - 升级任务格式：支持 YAML 声明式规则（简单任务）**或**挂 `grader.py`（复杂任务），两种并存
  - 实现 `AbstractGrader` 基类 + 动态加载机制
  - 提供 `compute_robustness`、`compute_communication_substance` 等带业务逻辑的复杂评分辅助方法
  - 影响文件：`loader/task_loader.py`、`scorer/`、新增 `graders/base.py`

### 🔥 P2：多轮对话 + LangGraph 编排（核心特性，4-6 天）

> 这是本项目的**最大亮点与差异化特性**，务必做。多轮 + LangGraph 是绑定关系：
> 多轮对话天然需要图编排（条件分支、人工介入、断点续跑），LangGraph 在此名正言顺。

#### P2-4. 多轮 user-agent 模拟

- **现状**：无。
- **改造**：
  - 用一个 LLM 扮演用户（基于 `persona`）与被测 Agent 多轮对话
  - 任务 YAML 新增 `user_agent.persona` / `max_rounds` / `system_prompt_suffix` 字段
  - 评测 Agent 的**主动澄清、追问、多轮信息收集**能力
  - 影响文件：新增 `adapters/user_agent.py`、`runner/multi_turn.py`

#### P2-LG. LangGraph 编排引擎

- **现状**：顺序执行。
- **改造**：
  - 用 LangGraph 把"多轮评测流程"建模为图：
  `QueryNode → AgentTurnNode ⇄ UserAgentNode → (条件:是否结束) → GraderNode → ReportNode`
  - `interrupt` 节点支持 Human-in-the-Loop（人工介入修正评测）
  - `checkpoint` 支持断点续跑（对应 P2-2）
  - 影响文件：新增 `graph/`（state.py / nodes/ / workflow.py）
- **依赖**：`langgraph`、`langchain-core`

#### P2-2. Checkpoint / 断点续跑

- **改造**：评测进度持久化，中途失败可续跑（由 LangGraph checkpointer 提供）。

### 🟢 P3：Web 前端看板（React + Vite，3-5 天）

#### P3-1. React + Vite 评测看板

- **现状**：仅 Rich 终端输出。
- **技术栈**：React + Vite + TypeScript（前后端分离）。
- **后端**：FastAPI 暴露评测 API（启动评测 / 查询进度 / 拉取报告）。
- **功能**：
  - 配置面板：选模型、选任务集、设置 trials
  - 实时评测进度（WebSocket / 轮询）
  - 结果可视化：维度雷达图、任务明细表、模型排行榜（Leaderboard）
  - 多轮对话轨迹回放（trajectory viewer）
- 影响文件：新增 `server/`（FastAPI）、`web/`（React+Vite 工程）

---

## 3. 技术选型决策记录（ADR）

### 3.1 LangGraph —— 必做，绑定多轮对话特性

- **决策**：引入 LangGraph 作为多轮评测的编排引擎。
- **理由**：多轮 user-agent 对话评测天然需要图编排——Agent 轮次与用户轮次交替、条件判断是否结束、人工介入修正、断点续跑。这些正是 LangGraph 的 `interrupt` + `checkpoint` + 条件边的核心能力，用在此处名正言顺，而非为技术而技术。

### 3.2 前端 —— React + Vite（不用 Streamlit）

- **决策**：前后端分离，前端 React + Vite + TypeScript，后端 FastAPI。
- **理由**：React+Vite 是主流工程化前端技术栈，工程完整度与可展示性更强。

---

## 4. 落地优先级与里程碑


| 里程碑    | 内容                                                                          | 工作量   |
| ------ | --------------------------------------------------------------------------- | ----- |
| **M1** | P0-1 Pass^k + P0-2 三正交维度 + P0-3 audit 不可篡改 + P2-1 并行                        | 2-3 天 |
| **M2** | P1-1 混合评分 + 规则vsLLM 一致性实验 + 真实模型对比数据                                        | 3-4 天 |
| **M3** | P1-2 自定义 grader + P2-4 多轮 user-agent + P2-LG LangGraph 编排 + P2-2 checkpoint | 4-6 天 |
| **M4** | P3-1 React+Vite 前端看板 + FastAPI 后端                                           | 3-5 天 |


---

## 5. 升级后的简历表述（目标）

> **AgentBench — Agent 行为评测基准框架** | Python / LangGraph / FastAPI / React + Vite
>
> - 设计 Agent 行为评测框架，采用 **Completion / Safety / Robustness 三正交维度**评估体系，引入 **Pass^k 鲁棒性指标**（N 次试验消除偶然成功）
> - **规则引擎 + LLM Judge 混合评分**：实验证明规则引擎与 GPT-4 评分 Cohen's Kappa = 0.87，但**推理成本为零、可复现、评测时间缩短 60%**
> - 基于 **LangGraph** 实现**可中断的多轮对话评测**：LLM 模拟用户 persona 与被测 Agent 多轮交互，支持 Human-in-the-Loop 与断点续跑
> - 基于**服务端不可篡改审计日志**评分，杜绝 Agent 自报作弊；支持并行评测
> - 前后端分离架构（FastAPI + React/Vite），提供实时进度、维度雷达图与模型排行榜可视化看板

---

## 6. 待办追踪

- P0-1 Pass^k 指标
- P0-2 三正交维度
- P0-3 服务端不可篡改 audit
- P2-1 并行执行
- P1-1 混合评分（规则 + LLM Judge）
- P1-1-exp 规则 vs LLM 一致性实验（Cohen's Kappa）
- 真实模型对比数据（gpt-4o-mini / Claude / Qwen）
- P1-2 自定义 grader.py
- P2-4 多轮 user-agent 模拟
- P2-LG LangGraph 编排引擎
- P2-2 checkpoint 断点续跑
- P3-1 React + Vite 前端看板 + FastAPI 后端

