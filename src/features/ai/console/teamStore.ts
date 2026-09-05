import { create } from "zustand";
import { api } from "../../../lib/api";

export type TeamRole =
  | "architect"
  | "coder"
  | "reviewer"
  | "tester"
  | "devops"
  | "operator"
  | "system";

export type TaskStatus =
  | "pending"
  | "queued"
  | "running"
  | "completed"
  | "failed"
  | "cancelled"
  | "waiting";

export interface TeamTask {
  id: string;
  job_id: string;
  title: string;
  assigned_agent: TeamRole | string;
  dependencies: string[];
  status: TaskStatus;
  started_at?: number | null;
  completed_at?: number | null;
  duration_seconds?: number | null;
  errors?: string | null;
  payload?: any;
}

export interface TeamMessage {
  id?: number;
  job_id: string;
  task_id?: string | null;
  sender_role: TeamRole | string;
  recipient_role: TeamRole | string;
  message_type: string;
  content: string;
  artifact?: any;
  artifact_json?: string | null;
  token_usage?: number;
  cost_usd?: number;
  acknowledged?: boolean;
  details?: Record<string, any> | null;
  timestamp: number;
}

export interface HandoffArtifact {
  type: string;
  from_role: string;
  to_role: string;
  task_id?: string | null;
  payload?: any;
  summary: string;
  created_at?: number;
}

export interface AgentMetric {
  total_tokens: number;
  input_tokens: number;
  output_tokens: number;
  total_cost: number;
  message_count: number;
}

export interface TeamConfig {
  id?: string;
  workspace?: string;
  name?: string;
  architect_model: string;
  architect_provider: string;
  coder_model: string;
  coder_provider: string;
  reviewer_model: string;
  reviewer_provider: string;
  tester_model: string;
  tester_provider: string;
  devops_model: string;
  devops_provider: string;
  max_repair_rounds: number;
  max_concurrency: number;
  auto_verify: boolean;
}

export const DEFAULT_TEAM_CONFIG: TeamConfig = {
  name: "Autonomous Engineering Team",
  architect_model: "gpt-4o",
  architect_provider: "openai",
  coder_model: "claude-3-5-sonnet-latest",
  coder_provider: "anthropic",
  reviewer_model: "gpt-4o",
  reviewer_provider: "openai",
  tester_model: "llama-3.3-70b-versatile",
  tester_provider: "groq",
  devops_model: "llama-3.1-8b-instant",
  devops_provider: "groq",
  max_repair_rounds: 3,
  max_concurrency: 3,
  auto_verify: true,
};

export interface FinalReport {
  files_changed: number;
  tests_run: number;
  tests_passed: number;
  tests_failed: number;
  review_notes: number;
  repair_rounds: number;
  total_cost: number;
}

export interface ActiveRepair {
  round: number;
  max_rounds: number;
  failures: string[];
  reason?: string;
}

export interface TeamStoreState {
  activeJobId: string | null;
  jobStatus: string;
  isVerifying: boolean;
  activeRepair: ActiveRepair | null;
  finalReport: FinalReport | null;
  tasks: TeamTask[];
  teamMessages: TeamMessage[];
  handoffs: HandoffArtifact[];
  approvals: any[];
  agentMetrics: Record<string, AgentMetric>;
  teamConfig: TeamConfig;
  selectedTaskId: string | null;
  sseConnection: EventSource | null;
  sseStatus: "disconnected" | "connecting" | "connected" | "error";
  reconnectAttempts: number;
  error: string | null;

  // Actions
  setActiveJobId: (jobId: string | null) => void;
  selectTask: (taskId: string | null) => void;
  updateTeamConfig: (config: Partial<TeamConfig>) => void;
  connectSSE: (jobId: string) => void;
  disconnectSSE: () => void;
  handleSSEEvent: (eventType: string, data: any) => void;
  submitTeamJob: (
    workspace: string,
    userRequest: string,
    configOverride?: Partial<TeamConfig>
  ) => Promise<string>;
  injectPrompt: (prompt: string, targetRole?: string, urgent?: boolean) => Promise<void>;
  pauseJob: () => Promise<void>;
  resumeJob: () => Promise<void>;
  cancelJob: () => Promise<void>;
  saveFinalReport: (report?: FinalReport) => Promise<void>;
  exportReportMarkdown: () => Promise<string>;
  reset: () => void;
}

const TERMINAL_STATUSES = new Set(["completed", "failed", "cancelled"]);
let reconnectTimer: any = null;

export const useTeamStore = create<TeamStoreState>((set, get) => ({
  activeJobId: null,
  jobStatus: "idle",
  isVerifying: false,
  activeRepair: null,
  finalReport: null,
  tasks: [],
  teamMessages: [],
  handoffs: [],
  approvals: [],
  agentMetrics: {
    architect: { total_tokens: 0, input_tokens: 0, output_tokens: 0, total_cost: 0, message_count: 0 },
    coder: { total_tokens: 0, input_tokens: 0, output_tokens: 0, total_cost: 0, message_count: 0 },
    reviewer: { total_tokens: 0, input_tokens: 0, output_tokens: 0, total_cost: 0, message_count: 0 },
    tester: { total_tokens: 0, input_tokens: 0, output_tokens: 0, total_cost: 0, message_count: 0 },
    devops: { total_tokens: 0, input_tokens: 0, output_tokens: 0, total_cost: 0, message_count: 0 },
  },
  teamConfig: DEFAULT_TEAM_CONFIG,
  selectedTaskId: null,
  sseConnection: null,
  sseStatus: "disconnected",
  reconnectAttempts: 0,
  error: null,

  setActiveJobId: (jobId) => {
    set({ activeJobId: jobId });
    if (jobId) {
      get().connectSSE(jobId);
    } else {
      get().disconnectSSE();
    }
  },

  selectTask: (taskId) => set({ selectedTaskId: taskId }),

  updateTeamConfig: (config) =>
    set((state) => ({ teamConfig: { ...state.teamConfig, ...config } })),

  handleSSEEvent: (eventType: string, data: any) => {
    const state = get();

    switch (eventType) {
      case "team_snapshot": {
        const snap = typeof data === "string" ? JSON.parse(data) : data;
        const tasks: TeamTask[] = (snap.tasks || []).map((t: any) => ({
          id: t.id,
          job_id: t.job_id || snap.job_id,
          title: t.title,
          assigned_agent: t.assigned_agent,
          dependencies: t.dependencies || [],
          status: (t.status as TaskStatus) || "pending",
          started_at: t.started_at,
          completed_at: t.completed_at,
          duration_seconds: t.duration_seconds,
          errors: t.errors,
          payload: t.payload,
        }));

        set({
          jobStatus: snap.status || (snap.job ? snap.job.status : state.jobStatus),
          tasks: tasks.length > 0 ? tasks : state.tasks,
          teamMessages: snap.messages && snap.messages.length > 0 ? snap.messages : state.teamMessages,
          agentMetrics: snap.metrics ? { ...state.agentMetrics, ...snap.metrics } : state.agentMetrics,
          teamConfig: snap.team_config ? { ...state.teamConfig, ...snap.team_config } : state.teamConfig,
        });
        break;
      }

      case "team_status": {
        const nextStatus = data?.status || state.jobStatus;
        const isVerif = nextStatus === "verifying";
        const finalRep = data?.final_report || data?.report || (data?.metrics && nextStatus === "completed" ? {
          files_changed: data.metrics.files_changed ?? (data.completed_tasks?.length || 0),
          tests_run: data.metrics.tests_run ?? 0,
          tests_passed: data.metrics.tests_passed ?? 0,
          tests_failed: data.metrics.tests_failed ?? 0,
          review_notes: data.metrics.review_notes ?? 0,
          repair_rounds: data.metrics.repair_rounds ?? 1,
          total_cost: data.metrics.total_cost ?? 0,
        } : state.finalReport);

        set({
          jobStatus: nextStatus,
          isVerifying: isVerif,
          finalReport: finalRep,
          activeRepair: nextStatus === "completed" || nextStatus === "verified" || nextStatus === "failed" ? null : state.activeRepair,
        });
        if (TERMINAL_STATUSES.has(nextStatus)) {
          get().disconnectSSE();
        }
        break;
      }

      case "team_step_update": {
        const taskId = data?.task_id;
        if (!taskId) break;
        const existingTasks = [...state.tasks];
        const idx = existingTasks.findIndex((t) => t.id === taskId);
        if (idx >= 0) {
          existingTasks[idx] = {
            ...existingTasks[idx],
            status: data.status || existingTasks[idx].status,
            assigned_agent: data.role || existingTasks[idx].assigned_agent,
            duration_seconds: data.duration_seconds ?? existingTasks[idx].duration_seconds,
            errors: data.error || existingTasks[idx].errors,
          };
        } else {
          existingTasks.push({
            id: taskId,
            job_id: state.activeJobId || "",
            title: data.title || `Task ${taskId}`,
            assigned_agent: data.role || "coder",
            dependencies: data.dependencies || [],
            status: data.status || "running",
            duration_seconds: data.duration_seconds,
            errors: data.error,
          });
        }
        set({ tasks: existingTasks });
        break;
      }

      case "team_message": {
        const msg: TeamMessage = {
          id: data.id || data.message_id || Date.now(),
          job_id: data.job_id || state.activeJobId || "",
          task_id: data.task_id,
          sender_role: data.sender_role || "system",
          recipient_role: data.recipient_role || "all",
          message_type: data.message_type || "chat",
          content: data.content || "",
          artifact: data.artifact,
          artifact_json: data.artifact_json,
          token_usage: data.token_usage || 0,
          cost_usd: data.cost_usd || 0,
          acknowledged: Boolean(data.acknowledged),
          details: data.details || null,
          timestamp: data.timestamp || Date.now() / 1000,
        };
        set((s) => ({ teamMessages: [...s.teamMessages, msg] }));
        break;
      }

      case "team_handoff": {
        const handoff: HandoffArtifact = {
          type: data.type || "files",
          from_role: data.from_role || "system",
          to_role: data.to_role || "all",
          task_id: data.task_id,
          payload: data.payload || {},
          summary: data.summary || "Artifact transfer",
          created_at: data.created_at || Date.now() / 1000,
        };
        const msg: TeamMessage = {
          id: Date.now(),
          job_id: state.activeJobId || "",
          task_id: data.task_id,
          sender_role: handoff.from_role,
          recipient_role: handoff.to_role,
          message_type: "handoff",
          content: handoff.summary,
          artifact: handoff,
          timestamp: handoff.created_at || Date.now() / 1000,
        };
        set((s) => ({
          handoffs: [...s.handoffs, handoff],
          teamMessages: [...s.teamMessages, msg],
        }));
        break;
      }

      case "team_approval": {
        set((s) => ({ approvals: [...s.approvals, data] }));
        break;
      }

      case "team_repair": {
        const numFailures = data.failures?.length || 1;
        const contentStr = data.failures?.length
          ? `🔄 Auto-Repair Round ${data.round || 1}/${data.max_rounds || 3}: Coder fixing ${numFailures} test failure${numFailures === 1 ? "" : "s"}`
          : `🔄 Auto-Repair Round ${data.round || 1}/${data.max_rounds || 3}: ${data.reason || "Verification failed, initiating autonomous repair"}`;

        const repairMsg: TeamMessage = {
          id: Date.now(),
          job_id: state.activeJobId || "",
          sender_role: "system",
          recipient_role: "all",
          message_type: "repair",
          content: contentStr,
          details: data,
          timestamp: Date.now() / 1000,
        };
        const repairState: ActiveRepair = {
          round: data.round || 1,
          max_rounds: data.max_rounds || 3,
          failures: data.failures || [],
          reason: data.reason || "Verification failed",
        };
        set((s) => ({
          activeRepair: repairState,
          teamMessages: [...s.teamMessages, repairMsg],
        }));
        break;
      }

      case "team_metrics": {
        if (data && typeof data === "object") {
          const nextMetrics = { ...state.agentMetrics };
          // Could be keyed by role or overall summary
          if (data.by_role) {
            Object.assign(nextMetrics, data.by_role);
          } else if (data.role && nextMetrics[data.role]) {
            nextMetrics[data.role] = {
              ...nextMetrics[data.role],
              total_tokens: (nextMetrics[data.role].total_tokens || 0) + (data.total_tokens || 0),
              total_cost: (nextMetrics[data.role].total_cost || 0) + (data.cost_usd || 0),
              message_count: (nextMetrics[data.role].message_count || 0) + 1,
            };
          } else {
            // General update
            Object.keys(data).forEach((k) => {
              if (nextMetrics[k]) {
                nextMetrics[k] = { ...nextMetrics[k], ...data[k] };
              }
            });
          }
          set({ agentMetrics: nextMetrics });
        }
        break;
      }

      default:
        break;
    }
  },

  connectSSE: (jobId: string) => {
    if (reconnectTimer) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }

    const currentSSE = get().sseConnection;
    if (currentSSE) {
      currentSSE.close();
    }

    set({ sseStatus: "connecting" });

    const API_BASE = "http://127.0.0.1:8000";
    const sseUrl = `${API_BASE}/api/team/jobs/${jobId}/events`;

    try {
      const es = new EventSource(sseUrl);

      es.onopen = () => {
        set({ sseStatus: "connected", reconnectAttempts: 0, sseConnection: es });
      };

      // Listen for all 7 event types + snapshot
      const eventTypes = [
        "team_snapshot",
        "team_status",
        "team_step_update",
        "team_message",
        "team_handoff",
        "team_approval",
        "team_repair",
        "team_metrics",
      ];

      eventTypes.forEach((evtName) => {
        es.addEventListener(evtName, (event: MessageEvent) => {
          try {
            const parsed = JSON.parse(event.data);
            get().handleSSEEvent(evtName, parsed);
          } catch {
            get().handleSSEEvent(evtName, event.data);
          }
        });
      });

      es.onerror = () => {
        set({ sseStatus: "error" });
        es.close();

        // Check if we should auto-reconnect
        const currentStatus = get().jobStatus;
        if (!TERMINAL_STATUSES.has(currentStatus)) {
          const attempts = get().reconnectAttempts + 1;
          const delay = Math.min(1000 * Math.pow(2, attempts - 1), 8000);
          set({ reconnectAttempts: attempts });
          reconnectTimer = setTimeout(() => {
            if (get().activeJobId === jobId) {
              get().connectSSE(jobId);
            }
          }, delay);
        }
      };

      set({ sseConnection: es });
    } catch (err: any) {
      set({ sseStatus: "error", error: err?.message || "Failed to initialize EventSource" });
    }
  },

  disconnectSSE: () => {
    if (reconnectTimer) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
    const es = get().sseConnection;
    if (es) {
      es.close();
      set({ sseConnection: null, sseStatus: "disconnected" });
    }
  },

  submitTeamJob: async (workspace, userRequest, configOverride) => {
    set({ error: null, jobStatus: "queued" });
    const cfg = { ...get().teamConfig, ...(configOverride || {}) };

    try {
      const res = await api.post<{ job_id: string; status: string; task_count: number }>(
        "/api/team/jobs",
        {
          workspace,
          user_request: userRequest,
          team_config: cfg,
        }
      );

      const jobId = res.job_id;
      set({
        activeJobId: jobId,
        jobStatus: res.status || "queued",
        tasks: [],
        teamMessages: [],
        handoffs: [],
        approvals: [],
        teamConfig: cfg,
      });

      get().connectSSE(jobId);
      return jobId;
    } catch (err: any) {
      const errMsg = err?.message || "Failed to submit team job";
      set({ error: errMsg, jobStatus: "failed" });
      throw err;
    }
  },

  injectPrompt: async (prompt, targetRole = "coder", urgent = false) => {
    const jobId = get().activeJobId;
    if (!jobId) return;

    try {
      const res: any = await api.post(`/api/team/jobs/${jobId}/inject`, {
        prompt,
        target_role: targetRole,
        urgent,
      });

      // Optimistically add message if not already delivered via SSE stream
      const currentMessages = get().teamMessages;
      const alreadyPresent = currentMessages.some(
        (m) => m.sender_role === "operator" && m.content === prompt
      );
      if (!alreadyPresent) {
        const opMsg: TeamMessage = {
          id: res?.message_id || Date.now(),
          job_id: jobId,
          sender_role: "operator",
          recipient_role: targetRole,
          message_type: "injection",
          content: prompt,
          details: { urgent, target_role: targetRole },
          timestamp: Date.now() / 1000,
        };
        const nextMsgs = [...currentMessages, opMsg];
        if (urgent) {
          const roleTitle = targetRole !== "all" ? targetRole.charAt(0).toUpperCase() + targetRole.slice(1) : "Team";
          const ackMsg: TeamMessage = {
            id: Date.now() + 1,
            job_id: jobId,
            sender_role: targetRole !== "all" ? targetRole : "system",
            recipient_role: "operator",
            message_type: "chat",
            content: `Acknowledged by [${roleTitle}]: ${prompt}`,
            acknowledged: true,
            details: { target_role: targetRole },
            timestamp: Date.now() / 1000,
          };
          nextMsgs.push(ackMsg);
        }
        set({ teamMessages: nextMsgs });
      }
    } catch (err: any) {
      set({ error: err?.message || "Failed to inject prompt" });
      throw err;
    }
  },

  pauseJob: async () => {
    const jobId = get().activeJobId;
    if (!jobId) return;
    try {
      await api.post(`/api/team/jobs/${jobId}/pause`);
      set({ jobStatus: "paused" });
    } catch (err: any) {
      set({ error: err?.message || "Failed to pause team job" });
      throw err;
    }
  },

  resumeJob: async () => {
    const jobId = get().activeJobId;
    if (!jobId) return;
    try {
      await api.post(`/api/team/jobs/${jobId}/resume`);
      set({ jobStatus: "running" });
    } catch (err: any) {
      set({ error: err?.message || "Failed to resume team job" });
      throw err;
    }
  },

  cancelJob: async () => {
    const jobId = get().activeJobId;
    if (!jobId) return;
    try {
      await api.post(`/api/team/jobs/${jobId}/cancel`);
      set({ jobStatus: "cancelled" });
      get().disconnectSSE();
    } catch (err: any) {
      set({ error: err?.message || "Failed to cancel team job" });
      throw err;
    }
  },

  saveFinalReport: async (report?: FinalReport) => {
    const { activeJobId, finalReport } = get();
    const rep = report || finalReport;
    if (!activeJobId || !rep) return;
    try {
      await api.post(`/api/team/jobs/${activeJobId}/report`, { final_report: rep });
    } catch (e) {
      console.warn("Failed to auto-save final report", e);
    }
  },

  exportReportMarkdown: async () => {
    const { activeJobId, finalReport, agentMetrics } = get();
    if (!activeJobId) return "# No active job\n";
    try {
      const res = await fetch(`http://127.0.0.1:8000/api/team/jobs/${activeJobId}/report/export`);
      if (res.ok) {
        return await res.text();
      }
    } catch (e) {
      console.warn("Export API fetch error, using client-side markdown formatter", e);
    }
    let md = `# Autonomous Engineering Team — Final Verification Report\n\n`;
    md += `**Job ID:** \`${activeJobId}\`\n\n`;
    if (finalReport) {
      md += `## Verification Summary\n\n`;
      md += `- **Files Changed:** ${finalReport.files_changed}\n`;
      md += `- **Tests Passed:** ${finalReport.tests_passed} / ${finalReport.tests_run}\n`;
      md += `- **Tests Failed:** ${finalReport.tests_failed}\n`;
      md += `- **Review Notes:** ${finalReport.review_notes}\n`;
      md += `- **Repair Rounds:** ${finalReport.repair_rounds}\n`;
      md += `- **Total Cost:** $${Number(finalReport.total_cost || 0).toFixed(4)}\n\n`;
    }
    md += `## Role Cost Breakdown\n\n`;
    for (const [role, m] of Object.entries(agentMetrics)) {
      md += `- **${role.toUpperCase()}**: $${Number(m.total_cost || 0).toFixed(4)} (${m.total_tokens.toLocaleString()} tokens)\n`;
    }
    return md;
  },

  reset: () => {
    get().disconnectSSE();
    set({
      activeJobId: null,
      jobStatus: "idle",
      isVerifying: false,
      activeRepair: null,
      finalReport: null,
      tasks: [],
      teamMessages: [],
      handoffs: [],
      approvals: [],
      teamConfig: DEFAULT_TEAM_CONFIG,
      selectedTaskId: null,
      error: null,
      reconnectAttempts: 0,
    });
  },
}));
