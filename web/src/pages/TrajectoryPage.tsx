import { useState, useEffect } from "react";
import { useParams, useNavigate } from "react-router-dom";
import {
  Card,
  Typography,
  Spin,
  Alert,
  Button,
  Tabs,
  Tag,
  Timeline,
  Space,
  Descriptions,
} from "antd";
import {
  ArrowLeftOutlined,
  RobotOutlined,
  HistoryOutlined,
} from "@ant-design/icons";
import { getRunResult, type EvaluationResult, type TaskTrials } from "../api/client";

const { Title, Text } = Typography;

export default function TrajectoryPage() {
  const { runId } = useParams<{ runId: string }>();
  const navigate = useNavigate();
  const [result, setResult] = useState<EvaluationResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!runId) return;
    loadData();
  }, [runId]);

  async function loadData() {
    setLoading(true);
    try {
      const res = await getRunResult(runId!);
      setResult(res);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  if (loading) {
    return (
      <div style={{ textAlign: "center", padding: 100 }}>
        <Spin size="large" />
      </div>
    );
  }

  if (error || !result) {
    return (
      <div style={{ maxWidth: 600, margin: "0 auto" }}>
        <Alert type="error" message={error || "结果不存在"} showIcon />
        <Button icon={<ArrowLeftOutlined />} onClick={() => navigate("/")} style={{ marginTop: 16 }}>
          返回
        </Button>
      </div>
    );
  }

  // 筛选有轨迹数据的任务
  const tasksWithTrials = result.task_trials.filter(
    (tt) => tt.trials?.length > 0
  );

  const tabItems = tasksWithTrials.map((tt) => ({
    key: tt.task_id,
    label: (
      <Space>
        <Text>{tt.task_id}</Text>
        <Tag color={tt.pass_k !== undefined ? (tt.pass_k ? "green" : "red") : "default"}>
          {tt.mean_score?.toFixed(1) ?? "-"}%
        </Tag>
      </Space>
    ),
    children: <TaskTrajectoryDetail taskTrials={tt} />,
  }));

  return (
    <div style={{ maxWidth: 1000, margin: "0 auto" }}>
      <Card style={{ marginBottom: 16, background: "#1e1e2e", border: "1px solid #313244" }}>
        <Space>
          <Button icon={<ArrowLeftOutlined />} onClick={() => navigate(-1)} />
          <Title level={4} style={{ margin: 0, color: "#cdd6f4" }}>
            <HistoryOutlined /> 对话轨迹回放
          </Title>
        </Space>
      </Card>

      {tabItems.length > 0 ? (
        <Card style={{ background: "#1e1e2e", border: "1px solid #313244" }}>
          <Tabs items={tabItems} />
        </Card>
      ) : (
        <Card style={{ background: "#1e1e2e", border: "1px solid #313244" }}>
          <div style={{ textAlign: "center", padding: 40 }}>
            <HistoryOutlined style={{ fontSize: 48, color: "#313244" }} />
            <Title level={4} style={{ color: "#6c7086", marginTop: 16 }}>
              暂无轨迹数据
            </Title>
            <Text style={{ color: "#6c7086" }}>轨迹数据在评测结果中不可用</Text>
          </div>
        </Card>
      )}
    </div>
  );
}

/** 单个任务的轨迹详情 */
function TaskTrajectoryDetail({ taskTrials }: { taskTrials: TaskTrials }) {
  const trial = taskTrials.trials[0];
  if (!trial) return <Text style={{ color: "#6c7086" }}>无数据</Text>;

  const report = trial.report;

  return (
    <div>
      {/* 评分详情 */}
      <Descriptions
        bordered
        size="small"
        column={2}
        style={{ marginBottom: 16 }}
        labelStyle={{ color: "#a6adc8", background: "#262637" }}
        contentStyle={{ color: "#cdd6f4", background: "#1e1e2e" }}
      >
        <Descriptions.Item label="维度">{taskTrials.dimension}</Descriptions.Item>
        <Descriptions.Item label="难度">{taskTrials.difficulty}</Descriptions.Item>
        <Descriptions.Item label="得分">
          <Text style={{ color: report.percentage >= 80 ? "#a6e3a1" : report.percentage >= 50 ? "#f9e2af" : "#f38ba8", fontWeight: 700 }}>
            {report.total_score} / {report.max_score} ({report.percentage}%)
          </Text>
        </Descriptions.Item>
        {taskTrials.num_trials > 1 && (
          <>
            <Descriptions.Item label="Pass^k">
              {taskTrials.pass_k ? (
                <Tag color="green">✓ Pass</Tag>
              ) : (
                <Tag color="red">✗ Fail</Tag>
              )}
            </Descriptions.Item>
            <Descriptions.Item label="通过率">
              {(taskTrials.pass_rate * 100).toFixed(0)}%
            </Descriptions.Item>
          </>
        )}
      </Descriptions>

      {/* 评分项详情 */}
      <Title level={5} style={{ color: "#cdd6f4" }}>评分项详情</Title>
      <Timeline
        items={report.scores.map((s, i) => ({
          color: s.passed ? "green" : "red",
          dot: s.passed ? (
            <RobotOutlined style={{ fontSize: 14, color: "#a6e3a1" }} />
          ) : (
            <RobotOutlined style={{ fontSize: 14, color: "#f38ba8" }} />
          ),
          children: (
            <div key={i}>
              <Space>
                <Text style={{ color: "#cdd6f4", fontWeight: 600 }}>{s.rubric_name}</Text>
                <Tag color={s.judge_type === "llm_judge" ? "purple" : "blue"}>
                  {s.judge_type === "llm_judge" ? "LLM Judge" : "规则引擎"}
                </Tag>
                <Text style={{ color: s.passed ? "#a6e3a1" : "#f38ba8" }}>
                  {s.points}/{s.max_points}
                </Text>
              </Space>
              <br />
              <Text style={{ color: "#6c7086", fontSize: 12 }}>{s.reason}</Text>
            </div>
          ),
        }))}
      />
    </div>
  );
}
