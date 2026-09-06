import { create } from "zustand";
import { api } from "../../../lib/api";

export interface SessionItem {
  job_id: string;
  workspace: string;
  title: string;
  created_at: string;
  completed_at?: string;
  duration: number;
  status: string;
  cost_usd: number;
  step_count: number;
  token_usage: number;
}

export interface TimelineStep {
  step_id: string;
  task_id?: string;
  step_num: number;
  timestamp: number;
  agent_role: string;
  action_type: string;
  tool_name: string;
  status: string;
  input: Record<string, any> | string;
  output: Record<string, any> | string;
  file_changes: Array<{ path: string; original?: string; updated?: string; diff?: string }>;
  thinking: string;
  cost_usd?: number;
}

export interface SessionSnapshot {
  job_id: string;
  step_id: string;
  step_num: number;
  agent_role: string;
  timestamp: number;
  status: string;
  messages: Array<{ role: string; content: string; timestamp?: number; step_id?: string }>;
  staged_changes: Array<{ path: string; original?: string; updated?: string }>;
  workspace_manifest: Record<string, any>;
  agent_state: {
    active_role: string;
    completed_steps: number;
    total_steps: number;
    workflow?: string;
    workspace?: string;
  };
}

interface SessionStoreState {
  sessions: SessionItem[];
  activeSessionId: string | null;
  activeSession: SessionItem | null;
  timeline: TimelineStep[];
  activeStepId: string | null;
  activeSnapshot: SessionSnapshot | null;
  isLoadingSessions: boolean;
  isLoadingTimeline: boolean;
  isLoadingSnapshot: boolean;
  error: string | null;

  // Fork Modal State
  isForkModalOpen: boolean;
  forkTargetStepId: string | null;
  isForking: boolean;

  // Actions
  fetchSessions: (workspace?: string) => Promise<void>;
  selectSession: (job_id: string) => Promise<void>;
  fetchTimeline: (job_id: string) => Promise<void>;
  selectStep: (step_id: string) => Promise<void>;
  fetchSnapshot: (job_id: string, step_id: string) => Promise<void>;
  openForkModal: (step_id?: string) => void;
  closeForkModal: () => void;
  forkSession: (job_id: string, step_id: string, new_prompt: string) => Promise<string | null>;
  exportSession: (job_id: string, format?: "markdown" | "json") => Promise<void>;
}

export const useSessionStore = create<SessionStoreState>((set, get) => ({
  sessions: [],
  activeSessionId: null,
  activeSession: null,
  timeline: [],
  activeStepId: null,
  activeSnapshot: null,
  isLoadingSessions: false,
  isLoadingTimeline: false,
  isLoadingSnapshot: false,
  error: null,

  isForkModalOpen: false,
  forkTargetStepId: null,
  isForking: false,

  fetchSessions: async (workspace = "") => {
    try {
      set({ isLoadingSessions: true, error: null });
      const q = workspace ? `?workspace=${encodeURIComponent(workspace)}&limit=100` : "?limit=100";
      const res = await api.get<SessionItem[]>(`/api/sessions${q}`);
      if (Array.isArray(res)) {
        set({ sessions: res, isLoadingSessions: false });
        if (res.length > 0 && !get().activeSessionId) {
          void get().selectSession(res[0].job_id);
        }
      } else {
        set({ sessions: [], isLoadingSessions: false });
      }
    } catch (err: any) {
      set({ isLoadingSessions: false, error: err?.message || "Failed to load sessions" });
    }
  },

  selectSession: async (job_id: string) => {
    const current = get().sessions.find((s) => s.job_id === job_id) || null;
    set({
      activeSessionId: job_id,
      activeSession: current,
      activeStepId: null,
      activeSnapshot: null,
    });
    await get().fetchTimeline(job_id);
  },

  fetchTimeline: async (job_id: string) => {
    try {
      set({ isLoadingTimeline: true, error: null });
      const res = await api.get<TimelineStep[]>(`/api/sessions/${job_id}/timeline`);
      if (Array.isArray(res)) {
        set({ timeline: res, isLoadingTimeline: false });
        if (res.length > 0) {
          const firstOrActive = get().activeStepId
            ? res.find((s) => s.step_id === get().activeStepId) || res[0]
            : res[0];
          void get().selectStep(firstOrActive.step_id);
        }
      } else {
        set({ timeline: [], isLoadingTimeline: false });
      }
    } catch (err: any) {
      set({ isLoadingTimeline: false, error: err?.message || "Failed to load timeline" });
    }
  },

  selectStep: async (step_id: string) => {
    set({ activeStepId: step_id });
    const job_id = get().activeSessionId;
    if (job_id) {
      await get().fetchSnapshot(job_id, step_id);
    }
  },

  fetchSnapshot: async (job_id: string, step_id: string) => {
    try {
      set({ isLoadingSnapshot: true });
      const res = await api.get<SessionSnapshot>(`/api/sessions/${job_id}/snapshot?step_id=${encodeURIComponent(step_id)}`);
      if (res) {
        set({ activeSnapshot: res, isLoadingSnapshot: false });
      }
    } catch (err: any) {
      set({ isLoadingSnapshot: false });
    }
  },

  openForkModal: (step_id?: string) => {
    const target = step_id || get().activeStepId || (get().timeline[0]?.step_id ?? "");
    set({ isForkModalOpen: true, forkTargetStepId: target });
  },

  closeForkModal: () => {
    set({ isForkModalOpen: false, forkTargetStepId: null });
  },

  forkSession: async (job_id: string, step_id: string, new_prompt: string) => {
    try {
      set({ isForking: true });
      const res = await api.post<{ job_id: string }>(`/api/sessions/${job_id}/fork`, {
        step_id,
        new_prompt,
      });
      set({ isForking: false, isForkModalOpen: false, forkTargetStepId: null });
      if (res && res.job_id) {
        // Refresh sessions and switch to new forked job
        await get().fetchSessions();
        await get().selectSession(res.job_id);
        return res.job_id;
      }
      return null;
    } catch (err: any) {
      set({ isForking: false, error: err?.message || "Forking session failed" });
      throw err;
    }
  },

  exportSession: async (job_id: string, format: "markdown" | "json" = "markdown") => {
    try {
      const ext = format === "json" ? "json" : "md";
      const mime = format === "json" ? "application/json" : "text/markdown";
      
      const res = await fetch(`/api/sessions/${job_id}/export?format=${format}`);
      const text = await res.text();

      if (typeof document !== "undefined") {
        const blob = new Blob([text], { type: mime });
        const createObjUrl = (typeof window !== "undefined" && window.URL?.createObjectURL) ? window.URL.createObjectURL : (() => "blob:mock");
        const revokeObjUrl = (typeof window !== "undefined" && window.URL?.revokeObjectURL) ? window.URL.revokeObjectURL : (() => {});
        const url = createObjUrl(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `session_${job_id}.${ext}`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        revokeObjUrl(url);
      }
    } catch (err: any) {
      set({ error: err?.message || "Export session failed" });
    }
  },
}));
