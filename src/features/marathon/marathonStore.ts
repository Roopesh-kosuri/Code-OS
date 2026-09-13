// Marathon Autopilot — Zustand store with SSE connection and API actions
import { create } from "zustand";
import { api } from "../../lib/api";
import type {
  MarathonSSEEvent,
  MarathonStateResponse,
  MarathonStatus,
  StartMarathonRequest,
} from "./types";

interface MarathonStore {
  // State
  activeMarathon: MarathonStateResponse | null;
  marathonList: MarathonStateResponse[];
  isLoading: boolean;
  error: string | null;
  showModal: boolean;
  liveLog: string[];

  // SSE connection
  _sseSource: EventSource | null;

  // Actions
  setShowModal: (show: boolean) => void;
  startMarathon: (req: StartMarathonRequest) => Promise<void>;
  pauseMarathon: (workspace: string) => Promise<void>;
  resumeMarathon: (workspace: string) => Promise<void>;
  abortMarathon: (workspace: string) => Promise<void>;
  connectSSE: (marathonId: string, workspace: string) => void;
  disconnectSSE: () => void;
  updateFromSSE: (event: MarathonSSEEvent) => void;
  fetchState: (marathonId: string, workspace: string) => Promise<void>;
  checkForActiveMarathon: (workspace: string) => Promise<void>;
  appendLog: (entry: string) => void;
  clearError: () => void;
}

export const useMarathonStore = create<MarathonStore>((set, get) => ({
  activeMarathon: null,
  marathonList: [],
  isLoading: false,
  error: null,
  showModal: false,
  liveLog: [],
  _sseSource: null,

  setShowModal: (show) => set({ showModal: show }),

  clearError: () => set({ error: null }),

  appendLog: (entry) =>
    set((s) => ({ liveLog: [...s.liveLog.slice(-199), entry] })),

  startMarathon: async (req) => {
    set({ isLoading: true, error: null, liveLog: [] });
    try {
      const data = await api.post<MarathonStateResponse>("/api/marathon/start", req);
      set({ activeMarathon: data, isLoading: false, showModal: false });
      get().connectSSE(data.marathon_id, req.workspace);
    } catch (e) {
      set({ error: String(e), isLoading: false });
    }
  },

  pauseMarathon: async (workspace) => {
    const mid = get().activeMarathon?.marathon_id;
    if (!mid) return;
    try {
      const data = await api.post<MarathonStateResponse>(`/api/marathon/${mid}/pause?workspace=${encodeURIComponent(workspace)}`, {});
      set({ activeMarathon: data });
    } catch (e) {
      set({ error: String(e) });
    }
  },

  resumeMarathon: async (workspace) => {
    const mid = get().activeMarathon?.marathon_id;
    if (!mid) return;
    try {
      const data = await api.post<MarathonStateResponse>(`/api/marathon/${mid}/resume?workspace=${encodeURIComponent(workspace)}`, {});
      set({ activeMarathon: data });
      get().connectSSE(mid, workspace);
    } catch (e) {
      set({ error: String(e) });
    }
  },

  abortMarathon: async (workspace) => {
    const mid = get().activeMarathon?.marathon_id;
    if (!mid) return;
    get().disconnectSSE();
    try {
      const data = await api.post<MarathonStateResponse>(`/api/marathon/${mid}/abort?workspace=${encodeURIComponent(workspace)}`, {});
      set({ activeMarathon: data });
    } catch (e) {
      set({ error: String(e) });
    }
  },

  fetchState: async (marathonId, workspace) => {
    try {
      const data = await api.get<MarathonStateResponse>(`/api/marathon/${marathonId}?workspace=${encodeURIComponent(workspace)}`);
      set({ activeMarathon: data });
    } catch {
      // silently ignore
    }
  },

  checkForActiveMarathon: async (workspace) => {
    try {
      const data = await api.get<{ found: boolean; marathon: MarathonStateResponse | null }>(
        `/api/marathon/active/resume-check?workspace=${encodeURIComponent(workspace)}`
      );
      if (data.found && data.marathon) {
        set({ activeMarathon: data.marathon });
        get().connectSSE(data.marathon.marathon_id, workspace);
      }
    } catch {
      // ignore
    }
  },

  connectSSE: (marathonId, workspace) => {
    get().disconnectSSE();
    const url = `http://127.0.0.1:8000/api/marathon/${marathonId}/stream?workspace=${encodeURIComponent(workspace)}`;
    const source = new EventSource(url);
    source.addEventListener("marathon_update", (e) => {
      try {
        const payload: MarathonSSEEvent = JSON.parse(e.data);
        get().updateFromSSE(payload);
      } catch {
        // ignore parse errors
      }
    });
    source.onerror = () => {
      source.close();
    };
    set({ _sseSource: source });
  },

  disconnectSSE: () => {
    const src = get()._sseSource;
    if (src) {
      src.close();
      set({ _sseSource: null });
    }
  },

  updateFromSSE: (event) => {
    const { appendLog } = get();
    // Update usage in the active marathon
    set((s) => {
      if (!s.activeMarathon) return {};
      const updated: MarathonStateResponse = {
        ...s.activeMarathon,
        status: event.status as MarathonStatus,
        progress_completed: event.progress_completed,
        progress_total: event.progress_total,
        usage: {
          ...s.activeMarathon.usage,
          tokens_used: event.tokens_used,
          cost_usd: event.cost_usd,
          elapsed_seconds: event.elapsed_seconds,
        },
        // Update individual task status if provided
        tasks: s.activeMarathon.tasks.map((t) => {
          if (event.task_id && t.id === event.task_id) {
            if (event.event === "task_started") return { ...t, status: "in_progress" as const };
            if (event.event === "task_completed") return { ...t, status: "completed" as const, git_commit_hash: event.commit_hash ?? null };
            if (event.event === "task_blocked") return { ...t, status: "blocked" as const };
          }
          return t;
        }),
      };
      return { activeMarathon: updated };
    });

    // Append to live log
    const logEntry = `[${new Date().toLocaleTimeString()}] ${event.event}${event.title ? `: ${event.title}` : ""}${event.reason ? ` (${event.reason})` : ""}`;
    appendLog(logEntry);
  },
}));
