import { create } from "zustand";
import { api } from "../../lib/api";

export interface RawActivity {
  jobs_completed: any[];
  files_modified: string[];
  commits_made: any[];
  tests_passed: number;
  total_cost: string;
  total_tokens?: number;
}

export interface StandupHistoryItem {
  id: string;
  workspace: string;
  date: string;
  format: "slack" | "markdown";
  report: string;
  raw_data: RawActivity;
  created_at: number;
}

interface StandupState {
  rawActivity: RawActivity;
  generatedReport: string;
  format: "slack" | "markdown";
  isGenerating: boolean;
  history: StandupHistoryItem[];
  copied: boolean;

  // Actions
  generateStandup: (workspace: string, date?: string, format?: "slack" | "markdown") => Promise<void>;
  setFormat: (format: "slack" | "markdown") => void;
  copyToClipboard: () => Promise<boolean>;
  loadHistory: (workspace: string) => Promise<void>;
  regenerate: (workspace: string, date?: string) => Promise<void>;
  reset: () => void;
}

const initialRawActivity: RawActivity = {
  jobs_completed: [],
  files_modified: [],
  commits_made: [],
  tests_passed: 0,
  total_cost: "$0.00",
};

export const useStandupStore = create<StandupState>((set, get) => ({
  rawActivity: initialRawActivity,
  generatedReport: "",
  format: "slack",
  isGenerating: false,
  history: [],
  copied: false,

  generateStandup: async (workspace: string, date?: string, format?: "slack" | "markdown") => {
    if (!workspace) return;
    const targetFormat = format || get().format;
    set({ isGenerating: true, format: targetFormat });

    try {
      const res = await api.post<{
        report: string;
        raw_activity: RawActivity;
        format: "slack" | "markdown";
        id: string;
      }>("/api/standup/generate", {
        workspace,
        date,
        format: targetFormat,
      });

      set({
        generatedReport: res.report || "",
        rawActivity: res.raw_activity || initialRawActivity,
        isGenerating: false,
      });

      // Refresh history
      void get().loadHistory(workspace);
    } catch (err) {
      console.error("[standupStore] generateStandup error:", err);
      set({ isGenerating: false });
    }
  },

  setFormat: (format: "slack" | "markdown") => {
    set({ format });
  },

  copyToClipboard: async () => {
    const report = get().generatedReport;
    if (!report) return false;

    try {
      if (typeof navigator !== "undefined" && navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(report);
      }
      set({ copied: true });
      setTimeout(() => set({ copied: false }), 2000);
      return true;
    } catch (err) {
      console.warn("[standupStore] copy error:", err);
      return false;
    }
  },

  loadHistory: async (workspace: string) => {
    if (!workspace) return;
    try {
      const res = await api.get<{ history: StandupHistoryItem[] }>("/api/standup/history", {
        workspace,
      });
      set({ history: res?.history || [] });
    } catch (err) {
      console.debug("[standupStore] loadHistory error:", err);
    }
  },

  regenerate: async (workspace: string, date?: string) => {
    await get().generateStandup(workspace, date, get().format);
  },

  reset: () =>
    set({
      rawActivity: initialRawActivity,
      generatedReport: "",
      format: "slack",
      isGenerating: false,
      history: [],
      copied: false,
    }),
}));
