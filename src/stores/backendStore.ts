import { create } from "zustand";
import { api } from "../lib/api";

export type BackendConnectionStatus = "connected" | "connecting" | "disconnected";

export interface BackendFreshness {
  boot_timestamp: number;
  boot_iso: string;
  uptime_seconds: number;
  is_stale: boolean;
  latest_source_mtime: number;
  changed_files: string[];
}

type BackendState = {
  status: BackendConnectionStatus;
  retryCount: number;
  nextRetryInSeconds: number;
  errorMessage: string | null;
  lastChecked: number | null;
  freshness: BackendFreshness | null;

  checkHealth: () => Promise<boolean>;
  checkFreshness: () => Promise<BackendFreshness | null>;
  recordFailure: (err?: unknown) => void;
  recordSuccess: () => void;
  retryNow: () => Promise<void>;
};

let _retryCountdownTimer: number | null = null;

export const useBackendStore = create<BackendState>((set, get) => ({
  status: "connecting",
  retryCount: 0,
  nextRetryInSeconds: 0,
  errorMessage: null,
  lastChecked: null,
  freshness: null,

  recordSuccess: () => {
    if (_retryCountdownTimer) {
      clearInterval(_retryCountdownTimer);
      _retryCountdownTimer = null;
    }
    set({
      status: "connected",
      retryCount: 0,
      nextRetryInSeconds: 0,
      errorMessage: null,
      lastChecked: Date.now(),
    });
  },

  recordFailure: (err) => {
    const current = get();
    const nextCount = current.retryCount + 1;
    // Exponential backoff: 1s, 2s, 4s, 8s, 16s, max 30s
    const delay = Math.min(30, Math.max(1, Math.pow(2, Math.min(nextCount - 1, 5))));

    if (_retryCountdownTimer) {
      clearInterval(_retryCountdownTimer);
    }

    set({
      status: "disconnected",
      retryCount: nextCount,
      nextRetryInSeconds: delay,
      errorMessage: err instanceof Error ? err.message : "Backend not running",
      lastChecked: Date.now(),
    });

    _retryCountdownTimer = window.setInterval(() => {
      const remaining = get().nextRetryInSeconds;
      if (remaining <= 1) {
        clearInterval(_retryCountdownTimer!);
        _retryCountdownTimer = null;
        set({ nextRetryInSeconds: 0 });
        void get().checkHealth();
      } else {
        set({ nextRetryInSeconds: remaining - 1 });
      }
    }, 1000);
  },

  checkHealth: async () => {
    try {
      const res = await fetch("http://127.0.0.1:8000/health", {
        method: "GET",
        headers: { "Content-Type": "application/json" },
      });
      if (res.ok) {
        get().recordSuccess();
        void get().checkFreshness();
        return true;
      } else {
        get().recordFailure(new Error(`HTTP ${res.status}`));
        return false;
      }
    } catch (e: any) {
      if (e?.name !== "AbortError") {
        get().recordFailure(e);
      }
      return false;
    }
  },

  checkFreshness: async () => {
    try {
      const res = await api.get<BackendFreshness>("/api/ai/chat-agent/freshness");
      set({ freshness: res });
      return res;
    } catch {
      return null;
    }
  },

  retryNow: async () => {
    if (_retryCountdownTimer) {
      clearInterval(_retryCountdownTimer);
      _retryCountdownTimer = null;
    }
    set({ status: "connecting", nextRetryInSeconds: 0 });
    await get().checkHealth();
  },
}));

