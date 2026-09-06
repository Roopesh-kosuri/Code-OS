/**
 * agenticTerminalStore.ts — Zustand store for Agentic Terminal.
 *
 * Manages:
 * - Active terminal sessions and current active session ID
 * - Real-time SSE streaming connection to /api/terminal/stream/:id
 * - Terminal events: input (agent typing), output (stdout/stderr), exit (exit code)
 * - Process control: kill/signal, clear, session close, command execution
 */

import { create } from "zustand";
import { api } from "../../lib/api";

export interface TerminalEvent {
  type: "connected" | "input" | "output" | "exit" | "session_closed" | "error";
  terminal_id?: string;
  command?: string;
  line?: string;
  stream?: "stdout" | "stderr";
  code?: number;
  duration_ms?: number;
  timestamp: number;
  message?: string;
}

export interface TerminalHistoryEntry {
  command: string;
  stdout: string;
  stderr: string;
  exit_code: number;
  duration_ms: number;
  timestamp: number;
}

export interface AgenticTerminalSession {
  terminal_id: string;
  job_id: string;
  workspace: string;
  status: "idle" | "running" | "closed";
  created_at: number;
  history: TerminalHistoryEntry[];
}

export interface AgenticTerminalState {
  sessions: Record<string, AgenticTerminalSession>;
  activeTerminalId: string | null;
  streamingOutputs: Record<string, TerminalEvent[]>;
  isProcessRunning: Record<string, boolean>;
  isLoading: boolean;
  error: string | null;

  // Selectors
  getActiveSession: () => AgenticTerminalSession | null;
  getActiveEvents: () => TerminalEvent[];
  getActiveCount: () => number;

  // Actions
  setActiveTerminal: (terminalId: string | null) => void;
  createSession: (jobId?: string, workspace?: string) => Promise<string>;
  executeCommand: (terminalId: string, command: string, args?: string[]) => Promise<any>;
  sendSignal: (terminalId: string, signal?: string) => Promise<boolean>;
  closeSession: (terminalId: string) => Promise<boolean>;
  clearTerminal: (terminalId: string) => void;
  fetchActiveSessions: () => Promise<void>;
  fetchHistory: (terminalId: string) => Promise<void>;
  connectStream: (terminalId: string, onEvent?: (event: TerminalEvent) => void) => () => void;
  appendEvent: (terminalId: string, event: TerminalEvent) => void;
}

// Module-level map of active EventSources for streaming cleanup
const activeEventSources: Record<string, EventSource> = {};

export const useAgenticTerminalStore = create<AgenticTerminalState>((set, get) => ({
  sessions: {},
  activeTerminalId: null,
  streamingOutputs: {},
  isProcessRunning: {},
  isLoading: false,
  error: null,

  getActiveSession: () => {
    const { activeTerminalId, sessions } = get();
    return activeTerminalId ? sessions[activeTerminalId] || null : null;
  },

  getActiveEvents: () => {
    const { activeTerminalId, streamingOutputs } = get();
    return activeTerminalId ? streamingOutputs[activeTerminalId] || [] : [];
  },

  getActiveCount: () => {
    return Object.values(get().sessions).filter((s) => s.status !== "closed").length;
  },

  setActiveTerminal: (terminalId: string | null) => {
    set({ activeTerminalId: terminalId });
  },

  createSession: async (jobId = "interactive_agent", workspace = "") => {
    try {
      set({ isLoading: true, error: null });
      const resp = await api.post<{ ok: boolean; terminal_id: string; session: AgenticTerminalSession }>(
        "/api/terminal/create",
        {
          job_id: jobId,
          workspace: workspace || ".",
        }
      );

      const terminalId = resp.terminal_id;
      const newSession: AgenticTerminalSession = resp.session || {
        terminal_id: terminalId,
        job_id: jobId,
        workspace: workspace || ".",
        status: "idle",
        created_at: Date.now() / 1000,
        history: [],
      };

      set((state) => ({
        sessions: { ...state.sessions, [terminalId]: newSession },
        activeTerminalId: terminalId,
        streamingOutputs: { ...state.streamingOutputs, [terminalId]: [] },
        isProcessRunning: { ...state.isProcessRunning, [terminalId]: false },
        isLoading: false,
      }));

      return terminalId;
    } catch (err: any) {
      console.error("[agenticTerminalStore] Failed to create session:", err);
      set({ error: err.message || "Failed to create terminal session", isLoading: false });
      throw err;
    }
  },

  executeCommand: async (terminalId: string, command: string, args?: string[]) => {
    try {
      set((s) => ({
        isProcessRunning: { ...s.isProcessRunning, [terminalId]: true },
        sessions: {
          ...s.sessions,
          [terminalId]: s.sessions[terminalId]
            ? { ...s.sessions[terminalId], status: "running" }
            : (s.sessions[terminalId] as any),
        },
      }));

      const resp = await api.post<{ ok: boolean; result: TerminalHistoryEntry }>(
        "/api/terminal/execute",
        {
          terminal_id: terminalId,
          command,
          args,
        }
      );

      set((s) => ({
        isProcessRunning: { ...s.isProcessRunning, [terminalId]: false },
        sessions: {
          ...s.sessions,
          [terminalId]: s.sessions[terminalId]
            ? {
                ...s.sessions[terminalId],
                status: "idle",
                history: [...(s.sessions[terminalId].history || []), resp.result],
              }
            : (s.sessions[terminalId] as any),
        },
      }));

      return resp.result;
    } catch (err: any) {
      set((s) => ({
        isProcessRunning: { ...s.isProcessRunning, [terminalId]: false },
        sessions: {
          ...s.sessions,
          [terminalId]: s.sessions[terminalId]
            ? { ...s.sessions[terminalId], status: "idle" }
            : (s.sessions[terminalId] as any),
        },
      }));
      throw err;
    }
  },

  sendSignal: async (terminalId: string, signal = "SIGINT") => {
    try {
      const resp = await api.post<{ ok: boolean; signaled: boolean }>("/api/terminal/signal", {
        terminal_id: terminalId,
        signal,
      });
      if (resp.signaled) {
        set((s) => ({
          isProcessRunning: { ...s.isProcessRunning, [terminalId]: false },
        }));
      }
      return resp.signaled;
    } catch (err: any) {
      console.error("[agenticTerminalStore] Failed to send signal:", err);
      return false;
    }
  },

  closeSession: async (terminalId: string) => {
    try {
      if (activeEventSources[terminalId]) {
        activeEventSources[terminalId].close();
        delete activeEventSources[terminalId];
      }

      const resp = await api.post<{ ok: boolean; closed: boolean }>("/api/terminal/close", {
        terminal_id: terminalId,
      });

      set((state) => {
        const updated = { ...state.sessions };
        if (updated[terminalId]) {
          updated[terminalId] = { ...updated[terminalId], status: "closed" };
        }
        const remainingActive = Object.values(updated).filter((s) => s.status !== "closed");
        const nextActiveId =
          state.activeTerminalId === terminalId
            ? remainingActive.length > 0
              ? remainingActive[0].terminal_id
              : null
            : state.activeTerminalId;

        return {
          sessions: updated,
          activeTerminalId: nextActiveId,
          isProcessRunning: { ...state.isProcessRunning, [terminalId]: false },
        };
      });

      return resp.closed;
    } catch (err: any) {
      console.error("[agenticTerminalStore] Failed to close session:", err);
      return false;
    }
  },

  clearTerminal: (terminalId: string) => {
    set((state) => ({
      streamingOutputs: {
        ...state.streamingOutputs,
        [terminalId]: [],
      },
    }));
  },

  fetchActiveSessions: async () => {
    try {
      const resp = await api.get<{ ok: boolean; sessions: AgenticTerminalSession[] }>(
        "/api/terminal/active-sessions"
      );
      if (resp.sessions) {
        const sessionMap: Record<string, AgenticTerminalSession> = {};
        resp.sessions.forEach((s) => {
          sessionMap[s.terminal_id] = s;
        });
        set((state) => ({
          sessions: { ...state.sessions, ...sessionMap },
          activeTerminalId:
            state.activeTerminalId && sessionMap[state.activeTerminalId]
              ? state.activeTerminalId
              : resp.sessions.length > 0
              ? resp.sessions[0].terminal_id
              : state.activeTerminalId,
        }));
      }
    } catch (err: any) {
      console.warn("[agenticTerminalStore] fetchActiveSessions failed:", err);
    }
  },

  fetchHistory: async (terminalId: string) => {
    try {
      const resp = await api.get<{ ok: boolean; history: TerminalHistoryEntry[]; status: string }>(
        `/api/terminal/history/${terminalId}`
      );
      if (resp.history) {
        set((state) => {
          const sess = state.sessions[terminalId];
          if (!sess) return state;
          return {
            sessions: {
              ...state.sessions,
              [terminalId]: {
                ...sess,
                history: resp.history,
                status: (resp.status as any) || sess.status,
              },
            },
          };
        });
      }
    } catch (err: any) {
      console.warn(`[agenticTerminalStore] fetchHistory failed for ${terminalId}:`, err);
    }
  },

  appendEvent: (terminalId: string, event: TerminalEvent) => {
    set((state) => {
      const existing = state.streamingOutputs[terminalId] || [];
      return {
        streamingOutputs: {
          ...state.streamingOutputs,
          [terminalId]: [...existing, event],
        },
      };
    });
  },

  connectStream: (terminalId: string, onEvent?: (event: TerminalEvent) => void) => {
    if (!terminalId) return () => {};

    if (activeEventSources[terminalId]) {
      activeEventSources[terminalId].close();
      delete activeEventSources[terminalId];
    }

    try {
      const es = new EventSource(`/api/terminal/stream/${encodeURIComponent(terminalId)}`);
      activeEventSources[terminalId] = es;

      es.onmessage = (e) => {
        try {
          const data = JSON.parse(e.data) as TerminalEvent;
          get().appendEvent(terminalId, data);
          if (onEvent) onEvent(data);

          if (data.type === "input") {
            set((s) => ({
              isProcessRunning: { ...s.isProcessRunning, [terminalId]: true },
            }));
          } else if (data.type === "exit" || data.type === "session_closed") {
            set((s) => ({
              isProcessRunning: { ...s.isProcessRunning, [terminalId]: false },
            }));
          }
        } catch (err) {
          console.warn("[agenticTerminalStore] Failed to parse SSE event:", err);
        }
      };

      es.onerror = () => {
        // SSE auto-reconnects by default in browsers
      };

      return () => {
        es.close();
        delete activeEventSources[terminalId];
      };
    } catch (err) {
      console.warn("[agenticTerminalStore] Failed to create EventSource:", err);
      return () => {};
    }
  },
}));
