import type { ReactNode } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { Layout, Menu, Typography } from "antd";
import {
  PlayCircleOutlined,
  TrophyOutlined,
  ApartmentOutlined,
  LineChartOutlined,
} from "@ant-design/icons";

const { Header, Content, Footer } = Layout;
const { Title } = Typography;

const menuItems = [
  { key: "/", icon: <PlayCircleOutlined />, label: "评测" },
  { key: "/leaderboard", icon: <TrophyOutlined />, label: "排行榜" },
];

interface MainLayoutProps {
  children: ReactNode;
}

export default function MainLayout({ children }: MainLayoutProps) {
  const location = useLocation();
  const navigate = useNavigate();

  // 激活菜单项：如果是 /result 或 /trajectory 子路径，高亮评测
  const activeKey = location.pathname.startsWith("/leaderboard")
    ? "/leaderboard"
    : "/";

  return (
    <Layout style={{ minHeight: "100vh" }}>
      <Header
        style={{
          display: "flex",
          alignItems: "center",
          padding: "0 24px",
          background: "#181825",
          borderBottom: "1px solid #313244",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginRight: 40 }}>
          <LineChartOutlined style={{ fontSize: 22, color: "#6366f1" }} />
          <Title level={4} style={{ margin: 0, color: "#cdd6f4" }}>
            AgentBench
          </Title>
        </div>
        <Menu
          theme="dark"
          mode="horizontal"
          selectedKeys={[activeKey]}
          items={menuItems}
          onClick={({ key }) => navigate(key)}
          style={{ flex: 1, background: "transparent", borderBottom: "none" }}
        />
        <div style={{ display: "flex", alignItems: "center", gap: 8, color: "#6c7086" }}>
          <ApartmentOutlined />
          <span style={{ fontSize: 12 }}>Agent 行为评测框架</span>
        </div>
      </Header>
      <Content style={{ padding: "24px 32px", background: "#11111b" }}>
        {children}
      </Content>
      <Footer style={{ textAlign: "center", background: "#181825", color: "#6c7086" }}>
        AgentBench ©2026 — Completion · Safety · Robustness
      </Footer>
    </Layout>
  );
}
