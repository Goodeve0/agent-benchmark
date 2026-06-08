/**
 * AgentBench API 客户端
 */

const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000/api/v1";
const WS_BASE = import.meta.env.VITE_WS_BASE || "ws://localhost:8000/ws";

export interface TaskSummary {
  task_id: string;
  dimension: string;
  sub_dimension: string;
  difficulty: string;
  mode: "single_turn" | "multi_turn";
  prompt_preview: string;
  max_score: number;
  has_judge_rubric: boolean;
  is_multi_turn: boolean;
  num_tools: number;
}

export interface EvalRunConfig {
  adapter_type?: string;
  num_trials?: number;
  max_parallel?: number;
  judge_mock?: boolean;
  tasks?: string[];
}

export interface EvalRunStatus {
  run_id: string;
  config: EvalRunConfig;
  status: "pending" | "running" | "completed" | "failed" | "cancelled";
  progress: number;
  current_task: string;
  completed_tasks: number;
  total_tasks: number;
  error: string | null;
  started_at: string;
  finished_at: string;
  has_result: boolean;
}

export interface ScoreDetail {
  rubric_name: string;
  points: number;
  max_points: number;
  passed: boolean;
  reason: string;
  judge_type: "rule" | "llm_judge";
}

export interface ScoreReport {
  task_id: string;
  dimension: string;
  sub_dimension: string;
  difficulty: string;
  scores: ScoreDetail[];
  total_score: number;
  max_score: number;
  percentage: number;
  passed: boolean;
}

export interface TaskTrials {
  task_id: string;
  dimension: string;
  sub_dimension: string;
  difficulty: string;
  trials: {
    trial_id: number;
    report: ScoreReport;
  }[];
  num_trials: number;
  mean_score: number;
  score_variance: number;
  pass_rate: number;
  pass_k: boolean;
}

export interface OrthogonalScore {
  dimension: "completion" | "safety" | "robustness";
  score: number;
  max_score: number;
  percentage: number;
  description: string;
}

export interface DimensionScore {
  dimension: string;
  score: number;
  max_score: number;
  percentage: number;
  task_count: number;
}

export interface EvaluationResult {
  agent_name: string;
  agent_model: string;
  timestamp: string;
  num_trials: number;
  task_trials: TaskTrials[];
  task_reports: ScoreReport[];
  dimension_scores: DimensionScore[];
  orthogonal_scores: OrthogonalScore[];
  overall_score: number;
  overall_max_score: number;
  overall_percentage: number;
  overall_pass_k_rate: number;
}

export interface LeaderboardEntry {
  run_id: string;
  agent_name: string;
  agent_model: string;
  timestamp: string;
  num_trials: number;
  overall_percentage: number;
  overall_pass_k_rate: number;
  orthogonal_scores: {
    dimension: string;
    percentage: number;
  }[];
  rank: number;
}

export interface ConfigOptions {
  adapter_types: string[];
  tasks: string[];
  num_trials_range: { min: number; max: number; default: number };
  max_parallel_range: { min: number; max: number; default: number };
}

// ---- REST API ----

async function fetchAPI<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || `API Error: ${res.status}`);
  }
  return res.json();
}

export async function getTasks(): Promise<{ tasks: TaskSummary[]; total: number }> {
  return fetchAPI("/tasks");
}

export async function getTaskDetail(taskId: string): Promise<any> {
  return fetchAPI(`/tasks/${taskId}`);
}

export async function createRun(config: EvalRunConfig): Promise<{ run_id: string; status: string }> {
  return fetchAPI("/runs", {
    method: "POST",
    body: JSON.stringify(config),
  });
}

export async function getRunStatus(runId: string): Promise<EvalRunStatus> {
  return fetchAPI(`/runs/${runId}`);
}

export async function getRunResult(runId: string): Promise<EvaluationResult> {
  return fetchAPI(`/runs/${runId}/result`);
}

export async function cancelRun(runId: string): Promise<{ run_id: string; status: string }> {
  return fetchAPI(`/runs/${runId}/cancel`, { method: "POST" });
}

export async function getLeaderboard(): Promise<{ leaderboard: LeaderboardEntry[] }> {
  return fetchAPI("/leaderboard");
}

export async function getConfigOptions(): Promise<ConfigOptions> {
  return fetchAPI("/config/options");
}

// ---- WebSocket ----

export type ProgressCallback = (data: EvalRunStatus) => void;

export function connectProgressWS(onProgress: ProgressCallback): WebSocket {
  const ws = new WebSocket(WS_BASE);
  ws.onmessage = (event) => {
    try {
      const msg = JSON.parse(event.data);
      if (msg.type === "progress") {
        onProgress(msg.data);
      }
    } catch {
      // ignore non-JSON messages (pong etc.)
    }
  };
  ws.onclose = () => {
    // Auto-reconnect after 3s
    setTimeout(() => connectProgressWS(onProgress), 3000);
  };
  // Heartbeat
  const heartbeat = setInterval(() => {
    if (ws.readyState === WebSocket.OPEN) {
      ws.send("ping");
    }
  }, 30000);
  ws.addEventListener("close", () => clearInterval(heartbeat));
  return ws;
}
