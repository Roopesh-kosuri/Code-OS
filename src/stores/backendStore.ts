import { create } from "zustand";
import { api } from "../lib/api";

export type BackendConnectionStatus = "connected" | "connecting" | "disconnected";
export type BootPhase = "booting" | "ready" | "failed";

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
  bootPhase: BootPhase;
  bootStartTime: number;
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
  setBootPhase: (phase: BootPhase) => void;
};

let _retryCountdownTimer: number | null = null;

export const useBackendStore = create<BackendState>((set, get) => ({
  status: "connecting",
  bootPhase: "booting",
  bootStartTime: Date.now(),
  retryCount: 0,
  nextRetryInSeconds: 0,
  errorMessage: null,
  lastChecked: null,
  freshness: null,

  setBootPhase: (phase: BootPhase) => set({ bootPhase: phase }),

  recordSuccess: () => {
    const wasDisconnected = get().status !== "connected";
    if (_retryCountdownTimer) {
      clearInterval(_retryCountdownTimer);
      _retryCountdownTimer = null;
    }
    set({
      status: "connected",
      bootPhase: "ready",
      retryCount: 0,
      nextRetryInSeconds: 0,
      errorMessage: null,
      lastChecked: Date.now(),
    });

    if (wasDisconnected) {
      void (async () => {
        try {
          const wsStore = (window as any).useWorkspaceStore?.getState?.();
          if (wsStore) {
            if (wsStore.activeWorkspaces && wsStore.activeWorkspaces.length > 0) {
              await wsStore.refreshTree();
            } else {
              await wsStore.restoreLastWorkspace();
            }
          }
        } catch (err) {
          console.error("[backendStore] Refresh after reconnect failed:", err);
        }
        try {
          await fetch("http://127.0.0.1:8000/api/warmup").catch(() => {});
        } catch {}
      })();
    }
  },

  recordFailure: (err) => {
    const current = get();
    const nextCount = current.retryCount + 1;
    // Exponential backoff: 1s, 2s, 4s, 8s, 16s, max 30s
    const delay = Math.min(30, Math.max(1, Math.pow(2, Math.min(nextCount - 1, 5))));

    if (_retryCountdownTimer) {
      clearInterval(_retryCountdownTimer);
    }

    const elapsed = Date.now() - current.bootStartTime;
    const isBootGraceExpired = elapsed >= 15_000;
    const isMaxBootRetries = nextCount >= 3;
    let nextBootPhase = current.bootPhase;
    if (current.bootPhase === "booting") {
      if (isBootGraceExpired || isMaxBootRetries) {
        nextBootPhase = "failed";
      }
    }

    let errMsg = err instanceof Error ? err.message : "Backend not running";
    if (nextCount >= 3) {
      errMsg = "Backend disconnected, restarting...";
      if ((window as any).codeOS?.restartBackend) {
        console.warn("[backendStore] 3 consecutive failures reached; triggering backend restart via IPC");
        void (window as any).codeOS.restartBackend().catch((e: any) => {
          console.error("[backendStore] IPC restart error:", e);
        });
      }
    }

    set({
      status: "disconnected",
      bootPhase: nextBootPhase,
      retryCount: nextCount,
      nextRetryInSeconds: delay,
      errorMessage: errMsg,
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
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 4000);
    try {
      const res = await fetch("http://127.0.0.1:8000/health", {
        method: "GET",
        headers: { "Content-Type": "application/json" },
        signal: controller.signal,
      });
      clearTimeout(timeoutId);
      if (res.ok) {
        get().recordSuccess();
        void get().checkFreshness();
        return true;
      } else {
        get().recordFailure(new Error(`HTTP ${res.status}`));
        return false;
      }
    } catch (e: any) {
      clearTimeout(timeoutId);
      get().recordFailure(e);
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

