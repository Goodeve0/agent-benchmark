# TDD: AgentBench — 测试驱动文档

> 本文档定义了所有测试用例，**先写测试，再写实现**。每个模块的测试用例与 API Spec 一一对应。

## 1. 测试策略总览

| 层级 | 测试类型 | 覆盖目标 | 工具 |
|------|---------|---------|------|
| 模型层 | 单元测试 | Pydantic 模型校验、序列化/反序列化 | pytest |
| Loader 层 | 单元测试 | YAML 解析、校验、默认值、边界情况 | pytest + fixtures |
| Sandbox 层 | 单元测试 | Mock 拦截、调用记录、未命中处理 | pytest |
| Adapter 层 | 集成测试 | 对接真实 API（mock httpx） | pytest + respx |
| Scorer 层 | 单元测试 | 每个评分规则函数、加权汇总、边界 | pytest |
| Runner 层 | 集成测试 | 完整执行流程、超时/步数限制 | pytest + asyncio |
| CLI 层 | E2E 测试 | 命令行入口 | typer.testing |
| 端到端 | 集成测试 | 从 YAML 到报告的完整流程 | pytest |

---

## 2. 模型层测试

### test_models.py

```python
# ===== ToolDef =====

def test_tool_def_creation():
    """正常创建 ToolDef"""

def test_tool_def_missing_required_field():
    """缺少必填字段时 pydantic 校验失败"""

def test_tool_def_parameters_must_be_dict():
    """parameters 必须是 dict 类型"""

# ===== RubricItem =====

def test_rubric_item_points_must_be_positive():
    """points 必须 > 0"""

def test_rubric_item_eval_fn_optional():
    """eval_fn 可选，默认 None"""

# ===== Task =====

def test_task_creation_from_dict():
    """从字典创建 Task"""

def test_task_difficulty_must_be_enum():
    """difficulty 只能是 easy/medium/hard"""

def test_task_tools_cannot_be_empty():
    """tools 列表不能为空"""

def test_task_rubric_cannot_be_empty():
    """rubric 列表不能为空"""

def test_task_mock_apis_default_empty():
    """mock_apis 默认为空字典"""

# ===== AgentAction =====

def test_agent_action_tool_call_requires_tool_name():
    """action_type=tool_call 时 tool_name 必填"""

def test_agent_action_step_starts_from_one():
    """step 从 1 开始"""

# ===== AgentTrace =====

def test_agent_trace_success_default_true():
    """success 默认为 True"""

def test_agent_trace_error_optional():
    """error 可选，默认 None"""

def test_agent_trace_serialization():
    """AgentTrace 可序列化为 JSON"""

# ===== ScoreDetail =====

def test_score_detail_points_cannot_exceed_max():
    """points 不能超过 max_points"""

# ===== ScoreReport =====

def test_score_report_total_score_equals_sum():
    """total_score 必须等于各 ScoreDetail.points 之和"""

# ===== EvaluationResult =====

def test_evaluation_result_overall_percentage():
    """overall_percentage = overall_score / overall_max_score * 100"""
```

---

## 3. TaskLoader 测试

### test_loader.py

```python
# ===== 正常流程 =====

def test_load_single_valid_task_yaml():
    """加载单个合法的 YAML 任务文件"""

def test_load_all_tasks_from_directory():
    """从目录加载所有 YAML 文件"""

def test_load_tasks_by_dimension():
    """按维度筛选任务"""

def test_load_task_by_id():
    """按 ID 加载单个任务"""

# ===== 校验 =====

def test_load_yaml_with_missing_required_field():
    """缺少必填字段时抛出 TaskLoadError"""

def test_load_yaml_with_invalid_difficulty():
    """difficulty 值非法时抛出 TaskLoadError"""

def test_load_yaml_with_duplicate_task_id():
    """task_id 重复时抛出 TaskLoadError"""

def test_load_yaml_with_empty_rubric():
    """rubric 为空时抛出 TaskLoadError"""

# ===== 默认值 =====

def test_load_yaml_without_mock_apis_defaults_empty():
    """未指定 mock_apis 时默认为空字典"""

def test_load_yaml_without_expected_tool_calls():
    """未指定 expected_tool_calls 时默认为空列表"""

# ===== 边界 =====

def test_load_empty_directory():
    """加载空目录时返回空列表"""

def test_load_nonexistent_task_id():
    """加载不存在的 task_id 时抛出 TaskNotFoundError"""

def test_load_nonexistent_directory():
    """加载不存在的目录时抛出 TaskLoadError"""

# ===== Fixture 准备 =====
# tests/fixtures/valid_task.yaml     — 合法的完整任务
# tests/fixtures/minimal_task.yaml   — 只有必填字段的任务
# tests/fixtures/missing_field.yaml  — 缺少必填字段
# tests/fixtures/invalid_diff.yaml   — difficulty 值非法
# tests/fixtures/duplicate_id/       — 两个相同 task_id 的 YAML
```

---

## 4. Sandbox 测试

### test_sandbox.py

```python
# ===== 正常流程 =====

async def test_execute_mocked_tool():
    """调用已配置的 Mock 工具，返回预设结果"""

async def test_execute_tool_with_params():
    """调用 Mock 工具时正确传递参数"""

async def test_execute_unmocked_tool():
    """调用未配置的工具时返回默认值 + warning"""

# ===== 调用记录 =====

async def test_call_log_records_all_calls():
    """get_call_log 返回所有调用记录"""

async def test_call_log_includes_timestamp():
    """调用记录包含时间戳"""

async def test_call_log_includes_params_and_result():
    """调用记录包含参数和结果"""

# ===== 重置 =====

async def test_reset_clears_call_log():
    """reset 后调用记录清空"""

async def test_reset_does_not_clear_mock_apis():
    """reset 不清除 mock_apis 配置"""

# ===== 边界 =====

async def test_execute_tool_with_empty_params():
    """参数为空字典时正常工作"""

async def test_execute_tool_returns_deep_copy():
    """返回的是深拷贝，修改不影响原始 mock_apis"""
```

---

## 5. Adapter 测试

### test_base_adapter.py

```python
def test_base_adapter_cannot_instantiate():
    """BaseAdapter 是抽象类，不能直接实例化"""

def test_base_adapter_subclass_must_implement_run_task():
    """子类必须实现 run_task 方法"""

def test_base_adapter_subclass_must_implement_get_agent_info():
    """子类必须实现 get_agent_info 方法"""
```

### test_raw_api_adapter.py

```python
# ===== 使用 mock httpx 测试 =====

async def test_raw_api_adapter_single_tool_call():
    """Agent 调用一次工具后返回结果"""

async def test_raw_api_adapter_multi_tool_call():
    """Agent 连续调用多个工具"""

async def test_raw_api_adapter_thinking_then_response():
    """Agent 先思考再回复"""

async def test_raw_api_adapter_timeout():
    """Agent 超时时抛出 AgentTimeoutError"""

async def test_raw_api_adapter_step_limit():
    """Agent 超步数时抛出 AgentStepLimitError"""

async def test_raw_api_adapter_api_error():
    """OpenAI API 返回错误时的处理"""

async def test_raw_api_adapter_get_agent_info():
    """返回正确的 Agent 元信息"""

# ===== 工具调用通过 Sandbox =====

async def test_adapter_uses_sandbox_for_tool_calls():
    """Agent 的工具调用必须通过 sandbox.execute_tool()"""

async def test_adapter_does_not_call_real_api():
    """Agent 不会真实调用外部 API"""
```

### test_langchain_adapter.py

```python
async def test_langchain_adapter_run_task():
    """基本任务执行"""

async def test_langchain_adapter_timeout():
    """超时处理"""

async def test_langchain_adapter_get_agent_info():
    """返回正确的 Agent 元信息"""
```

---

## 6. Scorer 测试

### test_scorer.py

```python
# ===== 单任务评分 =====

def test_score_task_all_pass():
    """所有评分项都通过，满分"""

def test_score_task_partial_pass():
    """部分评分项通过"""

def test_score_task_all_fail():
    """所有评分项都失败，0 分"""

def test_score_task_with_custom_eval_fn():
    """使用自定义评分函数"""

def test_score_task_with_empty_trace():
    """trace 为空（Agent 未执行）时安全处理"""

# ===== 批量评分 =====

def test_score_evaluation_pairs_traces_with_tasks():
    """traces 和 tasks 一一对应"""

def test_score_evaluation_length_mismatch():
    """traces 和 tasks 长度不一致时抛出 ScoringError"""

# ===== 维度汇总 =====

def test_aggregate_by_dimension():
    """按维度正确汇总"""

def test_aggregate_by_dimension_calculates_percentage():
    """百分比计算正确"""

# ===== 内置评分规则函数 =====

def test_check_tool_called_true():
    """Agent 确实调用了指定工具"""

def test_check_tool_called_false():
    """Agent 未调用指定工具"""

def test_check_tool_params_match():
    """工具参数匹配"""

def test_check_tool_params_partial_match():
    """工具参数部分匹配"""

def test_check_tool_call_sequence_correct():
    """工具调用顺序正确"""

def test_check_tool_call_sequence_wrong_order():
    """工具调用顺序错误"""

def test_check_no_extra_calls_true():
    """没有多余调用"""

def test_check_no_extra_calls_false():
    """有多余调用"""

def test_check_response_contains_keywords():
    """最终回复包含关键词"""

def test_check_response_format_json():
    """输出格式为 JSON"""

def test_check_step_count_within_range():
    """步骤数在范围内"""

def test_check_step_count_exceeds_range():
    """步骤数超出范围"""

def test_check_token_efficiency():
    """token 效率检查"""

def test_check_no_injection_safe():
    """未被 prompt 注入"""

def test_check_no_injection_compromised():
    """被 prompt 注入"""
```

---

## 7. EvalRunner 测试

### test_runner.py

```python
# ===== 单任务执行 =====

async def test_run_single_task_success():
    """正常完成单个任务"""

async def test_run_single_task_timeout():
    """任务超时，trace.success=False, trace.error 有值"""

async def test_run_single_task_step_limit():
    """超步数，trace.success=False, trace.error 有值"""

async def test_run_single_task_agent_error():
    """Agent 抛出异常，trace.error 有值"""

async def test_run_single_task_creates_sandbox():
    """每个任务都创建了独立的 Sandbox"""

# ===== 批量执行 =====

async def test_run_evaluation_sequential():
    """串行执行多个任务"""

async def test_run_evaluation_continues_on_error():
    """某个任务失败后继续执行下一个"""

async def test_run_evaluation_shows_progress():
    """执行过程显示进度"""

# ===== 重试 =====

async def test_run_single_task_retry_on_error():
    """retry_on_error=True 时，出错后重试一次"""

async def test_run_single_task_no_retry_by_default():
    """默认不重试"""
```

---

## 8. Reporter 测试

### test_reporter.py

```python
def test_print_table_output(capsys):
    """终端输出包含表格内容"""

def test_export_json_creates_file(tmp_path):
    """JSON 文件正确创建"""

def test_export_json_content_matches_result(tmp_path):
    """JSON 内容与 EvaluationResult 一致"""

def test_export_json_overwrites_existing(tmp_path):
    """覆盖已有文件"""
```

---

## 9. CLI 测试

### test_cli.py

```python
def test_cli_run_with_valid_args():
    """正常参数执行"""

def test_cli_run_with_invalid_agent():
    """无效的 agent 类型时报错"""

def test_cli_list_tasks():
    """list-tasks 输出所有任务"""

def test_cli_list_dimensions():
    """list-dimensions 输出所有维度"""

def test_cli_run_with_dimension_filter():
    """--dimension 参数过滤任务"""

def test_cli_run_with_task_filter():
    """--task 参数指定单个任务"""
```

---

## 10. 端到端测试

### test_e2e.py

```python
async def test_full_pipeline():
    """完整流程: YAML → TaskLoader → EvalRunner → Scorer → Reporter
    
    使用 MockAdapter（不调真实 API），验证整条链路跑通。
    """

async def test_full_pipeline_with_raw_api_adapter():
    """使用 RawAPIAdapter + mock httpx 的完整流程"""

async def test_full_pipeline_result_reproducible():
    """同一配置运行两次，结果一致（可复现性）"""
```

---

## 11. 测试覆盖率要求

| 模块 | 目标覆盖率 |
|------|-----------|
| models/ | ≥ 95% |
| loader/ | ≥ 90% |
| sandbox/ | ≥ 95% |
| adapters/ | ≥ 80%（集成测试为主） |
| scorer/ | ≥ 90% |
| runner/ | ≥ 85% |
| reporter/ | ≥ 80% |
| **总体** | **≥ 80%** |

---

## 12. 测试执行命令

```bash
# 运行所有测试
pytest tests/ -v

# 运行单个模块测试
pytest tests/test_scorer.py -v

# 运行并输出覆盖率
pytest tests/ --cov=src/agent_bench --cov-report=term-missing

# 只跑单元测试（排除 e2e）
pytest tests/ -v --ignore=tests/test_e2e.py

# 只跑 e2e 测试
pytest tests/test_e2e.py -v
```
