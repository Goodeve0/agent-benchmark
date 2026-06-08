import { useState, useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import {
  Card,
  Button,
  Select,
  Slider,
  Switch,
  Table,
  Tag,
  Progress,
  Space,
  Typography,
  Alert,
  Spin,
  Row,
  Col,
  message,
} from "antd";
import {
  PlayCircleOutlined,
  StopOutlined,
  ReloadOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
} from "@ant-design/icons";
import {
  getTasks,
  getConfigOptions,
  createRun,
  cancelRun,
  connectProgressWS,
  type TaskSummary,
  type EvalRunConfig,
  type EvalRunStatus,
} from "../api/client";

const { Text } = Typography;

export default function EvalPage() {
  const navigate = useNavigate();
  const wsRef = useRef<WebSocket | null>(null);

  // 配置
  const [adapterType, setAdapterType] = useState("mock");
  const [numTrials, setNumTrials] = useState(1);
  const [maxParallel, setMaxParallel] = useState(4);
  const [judgeMock, setJudgeMock] = useState(true);
  const [selectedTasks, setSelectedTasks] = useState<string[]>([]);
  const [configOptions, setConfigOptions] = useState<{
    adapter_types: string[];
    tasks: string[];
  }>({ adapter_types: [], tasks: [] });

  // 任务列表
  const [tasks, setTasks] = useState<TaskSummary[]>([]);

  // 运行状态
  const [runId, setRunId] = useState<string | null>(null);
  const [runStatus, setRunStatus] = useState<EvalRunStatus | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    loadData();
    return () => {
      wsRef.current?.close();
    };
  }, []);

  async function loadData() {
    try {
      const [tasksRes, optionsRes] = await Promise.all([getTasks(), getConfigOptions()]);
      setTasks(tasksRes.tasks);
      setConfigOptions({
        adapter_types: optionsRes.adapter_types,
        tasks: optionsRes.tasks,
      });
    } catch (e: any) {
      message.error("加载数据失败: " + e.message);
    }
  }

  async function handleStart() {
    setLoading(true);
    try {
      const config: EvalRunConfig = {
        adapter_type: adapterType,
        num_trials: numTrials,
        max_parallel: maxParallel,
        judge_mock: judgeMock,
        tasks: selectedTasks.length > 0 ? selectedTasks : [],
      };
      const res = await createRun(config);
      setRunId(res.run_id);
      setRunStatus({
        run_id: res.run_id,
        config,
        status: "running",
        progress: 0,
        current_task: "",
        completed_tasks: 0,
        total_tasks: 0,
        error: null,
        started_at: "",
        finished_at: "",
        has_result: false,
      });

      // 连接 WebSocket
      wsRef.current?.close();
      wsRef.current = connectProgressWS((data) => {
        setRunStatus(data);
        if (data.status === "completed") {
          message.success("评测完成！");
        } else if (data.status === "failed") {
          message.error("评测失败: " + (data.error || "未知错误"));
        }
      });
    } catch (e: any) {
      message.error("启动评测失败: " + e.message);
    } finally {
      setLoading(false);
    }
  }

  async function handleCancel() {
    if (!runId) return;
    try {
      await cancelRun(runId);
      message.info("评测已取消");
    } catch (e: any) {
      message.error("取消失败: " + e.message);
    }
  }

  function handleViewResult() {
    if (runId) {
      navigate(`/result/${runId}`);
    }
  }

  const isRunning = runStatus?.status === "running" || runStatus?.status === "pending";
  const isCompleted = runStatus?.status === "completed";
  const isFailed = runStatus?.status === "failed";

  // 任务列表表格列
  const taskColumns = [
    {
      title: "任务 ID",
      dataIndex: "task_id",
      key: "task_id",
      width: 160,
      render: (text: string) => <Text code>{text}</Text>,
    },
    {
      title: "维度",
      dataIndex: "dimension",
      key: "dimension",
      width: 120,
      render: (text: string) => <Tag color="blue">{text}</Tag>,
    },
    {
      title: "难度",
      dataIndex: "difficulty",
      key: "difficulty",
      width: 80,
      render: (text: string) => {
        const colorMap: Record<string, string> = { easy: "green", medium: "orange", hard: "red" };
        return <Tag color={colorMap[text] || "default"}>{text}</Tag>;
      },
    },
    {
      title: "模式",
      dataIndex: "mode",
      key: "mode",
      width: 100,
      render: (text: string) => (
        <Tag color={text === "multi_turn" ? "purple" : "cyan"}>
          {text === "multi_turn" ? "多轮" : "单轮"}
        </Tag>
      ),
    },
    {
      title: "满分",
      dataIndex: "max_score",
      key: "max_score",
      width: 80,
    },
    {
      title: "LLM Judge",
      dataIndex: "has_judge_rubric",
      key: "has_judge_rubric",
      width: 90,
      render: (v: boolean) =>
        v ? <CheckCircleOutlined style={{ color: "#a6e3a1" }} /> : <CloseCircleOutlined style={{ color: "#6c7086" }} />,
    },
    {
      title: "描述",
      dataIndex: "prompt_preview",
      key: "prompt_preview",
      ellipsis: true,
    },
  ];

  return (
    <div style={{ maxWidth: 1200, margin: "0 auto" }}>
      <Row gutter={24}>
        {/* 左侧：配置面板 */}
        <Col span={10}>
          <Card
            title="评测配置"
            style={{ background: "#1e1e2e", border: "1px solid #313244" }}
          >
            <Space direction="vertical" style={{ width: "100%" }} size="middle">
              <div>
                <Text style={{ color: "#cdd6f4" }}>Agent 类型</Text>
                <Select
                  value={adapterType}
                  onChange={setAdapterType}
                  style={{ width: "100%", marginTop: 4 }}
                  options={configOptions.adapter_types.map((t) => ({ value: t, label: t }))}
                />
              </div>

              <div>
                <Text style={{ color: "#cdd6f4" }}>Trial 次数 (Pass^k)</Text>
                <Slider
                  min={1}
                  max={10}
                  value={numTrials}
                  onChange={setNumTrials}
                  marks={{ 1: "1", 3: "3", 5: "5", 10: "10" }}
                />
              </div>

              <div>
                <Text style={{ color: "#cdd6f4" }}>最大并行数</Text>
                <Slider
                  min={1}
                  max={16}
                  value={maxParallel}
                  onChange={setMaxParallel}
                  marks={{ 1: "1", 4: "4", 8: "8", 16: "16" }}
                />
              </div>

              <div>
                <Space>
                  <Switch checked={judgeMock} onChange={setJudgeMock} />
                  <Text style={{ color: "#cdd6f4" }}>LLM Judge Mock 模式</Text>
                </Space>
              </div>

              <div>
                <Text style={{ color: "#cdd6f4" }}>
                  选择任务（空 = 全部，共 {tasks.length} 个）
                </Text>
                <Select
                  mode="multiple"
                  value={selectedTasks}
                  onChange={setSelectedTasks}
                  style={{ width: "100%", marginTop: 4 }}
                  placeholder="留空表示运行全部任务"
                  options={tasks.map((t) => ({
                    value: t.task_id,
                    label: `${t.task_id} (${t.dimension}/${t.difficulty})`,
                  }))}
                  maxTagCount={5}
                />
              </div>

              <Space style={{ width: "100%", justifyContent: "center", marginTop: 8 }}>
                {!isRunning && !isCompleted && !isFailed && (
                  <Button
                    type="primary"
                    icon={<PlayCircleOutlined />}
                    size="large"
                    loading={loading}
                    onClick={handleStart}
                    style={{ minWidth: 160 }}
                  >
                    开始评测
                  </Button>
                )}
                {isRunning && (
                  <>
                    <Spin />
                    <Text style={{ color: "#f9e2af" }}>评测进行中...</Text>
                    <Button
                      danger
                      icon={<StopOutlined />}
                      onClick={handleCancel}
                    >
                      取消
                    </Button>
                  </>
                )}
                {isCompleted && (
                  <Button
                    type="primary"
                    icon={<CheckCircleOutlined />}
                    size="large"
                    onClick={handleViewResult}
                    style={{ minWidth: 160 }}
                  >
                    查看结果
                  </Button>
                )}
                {(isCompleted || isFailed) && (
                  <Button
                    icon={<ReloadOutlined />}
                    onClick={() => {
                      setRunId(null);
                      setRunStatus(null);
                    }}
                  >
                    重新评测
                  </Button>
                )}
              </Space>
            </Space>
          </Card>

          {/* 进度卡片 */}
          {runStatus && (
            <Card
              title="评测进度"
              style={{ marginTop: 16, background: "#1e1e2e", border: "1px solid #313244" }}
            >
              <Progress
                percent={runStatus.progress}
                status={
                  isRunning ? "active" : isCompleted ? "success" : isFailed ? "exception" : "normal"
                }
                strokeColor="#6366f1"
              />
              <div style={{ marginTop: 12 }}>
                <Text style={{ color: "#a6adc8" }}>
                  已完成 {runStatus.completed_tasks} / {runStatus.total_tasks} 个任务
                </Text>
              </div>
              {runStatus.current_task && isRunning && (
                <div style={{ marginTop: 8 }}>
                  <Text style={{ color: "#cdd6f4" }}>
                    当前任务: <Text code>{runStatus.current_task}</Text>
                  </Text>
                </div>
              )}
              {isFailed && runStatus.error && (
                <Alert
                  type="error"
                  message={runStatus.error}
                  style={{ marginTop: 12 }}
                  showIcon
                />
              )}
            </Card>
          )}
        </Col>

        {/* 右侧：任务列表 */}
        <Col span={14}>
          <Card
            title={`任务列表 (${tasks.length})`}
            style={{ background: "#1e1e2e", border: "1px solid #313244" }}
          >
            <Table
              dataSource={tasks}
              columns={taskColumns}
              rowKey="task_id"
              size="small"
              pagination={{ pageSize: 8 }}
              scroll={{ y: 520 }}
              rowClassName={(record) =>
                selectedTasks.includes(record.task_id)
                  ? "ant-table-row-selected"
                  : ""
              }
            />
          </Card>
        </Col>
      </Row>
    </div>
  );
}
