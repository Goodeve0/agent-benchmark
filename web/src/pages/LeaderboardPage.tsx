import { useState, useEffect } from "react";
import { Card, Table, Tag, Typography, Space, Button, Row, Col } from "antd";
import { TrophyOutlined, ReloadOutlined, CrownOutlined } from "@ant-design/icons";
import {
  RadarChart,
  PolarGrid,
  PolarAngleAxis,
  PolarRadiusAxis,
  Radar,
  ResponsiveContainer,
  Legend,
  Tooltip,
} from "recharts";
import { getLeaderboard, type LeaderboardEntry } from "../api/client";

const { Title, Text } = Typography;

const DIMENSION_LABELS: Record<string, string> = {
  tool_use: "工具使用",
  reasoning: "推理能力",
  memory: "记忆能力",
  instruction_following: "指令遵循",
  efficiency: "执行效率",
  safety: "安全性",
  multi_agent: "多Agent协作",
};

const AGENT_COLORS = [
  "#6366f1", "#a6e3a1", "#f38ba8", "#89b4fa", "#f9e2af", "#fab387",
];

export default function LeaderboardPage() {
  const [leaderboard, setLeaderboard] = useState<LeaderboardEntry[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    loadLeaderboard();
  }, []);

  async function loadLeaderboard() {
    setLoading(true);
    try {
      const res = await getLeaderboard();
      setLeaderboard(res.leaderboard);
    } catch {
      // 可能还没有数据
    } finally {
      setLoading(false);
    }
  }

  // 构建雷达图数据：每个维度一行，每个 Agent 一列
  const radarData = buildRadarData(leaderboard);

  const columns = [
    {
      title: "排名",
      dataIndex: "rank",
      key: "rank",
      width: 70,
      render: (rank: number) => {
        if (rank === 1) return <CrownOutlined style={{ color: "#f9e2af", fontSize: 20 }} />;
        if (rank === 2) return <CrownOutlined style={{ color: "#a6adc8", fontSize: 18 }} />;
        if (rank === 3) return <CrownOutlined style={{ color: "#fab387", fontSize: 16 }} />;
        return <Text style={{ color: "#6c7086" }}>#{rank}</Text>;
      },
    },
    {
      title: "Agent",
      dataIndex: "agent_name",
      key: "agent_name",
      render: (text: string, record: LeaderboardEntry) => (
        <Space direction="vertical" size={0}>
          <Text style={{ color: "#cdd6f4", fontWeight: 600 }}>{text}</Text>
          <Text style={{ color: "#6c7086", fontSize: 12 }}>{record.agent_model}</Text>
        </Space>
      ),
    },
    {
      title: "总分",
      dataIndex: "overall_percentage",
      key: "overall_percentage",
      width: 100,
      sorter: (a: LeaderboardEntry, b: LeaderboardEntry) => a.overall_percentage - b.overall_percentage,
      render: (val: number) => (
        <Text
          style={{
            fontWeight: 700,
            fontSize: 16,
            color: val >= 80 ? "#a6e3a1" : val >= 50 ? "#f9e2af" : "#f38ba8",
          }}
        >
          {val}%
        </Text>
      ),
    },
    {
      title: "Completion",
      key: "completion",
      width: 100,
      render: (_: any, record: LeaderboardEntry) => {
        const o = record.orthogonal_scores?.find((s) => s.dimension === "completion");
        return o ? <Tag color="green">{o.percentage}%</Tag> : <Tag>-</Tag>;
      },
    },
    {
      title: "Safety",
      key: "safety",
      width: 100,
      render: (_: any, record: LeaderboardEntry) => {
        const o = record.orthogonal_scores?.find((s) => s.dimension === "safety");
        return o ? <Tag color="red">{o.percentage}%</Tag> : <Tag>-</Tag>;
      },
    },
    {
      title: "Robustness",
      key: "robustness",
      width: 100,
      render: (_: any, record: LeaderboardEntry) => {
        const o = record.orthogonal_scores?.find((s) => s.dimension === "robustness");
        return o ? <Tag color="blue">{o.percentage}%</Tag> : <Tag>-</Tag>;
      },
    },
    {
      title: "Trials",
      dataIndex: "num_trials",
      key: "num_trials",
      width: 70,
    },
    {
      title: "Pass^k",
      dataIndex: "overall_pass_k_rate",
      key: "overall_pass_k_rate",
      width: 80,
      render: (val: number) => `${(val * 100).toFixed(0)}%`,
    },
    {
      title: "时间",
      dataIndex: "timestamp",
      key: "timestamp",
      width: 140,
      render: (text: string) => {
        try {
          return new Date(text).toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
        } catch {
          return text;
        }
      },
    },
  ];

  return (
    <div style={{ maxWidth: 1200, margin: "0 auto" }}>
      <Row gutter={24}>
        <Col span={14}>
          <Card
            title={
              <Space>
                <TrophyOutlined style={{ color: "#f9e2af" }} />
                <span>模型排行榜</span>
              </Space>
            }
            extra={
              <Button icon={<ReloadOutlined />} onClick={loadLeaderboard} loading={loading}>
                刷新
              </Button>
            }
            style={{ background: "#1e1e2e", border: "1px solid #313244" }}
          >
            {leaderboard.length === 0 && !loading ? (
              <div style={{ textAlign: "center", padding: 40 }}>
                <TrophyOutlined style={{ fontSize: 48, color: "#313244" }} />
                <Title level={4} style={{ color: "#6c7086", marginTop: 16 }}>
                  暂无评测数据
                </Title>
                <Text style={{ color: "#6c7086" }}>运行评测后，结果将自动出现在排行榜中</Text>
              </div>
            ) : (
              <Table
                dataSource={leaderboard}
                columns={columns}
                rowKey="run_id"
                pagination={false}
                loading={loading}
              />
            )}
          </Card>
        </Col>

        <Col span={10}>
          <Card
            title={
              <Space>
                <span>多 Agent 维度对比</span>
              </Space>
            }
            style={{ background: "#1e1e2e", border: "1px solid #313244" }}
          >
            {radarData.length > 0 ? (
              <ResponsiveContainer width="100%" height={400}>
                <RadarChart data={radarData}>
                  <PolarGrid stroke="#313244" />
                  <PolarAngleAxis
                    dataKey="dimension"
                    tick={{ fill: "#cdd6f4", fontSize: 12 }}
                  />
                  <PolarRadiusAxis
                    angle={90}
                    domain={[0, 100]}
                    tick={{ fill: "#6c7086", fontSize: 10 }}
                  />
                  {leaderboard.slice(0, 6).map((entry, idx) => (
                    <Radar
                      key={entry.run_id}
                      name={entry.agent_name}
                      dataKey={entry.agent_name}
                      stroke={AGENT_COLORS[idx]}
                      fill={AGENT_COLORS[idx]}
                      fillOpacity={0.15}
                      strokeWidth={2}
                    />
                  ))}
                  <Legend
                    wrapperStyle={{ color: "#cdd6f4" }}
                  />
                  <Tooltip
                    contentStyle={{
                      background: "#262637",
                      border: "1px solid #313244",
                      borderRadius: 8,
                      color: "#cdd6f4",
                    }}
                  />
                </RadarChart>
              </ResponsiveContainer>
            ) : (
              <div style={{ textAlign: "center", padding: 40 }}>
                <Text style={{ color: "#6c7086" }}>运行多个 Agent 评测后，将展示维度对比雷达图</Text>
              </div>
            )}
          </Card>
        </Col>
      </Row>
    </div>
  );
}

/** 构建雷达图数据 */
function buildRadarData(entries: LeaderboardEntry[]) {
  if (entries.length === 0) return [];

  // 收集所有维度
  const dimSet = new Set<string>();
  entries.forEach((e) => {
    e.orthogonal_scores?.forEach((s) => dimSet.add(s.dimension));
  });

  // 每个维度一行
  return Array.from(dimSet).map((dim) => {
    const row: Record<string, string | number> = {
      dimension: DIMENSION_LABELS[dim] || dim,
    };
    entries.forEach((e) => {
      const score = e.orthogonal_scores?.find((s) => s.dimension === dim);
      row[e.agent_name] = score?.percentage ?? 0;
    });
    return row;
  });
}
