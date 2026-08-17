import { create } from "zustand";
import { api } from "../lib/api";
import { getPreset } from "../lib/providerPresets";
import type { ChatMessage, ModelDto } from "../types/api";
import { useWorkspaceStore } from "./workspaceStore";
import { useEditorStore } from "./editorStore";

// ── Extended types ────────────────────────────────────────────────────────────

export interface AgentStatus {
  type: "thinking" | "tool" | "step_complete" | "duo_escalation" | "proposal_created" | "approval_required" | "done" | "error";
  message: string;
  tool?: string;
  detail?: string;
  command?: string;
  step?: number;
  total?: number;
}

export interface PendingApprovalState {
  action_id: string;
  action_type: string; // "command" | "edit"
  command?: string;
  detail?: string;
  reason: string;
  proposal_id?: string;
  path?: string;
  diff_summary?: string;
}

export interface AgentPlan {
  steps: string[];
  current: number;
}

export interface ToolEvent {
  tool: string;
  arguments?: Record<string, string>;
  detail?: string;
  timestamp: string;
  success?: boolean;
  output_preview?: string;
}

export interface CommandExecution {
  command: string;
  output: string;
  exit_code: number;
  success: boolean;
}

export interface ExtendedChatMessage extends ChatMessage {
  id?: string;
  model?: string;
  attached_paths?: string[];
  created_at?: string;
  agentStatus?: AgentStatus | null;
  agentPlan?: AgentPlan | null;
  agentToolHistory?: ToolEvent[];
  commands?: CommandExecution[];
}

export interface ChatThread {
  id: string;
  workspace: string;
  title: string;
  created_at: string;
  updated_at: string;
}

type AIState = {
  /** Active preset ID (e.g. "ollama", "groq", "anthropic") */
  preset: string;
  /** Wire-protocol provider name sent to backend ("ollama" | "openai-compatible") */
  provider: string;
  /** Canonical key ID for api_keys table lookup */
  apiKeyProvider: string | null;
  model: string;
  baseUrl: string;
  messages: ExtendedChatMessage[];
  models: ModelDto[];
  streaming: boolean;
  error: string | null;

  // Agent mode state (Cursor/Antigravity-style autonomous loop)
  agentMode: boolean;
  agentStatus: AgentStatus | null;
  agentPlan: AgentPlan | null;
  agentToolHistory: ToolEvent[];
  pendingApproval: PendingApprovalState | null;
  pendingApprovals: PendingApprovalState[];

  // Multi-thread state
  currentThreadId: string | null;
  threads: ChatThread[];

  setPreset: (presetId: string, baseUrlOverride?: string, modelOverride?: string) => void;
  setModel: (model: string) => void;
  setBaseUrl: (baseUrl: string) => void;
  refreshModels: () => Promise<void>;
  stopGeneration: () => void;

  // Agent mode actions
  toggleAgentMode: () => void;
  setAgentMode: (enabled: boolean) => void;
  clearAgentState: () => void;
  approveAction: (actionId: string) => Promise<void>;
  rejectAction: (actionId: string) => Promise<void>;
  sendAgentMessage: (content: string, attachedPaths?: string[]) => Promise<void>;

  // Actions
  loadThreads: (workspace: string) => Promise<void>;
  switchThread: (threadId: string) => Promise<void>;
  newThread: (workspace?: string) => Promise<void>;
  renameThread: (threadId: string, title: string) => Promise<void>;
  deleteThread: (threadId: string) => Promise<void>;
  
  sendMessage: (content: string, attachedPaths?: string[]) => Promise<void>;
  regenerate: (messageIndex?: number) => Promise<void>;
  editMessage: (index: number, newContent: string) => Promise<void>;
  deleteMessagePair: (index: number) => Promise<void>;
};

let activeController: AbortController | null = null;

const savedPreset = typeof window !== "undefined" ? localStorage.getItem("code_os_ai_preset") || "auto" : "auto";
const savedPresetObj = getPreset(savedPreset);
const savedModel = typeof window !== "undefined" ? localStorage.getItem("code_os_ai_model") ?? (savedPresetObj?.model_example || "") : "";
const savedBaseUrl = typeof window !== "undefined" ? localStorage.getItem("code_os_ai_base_url") ?? (savedPresetObj?.base_url || "") : "";
const savedApiKeyProvider = typeof window !== "undefined" ? localStorage.getItem("code_os_ai_api_key_provider") ?? (savedPresetObj?.api_key_provider || null) : null;

export const useAIStore = create<AIState>((set, get) => ({
  preset: savedPreset,
  provider: savedPresetObj?.provider || "auto",
  apiKeyProvider: savedApiKeyProvider,
  model: savedModel,
  baseUrl: savedBaseUrl,
  messages: [],
  models: [],
  streaming: false,
  error: null,

  // Agent mode defaults (OFF by default)
  agentMode: false,
  agentStatus: null,
  agentPlan: null,
  agentToolHistory: [],
  pendingApproval: null,
  pendingApprovals: [],

  currentThreadId: null,
  threads: [],

  toggleAgentMode: () => {
    set((state) => ({ agentMode: !state.agentMode }));
  },

  setAgentMode: (enabled: boolean) => {
    set({ agentMode: enabled });
  },

  clearAgentState: () => {
    set({ agentStatus: null, agentPlan: null, agentToolHistory: [], pendingApproval: null, pendingApprovals: [] });
  },

  approveAction: async (actionId: string) => {
    try {
      await api.post(`/api/ai/chat-agent/approve/${actionId}`);
      set((state) => {
        const remaining = (state.pendingApprovals || []).filter((a) => a.action_id !== actionId);
        return {
          pendingApprovals: remaining,
          pendingApproval: remaining[0] || null,
        };
      });
    } catch (err) {
      console.error("Failed to approve action:", err);
    }
  },

  rejectAction: async (actionId: string) => {
    try {
      await api.post(`/api/ai/chat-agent/reject/${actionId}`);
      set((state) => {
        const remaining = (state.pendingApprovals || []).filter((a) => a.action_id !== actionId);
        return {
          pendingApprovals: remaining,
          pendingApproval: remaining[0] || null,
        };
      });
    } catch (err) {
      console.error("Failed to reject action:", err);
    }
  },

  setPreset: (presetId, baseUrlOverride, modelOverride) => {
    const p = getPreset(presetId);
    if (!p) return;
    const currentPreset = get().preset;
    const currentModel = get().model;
    const oldPresetObj = getPreset(currentPreset);
    const autoModel = modelOverride !== undefined
      ? modelOverride
      : (presetId !== currentPreset && (!currentModel || currentModel === oldPresetObj?.model_example))
        ? (p.model_example || "")
        : currentModel;
    const nextBaseUrl = baseUrlOverride ?? p.base_url ?? "";
    const nextApiKeyProvider = p.api_key_provider ?? null;

    if (typeof window !== "undefined") {
      localStorage.setItem("code_os_ai_preset", presetId);
      localStorage.setItem("code_os_ai_model", autoModel);
      localStorage.setItem("code_os_ai_base_url", nextBaseUrl);
      if (nextApiKeyProvider) {
        localStorage.setItem("code_os_ai_api_key_provider", nextApiKeyProvider);
      } else {
        localStorage.removeItem("code_os_ai_api_key_provider");
      }
    }

    set({
      preset: presetId,
      provider: p.provider,
      apiKeyProvider: nextApiKeyProvider,
      baseUrl: nextBaseUrl,
      model: autoModel,
      models: [],
    });
    void get().refreshModels();
  },

  setModel: (model) => {
    if (typeof window !== "undefined") {
      localStorage.setItem("code_os_ai_model", model);
    }
    set({ model });
  },

  setBaseUrl: (baseUrl) => {
    if (typeof window !== "undefined") {
      localStorage.setItem("code_os_ai_base_url", baseUrl);
    }
    set({ baseUrl });
  },

  refreshModels: async () => {
    const currentProvider = get().provider;
    const currentBaseUrl = get().baseUrl;
    const currentApiKeyProvider = get().apiKeyProvider;
    try {
      const models = await api.get<ModelDto[]>("/api/ai/models", {
        provider: currentProvider,
        base_url: currentBaseUrl,
        api_key_provider: currentApiKeyProvider,
      });
      // CRITICAL: NEVER overwrite user's selected model if it is already non-empty!
      const currentModel = get().model;
      if (!currentModel && models.length > 0) {
        const fallback = models[0]?.name || "";
        if (typeof window !== "undefined") {
          localStorage.setItem("code_os_ai_model", fallback);
        }
        set({ models, model: fallback });
      } else {
        // Just store the fetched models catalog without touching model!
        set({ models });
      }
    } catch {
      // Keep existing models array and current model on failure
    }
  },


  stopGeneration: () => {
    activeController?.abort();
    activeController = null;
    set({ streaming: false });
  },

  // ── Multi-thread actions ────────────────────────────────────────────────────

  loadThreads: async (workspace) => {
    try {
      const list = await api.get<ChatThread[]>("/api/ai/threads", { workspace });
      set({ threads: list });
      // Auto-load most recent thread if current is empty and list is not
      if (!get().currentThreadId && list.length > 0) {
        await get().switchThread(list[0].id);
      }
    } catch (err) {
      console.error("Failed to load threads:", err);
    }
  },

  switchThread: async (threadId) => {
    try {
      const messages = await api.get<ExtendedChatMessage[]>(`/api/ai/threads/${threadId}/messages`);
      set({ currentThreadId: threadId, messages, error: null });
    } catch (err) {
      set({ error: "Failed to switch thread" });
    }
  },

  newThread: async (workspace) => {
    set({
      currentThreadId: null,
      messages: [],
      error: null,
    });
  },

  renameThread: async (threadId, title) => {
    try {
      const updated = await api.put<ChatThread>(`/api/ai/threads/${threadId}`, { title });
      set((state) => ({
        threads: state.threads.map((t) => (t.id === threadId ? updated : t)),
      }));
    } catch (err) {
      console.error("Failed to rename thread:", err);
    }
  },

  deleteThread: async (threadId) => {
    try {
      await api.delete(`/api/ai/threads/${threadId}`);
      set((state) => {
        const nextThreads = state.threads.filter((t) => t.id !== threadId);
        const nextThreadId = state.currentThreadId === threadId ? nextThreads[0]?.id ?? null : state.currentThreadId;
        return {
          threads: nextThreads,
          currentThreadId: nextThreadId,
          messages: nextThreadId ? state.messages : [],
        };
      });
      // Switch if we changed current
      const nextId = get().currentThreadId;
      if (nextId) {
        await get().switchThread(nextId);
      }
    } catch (err) {
      console.error("Failed to delete thread:", err);
    }
  },

  // ── Message Actions ─────────────────────────────────────────────────────────

  sendMessage: async (content, attachedPaths = []) => {
    if (get().agentMode) {
      return get().sendAgentMessage(content, attachedPaths);
    }

    const workspace = useWorkspaceStore.getState().currentWorkspace?.path;
    const restrictedMode = useWorkspaceStore.getState().restrictedMode;
    
    if (!workspace) return;

    // Block AI file-write operations in restricted mode
    if (restrictedMode && (content.toLowerCase().includes("write") || content.toLowerCase().includes("edit") || content.toLowerCase().includes("modify") || content.toLowerCase().includes("change"))) {
      set({ error: "File operations are disabled in Restricted Mode. Switch to Trusted mode to enable AI file writes." });
      return;
    }

    let threadId = get().currentThreadId;
    if (!threadId) {
      // Auto-create thread
      const id = crypto.randomUUID();
      // Generate clean title from prompt preview
      const cleanTitle = content.trim().substring(0, 32) + (content.length > 32 ? "…" : "");
      try {
        const newT = await api.post<ChatThread>("/api/ai/threads", { id, workspace, title: cleanTitle });
        set((state) => ({
          currentThreadId: id,
          threads: [newT, ...state.threads],
        }));
        threadId = id;
      } catch {
        set({ error: "Failed to initialize thread" });
        return;
      }
    }

    // If it was the first user message, rename thread from default
    const activeThread = get().threads.find((t) => t.id === threadId);
    if (activeThread?.title === "New Conversation") {
      const cleanTitle = content.trim().substring(0, 32) + (content.length > 32 ? "…" : "");
      void get().renameThread(threadId, cleanTitle);
    }

    const userMessage: ExtendedChatMessage = {
      role: "user",
      content,
      attached_paths: attachedPaths,
      created_at: new Date().toISOString(),
    };
    const assistantMessage: ExtendedChatMessage = {
      role: "assistant",
      content: "",
      model: get().model,
      created_at: new Date().toISOString(),
    };

    activeController = new AbortController();
    set((state) => ({
      messages: [...state.messages, userMessage, assistantMessage],
      streaming: true,
      error: null,
    }));

    // Sync user message to db immediately
    try {
      await api.post(`/api/ai/threads/${threadId}/messages`, { messages: get().messages });
    } catch (err) {
      console.warn("Messages out of sync in DB:", err);
    }

    const requestMessages = get().messages.slice(0, -1).map((m) => ({
      role: m.role,
      content: m.content,
    }));

    const activePath = useEditorStore.getState().activePath;
    const openPaths = useEditorStore.getState().openFiles.map(f => f.path);
    const combinedAttachedPaths = Array.from(
      new Set([
        ...(activePath ? [activePath] : []),
        ...attachedPaths,
        ...openPaths,
      ])
    );

    let pendingBuffer = "";
    let flushTimer: ReturnType<typeof setTimeout> | null = null;

    const flushBuffer = () => {
      if (!pendingBuffer) return;
      const chunkToFlush = pendingBuffer;
      pendingBuffer = "";
      set((state) => {
        const messages = [...state.messages];
        const last = messages[messages.length - 1];
        if (last?.role === "assistant") {
          messages[messages.length - 1] = { ...last, content: last.content + chunkToFlush };
        }
        return { messages };
      });
    };

    try {
      await api.stream(
        "/api/ai/chat/stream",
        {
          provider: get().provider,
          model: get().model,
          base_url: get().baseUrl,
          api_key_provider: get().apiKeyProvider,
          messages: requestMessages,
          attached_paths: combinedAttachedPaths,
          workspace,
        },
        (token) => {
          if (token.includes("[EDIT_PROPOSAL_CREATED:")) {
            window.dispatchEvent(new CustomEvent("code-os:proposal-created"));
          }
          pendingBuffer += token;
          if (!flushTimer) {
            flushTimer = setTimeout(() => {
              flushTimer = null;
              flushBuffer();
            }, 60);
          }
        },
        activeController.signal
      );

      if (flushTimer) {
        clearTimeout(flushTimer);
        flushTimer = null;
      }
      flushBuffer();

      // Sync final response to db
      await api.post(`/api/ai/threads/${threadId}/messages`, { messages: get().messages });
    } catch (error) {
      if (flushTimer) clearTimeout(flushTimer);
      flushBuffer();
      if (!(error instanceof DOMException && error.name === "AbortError")) {
        set({ error: error instanceof Error ? error.message : "AI request failed" });
      }
    } finally {
      activeController = null;
      set({ streaming: false });
    }
  },

  sendAgentMessage: async (content, attachedPaths = []) => {
    const workspace = useWorkspaceStore.getState().currentWorkspace?.path;
    const restrictedMode = useWorkspaceStore.getState().restrictedMode;
    
    if (!workspace) return;

    if (restrictedMode && (content.toLowerCase().includes("write") || content.toLowerCase().includes("edit") || content.toLowerCase().includes("modify") || content.toLowerCase().includes("change"))) {
      set({ error: "File operations are disabled in Restricted Mode. Switch to Trusted mode to enable AI file writes." });
      return;
    }

    let threadId = get().currentThreadId;
    if (!threadId) {
      const id = crypto.randomUUID();
      const cleanTitle = content.trim().substring(0, 32) + (content.length > 32 ? "…" : "");
      try {
        const newT = await api.post<ChatThread>("/api/ai/threads", { id, workspace, title: cleanTitle });
        set((state) => ({
          currentThreadId: id,
          threads: [newT, ...state.threads],
        }));
        threadId = id;
      } catch {
        set({ error: "Failed to initialize thread" });
        return;
      }
    }

    const activeThread = get().threads.find((t) => t.id === threadId);
    if (activeThread?.title === "New Conversation") {
      const cleanTitle = content.trim().substring(0, 32) + (content.length > 32 ? "…" : "");
      void get().renameThread(threadId, cleanTitle);
    }

    const userMessage: ExtendedChatMessage = {
      role: "user",
      content,
      attached_paths: attachedPaths,
      created_at: new Date().toISOString(),
    };
    const assistantMessage: ExtendedChatMessage = {
      role: "assistant",
      content: "",
      model: get().model,
      created_at: new Date().toISOString(),
      agentStatus: { type: "thinking", message: "Starting agent..." },
      agentPlan: null,
      agentToolHistory: [],
    };

    activeController = new AbortController();
    set((state) => ({
      messages: [...state.messages, userMessage, assistantMessage],
      streaming: true,
      error: null,
      agentStatus: { type: "thinking", message: "Analyzing request..." },
      agentPlan: null,
      agentToolHistory: [],
    }));

    try {
      await api.post(`/api/ai/threads/${threadId}/messages`, { messages: get().messages });
    } catch (err) {
      console.warn("Messages out of sync in DB:", err);
    }

    const requestMessages = get().messages.slice(0, -1).map((m) => ({
      role: m.role,
      content: m.content,
    }));

    const activePath = useEditorStore.getState().activePath;
    const openPaths = useEditorStore.getState().openFiles.map(f => f.path);
    const combinedAttachedPaths = Array.from(
      new Set([
        ...(activePath ? [activePath] : []),
        ...attachedPaths,
        ...openPaths,
      ])
    );

    try {
      await api.streamSSE(
        "/api/ai/chat-agent/stream",
        {
          provider: get().provider,
          model: get().model,
          base_url: get().baseUrl,
          api_key_provider: get().apiKeyProvider,
          messages: requestMessages,
          attached_paths: combinedAttachedPaths,
          workspace,
          agent_mode: true,
        },
        (eventType, data: any) => {
          if (eventType === "status") {
            const statusObj: AgentStatus = {
              type: data.type || "thinking",
              message: data.message || "",
              tool: data.tool,
              detail: data.detail,
              command: data.command,
              step: data.step,
              total: data.total,
            };
            set((state) => {
              const messages = [...state.messages];
              const last = messages[messages.length - 1];
              if (last && last.role === "assistant") {
                messages[messages.length - 1] = { ...last, agentStatus: statusObj };
              }
              const newHistory = [...state.agentToolHistory];
              if (statusObj.type === "tool" && statusObj.tool) {
                newHistory.push({
                  tool: statusObj.tool,
                  detail: statusObj.detail,
                  timestamp: new Date().toISOString(),
                });
              }
              return { agentStatus: statusObj, agentToolHistory: newHistory, pendingApproval: statusObj.type === "tool" ? null : state.pendingApproval, messages };
            });
          } else if (eventType === "plan") {
            const planObj: AgentPlan = {
              steps: data.steps || [],
              current: data.current || 0,
            };
            set((state) => {
              const messages = [...state.messages];
              const last = messages[messages.length - 1];
              if (last && last.role === "assistant") {
                messages[messages.length - 1] = { ...last, agentPlan: planObj };
              }
              return { agentPlan: planObj, messages };
            });
          } else if (eventType === "token") {
            const tokenStr = typeof data === "string" ? data : (data.content || "");
            set((state) => {
              const messages = [...state.messages];
              const last = messages[messages.length - 1];
              if (last && last.role === "assistant") {
                messages[messages.length - 1] = { ...last, content: last.content + tokenStr };
              }
              return { messages };
            });
          } else if (eventType === "proposal") {
            window.dispatchEvent(new CustomEvent("code-os:proposal-created"));
          } else if (eventType === "command_result") {
            const cmdResult: CommandExecution = {
              command: data.command || "",
              output: data.output || "",
              exit_code: typeof data.exit_code === "number" ? data.exit_code : (data.success ? 0 : 1),
              success: data.success ?? true,
            };
            set((state) => {
              const messages = [...state.messages];
              const last = messages[messages.length - 1];
              const toolEntry = {
                tool: "run_command",
                detail: cmdResult.command,
                timestamp: new Date().toISOString(),
                success: cmdResult.success,
              };
              const updatedHistory = [...state.agentToolHistory, toolEntry];
              if (last && last.role === "assistant") {
                const existing = last.commands || [];
                messages[messages.length - 1] = {
                  ...last,
                  commands: [...existing, cmdResult],
                  agentToolHistory: updatedHistory,
                };
              }
              return { messages, agentToolHistory: updatedHistory, pendingApproval: null, pendingApprovals: [] };
            });
          } else if (eventType === "approval_request") {
            const approvalObj: PendingApprovalState = {
              action_id: data.action_id,
              action_type: data.action_type || "command",
              command: data.command || "",
              detail: data.detail || data.command || data.path || "",
              reason: data.reason || "Action requires user approval",
              proposal_id: data.proposal_id,
              path: data.path,
              diff_summary: data.diff_summary,
            };
            set((state) => {
              const currentList = state.pendingApprovals || [];
              const list = [...currentList.filter((a) => a.action_id !== approvalObj.action_id), approvalObj];
              return {
                pendingApprovals: list,
                pendingApproval: list[0] || approvalObj,
                agentStatus: {
                  type: "approval_required",
                  message: data.reason || "Approval required",
                  command: data.command,
                  detail: data.path || data.detail,
                },
              };
            });
          } else if (eventType === "error") {
            const errMsg = typeof data === "string" ? data : (data.message || "Agent error");
            set({ error: errMsg, pendingApproval: null, pendingApprovals: [] });
          } else if (eventType === "done") {
            set((state) => {
              const messages = [...state.messages];
              const last = messages[messages.length - 1];
              if (last && last.role === "assistant") {
                messages[messages.length - 1] = {
                  ...last,
                  agentStatus: { type: "done", message: data.message || "Task completed" },
                  agentToolHistory: state.agentToolHistory,
                };
              }
              return {
                agentStatus: { type: "done", message: data.message || "Task completed" },
                pendingApproval: null,
                pendingApprovals: [],
                messages,
              };
            });
          }
        },
        activeController.signal
      );

      // Sync final response to db
      await api.post(`/api/ai/threads/${threadId}/messages`, { messages: get().messages });
    } catch (error) {
      if (!(error instanceof DOMException && error.name === "AbortError")) {
        set({ error: error instanceof Error ? error.message : "Agent request failed" });
      }
    } finally {
      activeController = null;
      set({ streaming: false });
    }
  },

  regenerate: async () => {
    const threadId = get().currentThreadId;
    if (!threadId) return;

    const messages = get().messages;
    // Find index of the last user query
    const lastUserIndex = [...messages].reverse().findIndex((m) => m.role === "user");
    if (lastUserIndex === -1) return;
    const actualIndex = messages.length - 1 - lastUserIndex;

    const lastUser = messages[actualIndex];
    // Truncate message history from user message
    const nextMessages = messages.slice(0, actualIndex);
    set({ messages: nextMessages });

    // Re-send query
    await get().sendMessage(lastUser.content, lastUser.attached_paths);
  },

  editMessage: async (index, newContent) => {
    const threadId = get().currentThreadId;
    if (!threadId) return;

    const messages = get().messages;
    const targetMessage = messages[index];
    if (!targetMessage || targetMessage.role !== "user") return;

    // Truncate list from this user message onwards
    const nextMessages = messages.slice(0, index);
    set({ messages: nextMessages });

    // Sync truncation to backend immediately to clean up subsequent history
    try {
      await api.post(`/api/ai/threads/${threadId}/messages`, { messages: nextMessages });
    } catch {}

    // Send edited content
    await get().sendMessage(newContent, targetMessage.attached_paths);
  },

  deleteMessagePair: async (index) => {
    const threadId = get().currentThreadId;
    if (!threadId) return;

    const messages = [...get().messages];
    // Delete the clicked message and the next assistant message if it is pair
    const nextAssistantIdx = index + 1;
    if (messages[nextAssistantIdx]?.role === "assistant") {
      messages.splice(index, 2);
    } else {
      messages.splice(index, 1);
    }

    set({ messages });
    try {
      await api.post(`/api/ai/threads/${threadId}/messages`, { messages });
    } catch {}
  },
}));
