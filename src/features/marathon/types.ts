// Marathon Autopilot — TypeScript types mirroring backend Pydantic models

export type SubTaskStatus = "todo" | "in_progress" | "completed" | "blocked" | "skipped";
export type MarathonStatus =
  | "planning"
  | "running"
  | "paused"
  | "completed"
  | "aborted"
  | "awaiting_clarification";
export type TaskComplexity = "trivial" | "low" | "medium" | "high" | "epic";

export interface MarathonSubTask {
  id: string;
  title: string;
  description: string;
  dependencies: string[];
  complexity: TaskComplexity;
  target_files: string[];
  target_modules: string[];
  status: SubTaskStatus;
  retry_count: number;
  max_retries: number;
  git_commit_hash: string | null;
  error_log: string[];
  started_at: number | null;
  completed_at: number | null;
  tokens_used: number;
  cost_usd: number;
}

export interface BudgetConfig {
  token_budget: number;
  time_budget_seconds: number;
  cost_budget_usd: number;
}

export interface BudgetUsage {
  tokens_used: number;
  cost_usd: number;
  elapsed_seconds: number;
  started_at: number;
}

export interface MarathonStateResponse {
  marathon_id: string;
  goal: string;
  status: MarathonStatus;
  tasks: MarathonSubTask[];
  budget: BudgetConfig;
  usage: BudgetUsage;
  progress_completed: number;
  progress_total: number;
  handoff_report: string | null;
  clarifying_question: string | null;
  created_at: number;
  updated_at: number;
}

export interface StartMarathonRequest {
  goal: string;
  workspace: string;
  budget: BudgetConfig;
  provider_config: Record<string, string>;
  clarifying_answer?: string;
}

export interface MarathonSSEEvent {
  marathon_id: string;
  status: MarathonStatus;
  progress_completed: number;
  progress_total: number;
  tokens_used: number;
  cost_usd: number;
  elapsed_seconds: number;
  event: string;
  task_id?: string;
  title?: string;
  commit_hash?: string;
  reason?: string;
  resume_context?: string;
}
