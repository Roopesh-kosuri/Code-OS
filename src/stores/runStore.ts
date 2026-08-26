import { create } from "zustand";
import { api } from "../lib/api";

export type RunStatus = "idle" | "compiling" | "running" | "completed" | "failed" | "stopped";

export const MAX_LOG_ENTRIES = 10_000;

function appendLog(existing: LogEntry[], entry: LogEntry): LogEntry[] {
  const next = [...existing, entry];
  return next.length > MAX_LOG_ENTRIES ? next.slice(next.length - MAX_LOG_ENTRIES) : next;
}

export interface LogEntry {
  id: string;
  type: "system" | "stdout" | "stderr" | "compiling";
  text: string;
  timestamp: number;
}

export interface Toolchain {
  id: string;
  name: string;
  installed: boolean;
  version: string | null;
  command_path: string | null;
  compile_command_path: string | null;
  install_hint: string;
  error_message: string | null;
}

interface RunState {
  status: RunStatus;
  activeRunId: string | null;
  activeFilePath: string | null;
  detectedLanguage: string | null;
  command: string | null;
  logs: LogEntry[];
  exitCode: number | null;
  durationMs: number | null;
  error: string | null;
  toolchains: Toolchain[];
  isLoadingToolchains: boolean;
  abortController: AbortController | null;

  runFile: (workspace: string, filePath: string, args?: string[]) => Promise<void>;
  stopRun: () => Promise<void>;
  clearLogs: () => void;
  fetchToolchains: () => Promise<void>;
}

export const useRunStore = create<RunState>((set, get) => ({
  status: "idle",
  activeRunId: null,
  activeFilePath: null,
  detectedLanguage: null,
  command: null,
  logs: [],
  exitCode: null,
  durationMs: null,
  error: null,
  toolchains: [],
  isLoadingToolchains: false,
  abortController: null,

  runFile: async (workspace: string, filePath: string, args: string[] = []) => {
    // If a run is already executing, stop it first
    if (get().status === "running" || get().status === "compiling") {
      await get().stopRun();
    }

    const abortController = new AbortController();
    const filename = filePath.split(/[/\\]/).pop() || filePath;

    set({
      status: "running",
      activeFilePath: filePath,
      activeRunId: null,
      detectedLanguage: null,
      command: null,
      exitCode: null,
      durationMs: null,
      error: null,
      abortController,
      logs: [
        {
          id: `log-${Date.now()}-init`,
          type: "system",
          text: `[CODE OS Runner] Preparing ${filename}...\n`,
          timestamp: Date.now(),
        },
      ],
    });

    try {
      await api.terminal.runFileStream(
        workspace,
        filePath,
        args,
        (eventType, data: any) => {
          const now = Date.now();
          if (eventType === "compiling") {
            set((s) => ({
              status: "compiling",
              detectedLanguage: data.language || s.detectedLanguage,
              logs: appendLog(s.logs, {
                id: `log-${now}-${Math.random().toString(36).slice(2, 6)}`,
                type: "compiling",
                text: `🔨 ${data.message || "Compiling source file..."}\n`,
                timestamp: now,
              }),
            }));
          } else if (eventType === "started") {
            set((s) => ({
              status: "running",
              activeRunId: data.run_id || s.activeRunId,
              detectedLanguage: data.language || s.detectedLanguage,
              command: data.command || s.command,
              logs: [
                ...s.logs,
                {
                  id: `log-${now}-${Math.random().toString(36).slice(2, 6)}`,
                  type: "system",
                  text: `▶ Executing: ${data.command || data.file} [${data.language || "Unknown"}]\n`,
                  timestamp: now,
                },
              ],
            }));
          } else if (eventType === "stdout") {
            set((s) => ({
              logs: appendLog(s.logs, {
                id: `log-${now}-${Math.random().toString(36).slice(2, 6)}`,
                type: "stdout",
                text: data.text || "",
                timestamp: now,
              }),
            }));
          } else if (eventType === "stderr") {
            set((s) => ({
              logs: appendLog(s.logs, {
                id: `log-${now}-${Math.random().toString(36).slice(2, 6)}`,
                type: "stderr",
                text: data.text || "",
                timestamp: now,
              }),
            }));
          } else if (eventType === "exit") {
            const isSuccess = data.exit_code === 0;
            set((s) => ({
              status: isSuccess ? "completed" : "failed",
              exitCode: data.exit_code,
              durationMs: data.duration_ms,
              error: isSuccess ? null : (data.error || s.error || `Process exited with code ${data.exit_code}`),
              logs: appendLog(s.logs, {
                id: `log-${now}-${Math.random().toString(36).slice(2, 6)}`,
                type: "system",
                text: `\n[Process exited with code ${data.exit_code} in ${(data.duration_ms / 1000).toFixed(2)}s]\n`,
                timestamp: now,
              }),
            }));
          } else if (eventType === "error") {
            set((s) => ({
              status: "failed",
              error: data.error,
              logs: appendLog(s.logs, {
                id: `log-${now}-${Math.random().toString(36).slice(2, 6)}`,
                type: "stderr",
                text: `\n[Error]: ${data.error}\n`,
                timestamp: now,
              }),
            }));
          }
        },
        abortController.signal
      );
    } catch (err: any) {
      if (err.name === "AbortError") {
        set((s) => ({
          status: "stopped",
          logs: appendLog(s.logs, {
            id: `log-${Date.now()}-abort`,
            type: "system",
            text: "\n[Process execution stopped by user]\n",
            timestamp: Date.now(),
          }),
        }));
      } else {
        set((s) => ({
          status: "failed",
          error: err.message || String(err),
          logs: appendLog(s.logs, {
            id: `log-${Date.now()}-err`,
            type: "stderr",
            text: `\n[Fatal Runner Error]: ${err.message || String(err)}\n`,
            timestamp: Date.now(),
          }),
        }));
      }
    } finally {
      set({ abortController: null });
    }
  },

  stopRun: async () => {
    const { activeRunId, abortController } = get();
    if (abortController) {
      abortController.abort();
    }
    if (activeRunId) {
      try {
        await api.terminal.killRun(activeRunId);
      } catch (e) {
        console.warn("[runStore] Failed to kill remote run process", e);
      }
    }
    set({
      status: "stopped",
      activeRunId: null,
      abortController: null,
    });
  },

  clearLogs: () => {
    set({ logs: [], error: null, exitCode: null, durationMs: null });
  },

  fetchToolchains: async () => {
    set({ isLoadingToolchains: true });
    try {
      const res = await api.terminal.getToolchains();
      set({ toolchains: res.toolchains || [] });
    } catch (err) {
      console.warn("[runStore] Failed to fetch toolchains", err);
    } finally {
      set({ isLoadingToolchains: false });
    }
  },
}));
