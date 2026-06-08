import { useState, useEffect } from "react";
import { useParams, useNavigate } from "react-router-dom";
import {
  Card,
  Table,
  Tag,
  Typography,
  Row,
  Col,
  Spin,
  Alert,
  Statistic,
  Space,
  Button,
  Progress,
} from "antd";
import {
  ArrowLeftOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  SafetyOutlined,
  ThunderboltOutlined,
  ExperimentOutlined,
} from "@ant-design/icons";
import {
  RadarChart,
  PolarGrid,
  PolarAngleAxis,
  PolarRadiusAxis,
  Radar,
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Cell,
} from "recharts";
import { getRunResult, type EvaluationResult } from "../api/client";

const { Title, Text } = Typography;

const ORTHOGONAL_LABELS: Record<string, string> = {
  completion: "Completion 任务完成度",
  safety: "Safety 安全性",
  robustness: "Robustness 鲁棒性",
};

const ORTHOGONAL_COLORS: Record<string, string> = {
  completion: "#a6e3a1",
  safety: "#f38ba8",
  robustness: "#89b4fa",
};

export default function ResultPage() {
  const { runId } = useParams<{ runId: string }>();
  const navigate = useNavigate();
  const [result, setResult] = useState<EvaluationResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!runId) return;
    loadResult();
  }, [runId]);

  async function loadResult() {
    setLoading(true);
    setError(null);
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
        <Button
          icon={<ArrowLeftOutlined />}
          onClick={() => navigate("/")}
          style={{ marginTop: 16 }}
        >
          返回评测页
        </Button>
      </div>
    );
  }

  // 雷达图数据
  const radarData = result.orthogonal_scores.map((o) => ({
    dimension: ORTHOGONAL_LABELS[o.dimension] || o.dimension,
    score: o.percentage,
    fullMark: 100,
  }));

  // 细分维度柱状图数据
  const dimBarData = result.dimension_scores.map((d) => ({
    name: d.dimension,
    得分率: d.percentage,
    任务数: d.task_count,
  }));

  // 任务明细表格
  const hasTrials = result.num_trials > 1 && result.task_trials.length > 0;

  const taskColumns: any[] = [
    {
      title: "任务 ID",
      dataIndex: "task_id",
      key: "task_id",
      width: 150,
      render: (text: string) => <Text code>{text}</Text>,
    },
    {
      title: "维度",
      dataIndex: "dimension",
      key: "dimension",
      width: 100,
      render: (text: string) => <Tag color="blue">{text}</Tag>,
    },
    {
      title: "难度",
      dataIndex: "difficulty",
      key: "difficulty",
      width: 70,
      render: (text: string) => {
        const colorMap: Record<string, string> = { easy: "green", medium: "orange", hard: "red" };
        return <Tag color={colorMap[text]}>{text}</Tag>;
      },
    },
    {
      title: "得分",
      dataIndex: hasTrials ? undefined : "total_score",
      key: "score",
      width: 70,
      render: (_: any, record: any) => {
        const score = hasTrials ? record.trials?.[0]?.report?.total_score : record.total_score;
        return <Text>{score ?? "-"}</Text>;
      },
    },
    {
      title: "满分",
      dataIndex: "max_score",
      key: "max_score",
      width: 70,
    },
    {
      title: "得分率",
      key: "percentage",
      width: 120,
      render: (_: any, record: any) => {
        const pct = hasTrials ? record.mean_score : record.percentage;
        return (
          <Progress
            percent={pct}
            size="small"
            strokeColor={pct >= 80 ? "#a6e3a1" : pct >= 50 ? "#f9e2af" : "#f38ba8"}
          />
        );
      },
    },
  ];

  if (hasTrials) {
    taskColumns.push(
      {
        title: "Pass^k",
        key: "pass_k",
        width: 80,
        render: (_: any, record: any) =>
          record.pass_k ? (
            <CheckCircleOutlined style={{ color: "#a6e3a1", fontSize: 18 }} />
          ) : (
            <CloseCircleOutlined style={{ color: "#f38ba8", fontSize: 18 }} />
          ),
      },
      {
        title: "通过率",
        key: "pass_rate",
        width: 80,
        render: (_: any, record: any) => `${(record.pass_rate * 100).toFixed(0)}%`,
      },
      {
        title: "方差",
        key: "variance",
        width: 80,
        render: (_: any, record: any) => record.score_variance?.toFixed(4) ?? "-",
      }
    );
  }

  const taskData: readonly any[] = hasTrials ? result.task_trials : result.task_reports;

  return (
    <div style={{ maxWidth: 1200, margin: "0 auto" }}>
      {/* 顶部概览 */}
      <Card style={{ marginBottom: 16, background: "#1e1e2e", border: "1px solid #313244" }}>
        <Row gutter={16} align="middle">
          <Col>
            <Button icon={<ArrowLeftOutlined />} onClick={() => navigate("/")} />
          </Col>
          <Col flex="auto">
            <Title level={4} style={{ margin: 0, color: "#cdd6f4" }}>
              评测结果 — {result.agent_name} ({result.agent_model})
            </Title>
          </Col>
        </Row>
        <Row gutter={24} style={{ marginTop: 16 }}>
          <Col span={6}>
            <Statistic
              title={<span style={{ color: "#a6adc8" }}>总分</span>}
              value={result.overall_percentage}
              suffix="%"
              valueStyle={{ color: "#6366f1", fontSize: 32 }}
            />
          </Col>
          <Col span={6}>
            <Statistic
              title={<span style={{ color: "#a6adc8" }}>原始分</span>}
              value={`${result.overall_score} / ${result.overall_max_score}`}
              valueStyle={{ color: "#cdd6f4" }}
            />
          </Col>
          <Col span={6}>
            <Statistic
              title={<span style={{ color: "#a6adc8" }}>Trials</span>}
              value={result.num_trials}
              valueStyle={{ color: "#cdd6f4" }}
            />
          </Col>
          {result.num_trials > 1 && (
            <Col span={6}>
              <Statistic
                title={<span style={{ color: "#a6adc8" }}>Pass^k 通过率</span>}
                value={(result.overall_pass_k_rate * 100).toFixed(1)}
                suffix="%"
                valueStyle={{
                  color: result.overall_pass_k_rate >= 0.8 ? "#a6e3a1" : "#f38ba8",
                  fontSize: 28,
                }}
              />
            </Col>
          )}
        </Row>
      </Card>

      <Row gutter={16}>
        {/* 三正交维度雷达图 */}
        <Col span={12}>
          <Card
            title="三正交维度"
            style={{ background: "#1e1e2e", border: "1px solid #313244" }}
          >
            <ResponsiveContainer width="100%" height={320}>
              <RadarChart data={radarData}>
                <PolarGrid stroke="#45475a" />
                <PolarAngleAxis dataKey="dimension" tick={{ fill: "#cdd6f4", fontSize: 12 }} />
                <PolarRadiusAxis angle={30} domain={[0, 100]} tick={{ fill: "#6c7086" }} />
                <Radar
                  name="得分率"
                  dataKey="score"
                  stroke="#6366f1"
                  fill="#6366f1"
                  fillOpacity={0.3}
                />
              </RadarChart>
            </ResponsiveContainer>
            <Row justify="space-around" style={{ marginTop: 8 }}>
              {result.orthogonal_scores.map((o) => (
                <Space key={o.dimension} direction="vertical" align="center">
                  {o.dimension === "completion" && <ThunderboltOutlined style={{ fontSize: 20, color: ORTHOGONAL_COLORS[o.dimension] }} />}
                  {o.dimension === "safety" && <SafetyOutlined style={{ fontSize: 20, color: ORTHOGONAL_COLORS[o.dimension] }} />}
                  {o.dimension === "robustness" && <ExperimentOutlined style={{ fontSize: 20, color: ORTHOGONAL_COLORS[o.dimension] }} />}
                  <Text style={{ color: ORTHOGONAL_COLORS[o.dimension], fontSize: 18, fontWeight: 600 }}>
                    {o.percentage}%
                  </Text>
                  <Text style={{ color: "#6c7086", fontSize: 12 }}>{o.dimension}</Text>
                </Space>
              ))}
            </Row>
          </Card>
        </Col>

        {/* 细分维度柱状图 */}
        <Col span={12}>
          <Card
            title="细分维度得分"
            style={{ background: "#1e1e2e", border: "1px solid #313244" }}
          >
            <ResponsiveContainer width="100%" height={320}>
              <BarChart data={dimBarData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#313244" />
                <XAxis dataKey="name" tick={{ fill: "#cdd6f4", fontSize: 11 }} />
                <YAxis domain={[0, 100]} tick={{ fill: "#6c7086" }} />
                <Tooltip
                  contentStyle={{ background: "#1e1e2e", border: "1px solid #313244", color: "#cdd6f4" }}
                />
                <Bar dataKey="得分率" radius={[4, 4, 0, 0]}>
                  {dimBarData.map((entry, index) => (
                    <Cell
                      key={index}
                      fill={
                        entry.得分率 >= 80
                          ? "#a6e3a1"
                          : entry.得分率 >= 50
                          ? "#f9e2af"
                          : "#f38ba8"
                      }
                    />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </Card>
        </Col>
      </Row>

      {/* 任务明细表 */}
      <Card
        title="任务明细"
        style={{ marginTop: 16, background: "#1e1e2e", border: "1px solid #313244" }}
      >
        <Table
          dataSource={taskData}
          columns={taskColumns}
          rowKey="task_id"
          size="small"
          pagination={{ pageSize: 10 }}
        />
      </Card>
    </div>
  );
}
