import { create } from "zustand";
import { api } from "../lib/api";

export interface BudgetConfig {
  daily_limit_usd: number | null;
  session_limit_usd: number | null;
  auto_downgrade_at_percent: number;
  hard_stop_at_percent: number;
  downgrade_model: string;
  show_topbar_pill?: boolean;
  today_spend_usd: number;
  usage_percent: number;
  status: "none" | "downgrade" | "block" | string;
  ok: boolean;
}

export interface SpendJobItem {
  job_id: string;
  workspace: string;
  provider: string;
  model: string;
  cost_usd: number;
  token_count: number;
  event_count?: number;
  timestamp: number;
}

export interface SpendSummary {
  total_usd: number;
  per_provider: Record<string, number>;
  per_model: Record<string, number>;
  per_job: SpendJobItem[];
}

export interface DailyBreakdownItem {
  date: string;
  usd: number;
  job_count: number;
  token_count: number;
}

interface CostStoreState {
  budget: BudgetConfig;
  showTopBarPill: boolean;
  summary: SpendSummary;
  dailyBreakdown: DailyBreakdownItem[];
  activePeriod: "today" | "7d" | "30d" | "all";
  isModalOpen: boolean;
  isLoading: boolean;
  error: string | null;

  // Actions
  setShowTopBarPill: (show: boolean, workspace?: string) => Promise<void>;
  fetchBudget: (workspace?: string) => Promise<void>;
  updateBudget: (patch: Partial<BudgetConfig> & { workspace?: string }) => Promise<void>;
  fetchSummary: (period?: string, workspace?: string) => Promise<void>;
  fetchBreakdown: (days?: number, workspace?: string) => Promise<void>;
  resetTodaySpend: (workspace?: string) => Promise<boolean>;
  openModal: () => void;
  closeModal: () => void;
  setActivePeriod: (period: "today" | "7d" | "30d" | "all") => void;
}

const DEFAULT_BUDGET: BudgetConfig = {
  daily_limit_usd: null,
  session_limit_usd: null,
  auto_downgrade_at_percent: 90,
  hard_stop_at_percent: 100,
  downgrade_model: "groq/llama-3.3-70b",
  show_topbar_pill: true,
  today_spend_usd: 0.0,
  usage_percent: 0.0,
  status: "none",
  ok: true,
};

const DEFAULT_SUMMARY: SpendSummary = {
  total_usd: 0.0,
  per_provider: {},
  per_model: {},
  per_job: [],
};

export const useCostStore = create<CostStoreState>((set, get) => ({
  budget: DEFAULT_BUDGET,
  showTopBarPill: (() => {
    try {
      const saved = localStorage.getItem("code-os:cost.showTopBarPill");
      return saved !== null ? saved !== "false" : true;
    } catch {
      return true;
    }
  })(),
  summary: DEFAULT_SUMMARY,
  dailyBreakdown: [],
  activePeriod: "today",
  isModalOpen: false,
  isLoading: false,
  error: null,

  setShowTopBarPill: async (show: boolean, workspace = "") => {
    try {
      localStorage.setItem("code-os:cost.showTopBarPill", String(show));
    } catch {
      // storage unavailable
    }
    set({ showTopBarPill: show });
    try {
      await get().updateBudget({ show_topbar_pill: show, workspace });
    } catch {
      // local toggle is retained
    }
  },

  fetchBudget: async (workspace = "") => {
    try {
      const q = workspace ? `?workspace=${encodeURIComponent(workspace)}` : "";
      const res = await api.get<BudgetConfig>(`/api/cost/budget${q}`);
      if (res) {
        let showPill = true;
        try {
          const localVal = localStorage.getItem("code-os:cost.showTopBarPill");
          if (localVal !== null) {
            showPill = localVal !== "false";
          } else if (res.show_topbar_pill !== undefined) {
            showPill = res.show_topbar_pill !== false;
          }
        } catch {
          showPill = res.show_topbar_pill !== undefined ? res.show_topbar_pill !== false : true;
        }
        set({ budget: res, showTopBarPill: showPill, error: null });
      }
    } catch (err: any) {
      set({ error: err?.message || "Failed to load budget status" });
    }
  },

  updateBudget: async (patch) => {
    try {
      set({ isLoading: true });
      const res = await api.put<BudgetConfig>("/api/cost/budget", patch);
      if (res) {
        set({ budget: res, isLoading: false, error: null });
      }
    } catch (err: any) {
      set({ isLoading: false, error: err?.message || "Failed to update budget" });
      throw err;
    }
  },

  fetchSummary: async (period = "today", workspace = "") => {
    try {
      set({ isLoading: true });
      const params = new URLSearchParams();
      if (period) params.set("period", period);
      if (workspace) params.set("workspace", workspace);
      const res = await api.get<SpendSummary>(`/api/cost/summary?${params.toString()}`);
      if (res) {
        set({ summary: res, isLoading: false, error: null });
      }
    } catch (err: any) {
      set({ isLoading: false, error: err?.message || "Failed to fetch spend summary" });
    }
  },

  fetchBreakdown: async (days = 30, workspace = "") => {
    try {
      const params = new URLSearchParams();
      params.set("days", String(days));
      if (workspace) params.set("workspace", workspace);
      const res = await api.get<DailyBreakdownItem[]>(`/api/cost/breakdown?${params.toString()}`);
      if (Array.isArray(res)) {
        set({ dailyBreakdown: res, error: null });
      }
    } catch (err: any) {
      set({ error: err?.message || "Failed to fetch daily breakdown" });
    }
  },

  resetTodaySpend: async (workspace = "") => {
    try {
      const q = workspace ? `?workspace=${encodeURIComponent(workspace)}` : "";
      await api.post(`/api/cost/reset-today${q}`, {});
      await get().fetchBudget(workspace);
      await get().fetchSummary(get().activePeriod, workspace);
      await get().fetchBreakdown(30, workspace);
      return true;
    } catch (err: any) {
      set({ error: err?.message || "Failed to reset today's spend" });
      return false;
    }
  },

  openModal: () => set({ isModalOpen: true }),
  closeModal: () => set({ isModalOpen: false }),
  setActivePeriod: (period) => {
    set({ activePeriod: period });
    void get().fetchSummary(period);
  },
}));
