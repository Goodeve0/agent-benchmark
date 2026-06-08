import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { ConfigProvider, theme } from "antd";
import MainLayout from "./components/MainLayout";
import EvalPage from "./pages/EvalPage";
import ResultPage from "./pages/ResultPage";
import LeaderboardPage from "./pages/LeaderboardPage";
import TrajectoryPage from "./pages/TrajectoryPage";

function App() {
  return (
    <ConfigProvider
      theme={{
        algorithm: theme.darkAlgorithm,
        token: {
          colorPrimary: "#6366f1",
          borderRadius: 8,
          colorBgContainer: "#1e1e2e",
          colorBgElevated: "#262637",
        },
      }}
    >
      <BrowserRouter>
        <MainLayout>
          <Routes>
            <Route path="/" element={<EvalPage />} />
            <Route path="/result/:runId" element={<ResultPage />} />
            <Route path="/leaderboard" element={<LeaderboardPage />} />
            <Route path="/trajectory/:runId" element={<TrajectoryPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </MainLayout>
      </BrowserRouter>
    </ConfigProvider>
  );
}

export default App;
