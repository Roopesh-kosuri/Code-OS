/**
 * ronyVoiceStore.ts — Zustand store for Rony Voice: system-wide voice assistant with laptop control.
 */

import { create } from "zustand";
import { api } from "../../lib/api";

export interface AutomationStep {
  step_id: number;
  action_type: string;
  description: string;
  params: Record<string, any>;
  requires_approval: boolean;
}

export interface ActiveAutomationState {
  type: string;
  progress: number; // 0 to 100
  current_step: number;
  total_steps: number;
  description: string;
}

export interface PendingApprovalState {
  id: string;
  title: string;
  action: string;
  details: Record<string, any>;
  message: string;
}

export interface VoiceCommandLog {
  id: string;
  command: string;
  timestamp: number;
  status: "success" | "pending" | "aborted" | "approval_required";
  result?: string;
}

export interface RonyVoiceState {
  // Listening & Voice Activity
  isListening: boolean;
  isProcessing: boolean;
  isAutomating: boolean;
  systemControlEnabled: boolean;
  alwaysListening: boolean;
  wakeWord: string;
  wakeWordDetected: boolean;
  currentTranscript: string;

  // Multi-step task automation
  activeAutomation: ActiveAutomationState | null;

  // Approval Gate
  pendingApproval: PendingApprovalState | null;

  // History & Logs
  commandHistory: VoiceCommandLog[];

  // Actions
  startListening: () => void;
  stopListening: () => void;
  toggleSystemControl: (enabled?: boolean) => void;
  toggleAlwaysListening: (enabled?: boolean) => void;
  setWakeWord: (word: string) => void;
  executeCommand: (text: string) => Promise<void>;
  requestApproval: (title: string, action: string, details: Record<string, any>, message: string) => void;
  approveAction: (id: string) => Promise<void>;
  rejectAction: (id: string) => void;
  emergencyStop: () => Promise<void>;
  clearHistory: () => void;
}

export const useRonyVoiceStore = create<RonyVoiceState>((set, get) => ({
  isListening: false,
  isProcessing: false,
  isAutomating: false,
  systemControlEnabled: false,
  alwaysListening: false,
  wakeWord: "Hey Rony",
  wakeWordDetected: false,
  currentTranscript: "",
  activeAutomation: null,
  pendingApproval: null,
  commandHistory: [],

  startListening: () => {
    set({ isListening: true, currentTranscript: "" });
  },

  stopListening: () => {
    set({ isListening: false });
  },

  toggleSystemControl: (enabled?: boolean) => {
    set((state) => ({
      systemControlEnabled: enabled !== undefined ? enabled : !state.systemControlEnabled,
    }));
  },

  toggleAlwaysListening: (enabled?: boolean) => {
    set((state) => ({
      alwaysListening: enabled !== undefined ? enabled : !state.alwaysListening,
    }));
  },

  setWakeWord: (word: string) => {
    set({ wakeWord: word });
  },

  requestApproval: (title, action, details, message) => {
    const id = `approval-${Date.now()}`;
    set({
      pendingApproval: { id, title, action, details, message },
      isAutomating: false,
    });
  },

  approveAction: async (id: string) => {
    const approval = get().pendingApproval;
    if (!approval || approval.id !== id) return;

    try {
      set({ isProcessing: true, pendingApproval: null });
      const res = await api.post<any>("/api/rony/system-action", {
        action: approval.action,
        params: approval.details,
        approved: true,
      });

      set((state) => ({
        commandHistory: [
          {
            id: `cmd-${Date.now()}`,
            command: `Approved: ${approval.action}`,
            timestamp: Date.now(),
            status: "success",
            result: JSON.stringify(res),
          },
          ...state.commandHistory,
        ],
      }));
    } catch (err: any) {
      console.error("Failed to execute approved action:", err);
    } finally {
      set({ isProcessing: false, isAutomating: false });
    }
  },

  rejectAction: (id: string) => {
    set((state) => {
      if (state.pendingApproval?.id === id) {
        return {
          pendingApproval: null,
          isAutomating: false,
          commandHistory: [
            {
              id: `cmd-${Date.now()}`,
              command: `Denied: ${state.pendingApproval.action}`,
              timestamp: Date.now(),
              status: "aborted",
              result: "User declined destructive operation.",
            },
            ...state.commandHistory,
          ],
        };
      }
      return state;
    });
  },

  emergencyStop: async () => {
    try {
      await api.post("/api/rony/emergency-stop");
    } catch (e) {
      console.warn("Emergency stop API call failed:", e);
    }
    set({
      isListening: false,
      isProcessing: false,
      isAutomating: false,
      activeAutomation: null,
      pendingApproval: null,
      currentTranscript: "Emergency Stop Triggered",
      commandHistory: [
        {
          id: `cmd-${Date.now()}`,
          command: "EMERGENCY STOP",
          timestamp: Date.now(),
          status: "aborted",
          result: "All automation killed immediately.",
        },
        ...get().commandHistory,
      ],
    });
  },

  clearHistory: () => {
    set({ commandHistory: [] });
  },

  executeCommand: async (text: string) => {
    const rawText = text.trim();
    if (!rawText) return;

    const lower = rawText.toLowerCase();
    const wake = get().wakeWord.toLowerCase();
    const isWake = lower.startsWith(wake) || lower.includes(wake);

    // Strip wake word for command execution
    const cleanCmd = isWake
      ? lower.replace(wake, "").replace(/^[,.:\s]+/, "").trim()
      : lower;

    set({
      isProcessing: true,
      currentTranscript: rawText,
      wakeWordDetected: isWake,
    });

    const cmdId = `cmd-${Date.now()}`;
    const logItem: VoiceCommandLog = {
      id: cmdId,
      command: rawText,
      timestamp: Date.now(),
      status: "pending",
    };
    set((s) => ({ commandHistory: [logItem, ...s.commandHistory] }));

    try {
      // 1. Emergency stop trigger
      if (cleanCmd.includes("emergency stop") || cleanCmd.includes("kill all") || cleanCmd.includes("abort")) {
        await get().emergencyStop();
        return;
      }

      // 2. Flight / Booking command
      if (cleanCmd.includes("book") && (cleanCmd.includes("flight") || cleanCmd.includes("ticket") || cleanCmd.includes("hotel"))) {
        set({
          isAutomating: true,
          activeAutomation: {
            type: "booking",
            progress: 25,
            current_step: 1,
            total_steps: 4,
            description: "Searching booking portals for optimal itineraries...",
          },
        });

        // Simulate step progression
        set({
          activeAutomation: {
            type: "booking",
            progress: 75,
            current_step: 3,
            total_steps: 4,
            description: "Filled reservation forms. Preparing checkout summary...",
          },
        });

        const bookRes = await api.post<any>("/api/rony/book", {
          service: cleanCmd.includes("hotel") ? "hotel" : "flight",
          details: { request: cleanCmd },
        });

        if (bookRes.confirmation_pending) {
          get().requestApproval(
            "Ticket Purchase Approval Required",
            "purchase_ticket",
            bookRes.details,
            bookRes.message
          );
        }

        set((s) => ({
          activeAutomation: null,
          isAutomating: false,
          commandHistory: s.commandHistory.map((c) =>
            c.id === cmdId ? { ...c, status: "approval_required", result: bookRes.message } : c
          ),
        }));
        return;
      }

      // 3. Web Research
      if (cleanCmd.startsWith("search") || cleanCmd.startsWith("research") || cleanCmd.includes("search for")) {
        const query = cleanCmd.replace(/^(search for|search|research)\s+/, "");
        set({
          isAutomating: true,
          activeAutomation: {
            type: "research",
            progress: 50,
            current_step: 1,
            total_steps: 2,
            description: `Searching web for: "${query}"...`,
          },
        });

        const res = await api.post<any>("/api/rony/research", { query, num_results: 5 });

        set((s) => ({
          isAutomating: false,
          activeAutomation: null,
          commandHistory: s.commandHistory.map((c) =>
            c.id === cmdId ? { ...c, status: "success", result: res.summary } : c
          ),
        }));
        return;
      }

      // 4. Screenshot / Vision Analysis
      if (cleanCmd.includes("screenshot") || cleanCmd.includes("screen") || cleanCmd.includes("error")) {
        set({
          isAutomating: true,
          activeAutomation: {
            type: "vision",
            progress: 50,
            current_step: 1,
            total_steps: 2,
            description: "Capturing screen and analyzing vision elements...",
          },
        });

        const res = await api.post<any>("/api/rony/analyze-screen", { question: rawText });

        set((s) => ({
          isAutomating: false,
          activeAutomation: null,
          commandHistory: s.commandHistory.map((c) =>
            c.id === cmdId ? { ...c, status: "success", result: res.answer } : c
          ),
        }));
        return;
      }

      // 5. Open Application
      if (cleanCmd.startsWith("open ")) {
        const appName = cleanCmd.replace(/^open\s+/, "").trim();
        const res = await api.post<any>("/api/rony/system-action", {
          action: "open_application",
          params: { app_name: appName },
        });

        set((s) => ({
          commandHistory: s.commandHistory.map((c) =>
            c.id === cmdId ? { ...c, status: "success", result: `Opened ${appName}` } : c
          ),
        }));
        return;
      }

      // 6. Minimize / Window Controls
      if (cleanCmd.includes("minimize")) {
        const res = await api.post<any>("/api/rony/system-action", {
          action: "minimize_window",
          params: { title: "all" },
        });

        set((s) => ({
          commandHistory: s.commandHistory.map((c) =>
            c.id === cmdId ? { ...c, status: "success", result: "Minimized windows" } : c
          ),
        }));
        return;
      }

      // 7. Generic System Action
      const genericRes = await api.post<any>("/api/rony/system-action", {
        action: cleanCmd,
        params: {},
      });

      if (genericRes.approval_required) {
        get().requestApproval(
          "Destructive Action Approval",
          cleanCmd,
          {},
          genericRes.message
        );
        return;
      }

      set((s) => ({
        commandHistory: s.commandHistory.map((c) =>
          c.id === cmdId ? { ...c, status: "success", result: JSON.stringify(genericRes) } : c
        ),
      }));
    } catch (err: any) {
      set((s) => ({
        commandHistory: s.commandHistory.map((c) =>
          c.id === cmdId ? { ...c, status: "aborted", result: err?.message || "Execution failed" } : c
        ),
      }));
    } finally {
      set({ isProcessing: false });
    }
  },
}));
