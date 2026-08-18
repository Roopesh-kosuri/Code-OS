import { create } from "zustand";
import { api } from "../lib/api";
import { getPreset } from "../lib/providerPresets";
import { getDefaultVisionModel } from "../lib/models";
import type { ChatMessage, ModelDto } from "../types/api";
import { useWorkspaceStore } from "./workspaceStore";
import { useEditorStore } from "./editorStore";

// ── Extended types ────────────────────────────────────────────────────────────

export interface DAGPlanStep {
  id: string;
  title: string;
  status: "pending" | "running" | "done" | "failed" | "blocked";
  depends_on?: string[];
}

export interface AgentStatus {
  type:
    | "thinking"
    | "tool"
    | "step_complete"
    | "duo_escalation"
    | "proposal_created"
    | "approval_required"
    | "done"
    | "error"
    | "tier_routing"
    | "ask_user"
    | "memory_updated"
    | "verified_disk"
    | "self_critique"
    | "secret_scan"
    | "regression_guard"
    | "tool_skipped"
    | "replan"
    | "partial_report"
    | "audit"
    | "vision";
  message: string;
  tool?: string;
  detail?: string;
  command?: string;
  step?: number;
  total?: number;
  tier?: number;
  label?: string;
  action_id?: string;
  options?: string[];
  confirmed?: boolean;
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
  is_native_fallback?: boolean;
}

export interface PendingUserResponseState {
  action_id: string;
  question: string;
  options: string[];
}

export interface AgentPlan {
  steps: (string | DAGPlanStep)[];
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

export interface AttachedImage {
  name: string;
  dataUrl: string;
  size?: number;
  type?: string;
}

export interface CheckpointInfo {
  turn_number: number;
  commit_hash: string;
  touched_files: string[];
  undone?: boolean;
}

export interface InterruptedState {
  user_query: string;
  tier: number;
  iteration: number;
  max_iterations: number;
  messages: { role: string; content: string }[];
  dag_plan_steps: DAGPlanStep[];
  staged_changes: { path: string; original: string; updated: string }[];
  tokens_used: number;
  tools_executed: number;
  timestamp: string;
}

export interface ActivityLogEntry {
  timestamp: string;
  action_type: string;
  target: string;
  outcome: string;
  tier?: number;
  token_count?: number;
  details?: string;
}

export interface ExtendedChatMessage extends ChatMessage {
  id?: string;
  model?: string;
  attached_paths?: string[];
  attached_images?: AttachedImage[];
  created_at?: string;
  agentStatus?: AgentStatus | null;
  agentPlan?: AgentPlan | null;
  agentToolHistory?: ToolEvent[];
  commands?: CommandExecution[];
  checkpoint?: CheckpointInfo;
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
  visionModel: string;
  baseUrl: string;
  messages: ExtendedChatMessage[];
  models: ModelDto[];
  streaming: boolean;
  error: string | null;

  // Agent mode & Adaptive Routing state
  agentMode: boolean;
  currentTier: number | null;
  currentTierLabel: string | null;
  currentTierReason: string | null;
  currentTokensUsed: number | null;
  interruptedState: InterruptedState | null;
  agentStatus: AgentStatus | null;
  agentPlan: AgentPlan | null;
  agentToolHistory: ToolEvent[];
  pendingApproval: PendingApprovalState | null;
  pendingApprovals: PendingApprovalState[];
  pendingUserResponse: PendingUserResponseState | null;
  streamStartTimestamp: number | null;
  lastTokenTimestamp: number | null;

  // Multi-thread state
  currentThreadId: string | null;
  threads: ChatThread[];

  setPreset: (presetId: string, baseUrlOverride?: string, modelOverride?: string) => void;
  setModel: (model: string) => void;
  setVisionModel: (visionModel: string) => void;
  setBaseUrl: (baseUrl: string) => void;
  refreshModels: () => Promise<void>;
  stopGeneration: () => void;

  // Agent mode & interaction actions
  toggleAgentMode: () => void;
  setAgentMode: (enabled: boolean) => void;
  clearAgentState: () => void;
  clearPendingUserResponse: () => void;
  checkInterruptedState: (workspace?: string) => Promise<void>;
  resumeInterruptedRun: (workspace?: string) => Promise<void>;
  dismissInterruptedState: (workspace?: string) => Promise<void>;
  approveAction: (actionId: string, alwaysAllow?: boolean, trustPattern?: string) => Promise<void>;
  rejectAction: (actionId: string) => Promise<void>;
  respondToUserQuestion: (actionId: string, answer: string) => Promise<void>;
  sendAgentMessage: (content: string, attachedPaths?: string[]) => Promise<void>;
  undoTurn: (commitHash: string, touchedFiles: string[]) => Promise<{ success: boolean; message: string; restored_files: string[] }>;

  // Actions
  loadThreads: (workspace?: string) => Promise<void>;
  switchThread: (threadId: string) => Promise<void>;
  newThread: (workspace?: string) => Promise<void>;
  renameThread: (threadId: string, title: string) => Promise<void>;
  deleteThread: (threadId: string) => Promise<void>;
  
  sendMessage: (content: string, attachedPaths?: string[], attachedImages?: AttachedImage[]) => Promise<void>;
  regenerate: (messageIndex?: number) => Promise<void>;
  editMessage: (index: number, newContent: string) => Promise<void>;
  deleteMessagePair: (index: number) => Promise<void>;
};

let activeController: AbortController | null = null;

const savedPreset = typeof window !== "undefined" ? localStorage.getItem("code_os_ai_preset") || "auto" : "auto";
const savedPresetObj = getPreset(savedPreset);
const savedModel = typeof window !== "undefined" ? localStorage.getItem("code_os_ai_model") ?? (savedPresetObj?.model_example || "") : "";
const savedVisionModel = typeof window !== "undefined" ? localStorage.getItem("code_os_ai_vision_model") ?? getDefaultVisionModel(savedPreset) : getDefaultVisionModel(savedPreset);
const savedBaseUrl = typeof window !== "undefined" ? localStorage.getItem("code_os_ai_base_url") ?? (savedPresetObj?.base_url || "") : "";
const savedApiKeyProvider = typeof window !== "undefined" ? localStorage.getItem("code_os_ai_api_key_provider") ?? (savedPresetObj?.api_key_provider || null) : null;

export const useAIStore = create<AIState>((set, get) => ({
  preset: savedPreset,
  provider: savedPresetObj?.provider || "auto",
  apiKeyProvider: savedApiKeyProvider,
  model: savedModel,
  visionModel: savedVisionModel,
  baseUrl: savedBaseUrl,
  messages: [],
  models: [],
  streaming: false,
  error: null,

  // Agent mode defaults (OFF by default)
  agentMode: false,
  currentTier: null,
  currentTierLabel: null,
  currentTierReason: null,
  currentTokensUsed: null,
  interruptedState: null,
  agentStatus: null,
  agentPlan: null,
  agentToolHistory: [],
  pendingApproval: null,
  pendingApprovals: [],
  pendingUserResponse: null,
  streamStartTimestamp: null,
  lastTokenTimestamp: null,

  currentThreadId: null,
  threads: [],

  toggleAgentMode: () => {
    set((state) => ({ agentMode: !state.agentMode }));
  },

  setAgentMode: (enabled: boolean) => {
    set({ agentMode: enabled });
  },

  clearAgentState: () => {
    set({
      currentTier: null,
      currentTierLabel: null,
      currentTierReason: null,
      currentTokensUsed: null,
      interruptedState: null,
      agentStatus: null,
      agentPlan: null,
      agentToolHistory: [],
      pendingApproval: null,
      pendingApprovals: [],
      pendingUserResponse: null,
    });
  },

  clearPendingUserResponse: () => {
    set({ pendingUserResponse: null });
  },

  checkInterruptedState: async (workspace) => {
    const ws = workspace || useWorkspaceStore.getState().currentWorkspace?.path || "";
    if (!ws) return;
    try {
      const res = await api.get<{ has_interrupted: boolean; state: InterruptedState | null }>(
        `/api/ai/chat-agent/interrupted-state?workspace=${encodeURIComponent(ws)}`
      );
      set({ interruptedState: res.has_interrupted ? res.state : null });
    } catch {
      set({ interruptedState: null });
    }
  },

  resumeInterruptedRun: async (workspace) => {
    const ws = workspace || useWorkspaceStore.getState().currentWorkspace?.path || "";
    const state = get().interruptedState;
    if (!ws || !state) return;
    set({ streaming: true, error: null, interruptedState: null, agentMode: true });

    try {
      const controller = new AbortController();
      activeController = controller;

      // Add resumed assistant placeholder if needed
      const msgs = get().messages;
      if (msgs.length === 0 || msgs[msgs.length - 1].role !== "assistant") {
        set({
          messages: [
            ...msgs,
            {
              role: "assistant",
              content: "",
              agentStatus: { type: "thinking", message: `Resuming task from step ${state.iteration + 1}...` },
            },
          ],
        });
      }

      await api.streamSSE(
        "/api/ai/chat-agent/resume",
        {
          workspace: ws,
          provider: get().provider,
          model: get().model,
          base_url: get().baseUrl || undefined,
          api_key_provider: get().apiKeyProvider || undefined,
        },
        (eventType: string, data: any) => {
          if (eventType === "tier_routing") {
            const tierVal = typeof data.tier === "number" ? data.tier : 0;
            const labelVal = data.label || (tierVal === 0 ? "Fast path" : (tierVal === 1 ? "Quick task" : "Deep think"));
            set({ currentTier: tierVal, currentTierLabel: labelVal, currentTierReason: data.reason || labelVal });
          } else if (eventType === "metrics") {
            if (typeof data.tokens_used === "number") {
              set({ currentTokensUsed: data.tokens_used });
            }
          } else if (eventType === "status") {
            const statusObj: AgentStatus = {
              type: data.type || "thinking",
              message: data.message || "",
              tool: data.tool,
              detail: data.detail,
              command: data.command,
              tier: data.tier,
              label: data.label,
            };
            set((s) => {
              const messages = [...s.messages];
              const last = messages[messages.length - 1];
              if (last && last.role === "assistant") {
                messages[messages.length - 1] = { ...last, agentStatus: statusObj };
              }
              return { agentStatus: statusObj, messages };
            });
          } else if (eventType === "token") {
            const tokenStr = typeof data === "string" ? data : (data.content || "");
            set((s) => {
              const messages = [...s.messages];
              const last = messages[messages.length - 1];
              if (last && last.role === "assistant") {
                messages[messages.length - 1] = { ...last, content: last.content + tokenStr };
              }
              return { messages };
            });
          } else if (eventType === "done") {
            set({ streaming: false, interruptedState: null });
          }
        },
        controller.signal
      );
    } catch (err: any) {
      if (err.name !== "AbortError") {
        set({ error: err.message || "Failed to resume interrupted run", streaming: false });
      }
    } finally {
      activeController = null;
      set({ streaming: false });
    }
  },

  dismissInterruptedState: async (workspace) => {
    const ws = workspace || useWorkspaceStore.getState().currentWorkspace?.path || "";
    if (!ws) return;
    try {
      await api.delete(`/api/ai/chat-agent/interrupted-state?workspace=${encodeURIComponent(ws)}`);
    } catch {}
    set({ interruptedState: null });
  },

  approveAction: async (actionId: string, alwaysAllow: boolean = false, trustPattern?: string) => {
    try {
      await api.post(`/api/ai/chat-agent/approve/${actionId}`, {
        always_allow: alwaysAllow,
        trust_pattern: trustPattern,
      });
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

  undoTurn: async (commitHash: string, touchedFiles: string[]) => {
    const workspace = useWorkspaceStore.getState().currentWorkspace?.path || "";
    try {
      const res = await api.post<{ success: boolean; message: string; restored_files: string[] }>(
        "/api/ai/chat-agent/undo-turn",
        {
          workspace,
          commit_hash: commitHash,
          touched_files: touchedFiles,
        }
      );
      set((state) => {
        const messages = state.messages.map((m) => {
          if (m.checkpoint?.commit_hash === commitHash) {
            return {
              ...m,
              checkpoint: { ...m.checkpoint, undone: true },
            };
          }
          return m;
        });
        return { messages };
      });
      return res;
    } catch (err) {
      console.error("Failed to undo turn:", err);
      throw err;
    }
  },

  respondToUserQuestion: async (actionId: string, answer: string) => {
    // Optimistically dismiss the clarification card immediately so it vanishes without lag
    set({ pendingUserResponse: null });
    try {
      await api.post(`/api/ai/chat-agent/respond/${actionId}`, { answer });
    } catch (err) {
      console.warn("Failed to submit in-stream response or action expired:", err);
      // Fallback: if the in-stream listener already closed, fallback to sending as a normal user message
      if (!get().streaming) {
        void get().sendMessage(answer);
      }
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

  setVisionModel: (visionModel) => {
    if (typeof window !== "undefined") {
      localStorage.setItem("code_os_ai_vision_model", visionModel);
    }
    set({ visionModel });
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
      const currentModel = get().model;
      if (!currentModel && models.length > 0) {
        const fallback = models[0]?.name || "";
        if (typeof window !== "undefined") {
          localStorage.setItem("code_os_ai_model", fallback);
        }
        set({ models, model: fallback });
      } else {
        set({ models });
      }
    } catch {
      // Keep existing models on failure
    }
  },

  stopGeneration: () => {
    activeController?.abort();
    activeController = null;
    void api.post("/api/ai/chat-agent/cancel").catch(() => {});
    set({ streaming: false, pendingUserResponse: null, pendingApproval: null, pendingApprovals: [], streamStartTimestamp: null, lastTokenTimestamp: null });
  },

  // ── Multi-thread actions ────────────────────────────────────────────────────

  loadThreads: async (workspace?: string) => {
    try {
      const list = await api.get<ChatThread[]>("/api/ai/threads", workspace ? { workspace } : undefined);
      set({ threads: list });
      const lastActiveId = typeof window !== "undefined" ? localStorage.getItem("code-os:active-chat-thread-id") : null;
      if (lastActiveId && list.some((t) => t.id === lastActiveId)) {
        await get().switchThread(lastActiveId);
      } else if (!get().currentThreadId && list.length > 0) {
        await get().switchThread(list[0].id);
      }
    } catch (err) {
      console.error("Failed to load threads:", err);
    }
  },

  switchThread: async (threadId) => {
    try {
      if (typeof window !== "undefined") {
        localStorage.setItem("code-os:active-chat-thread-id", threadId);
      }
      const messages = await api.get<ExtendedChatMessage[]>(`/api/ai/threads/${threadId}/messages`);
      set({ currentThreadId: threadId, messages, error: null, pendingUserResponse: null, pendingApproval: null, pendingApprovals: [] });
    } catch (err) {
      set({ error: "Failed to switch thread" });
    }
  },

  newThread: async (workspace) => {
    if (typeof window !== "undefined") {
      localStorage.removeItem("code-os:active-chat-thread-id");
    }
    set({
      currentThreadId: null,
      messages: [],
      error: null,
      pendingUserResponse: null,
      pendingApproval: null,
      pendingApprovals: [],
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
      if (typeof window !== "undefined" && localStorage.getItem("code-os:active-chat-thread-id") === threadId) {
        localStorage.removeItem("code-os:active-chat-thread-id");
      }
      set((state) => {
        const nextThreads = state.threads.filter((t) => t.id !== threadId);
        const nextThreadId = state.currentThreadId === threadId ? nextThreads[0]?.id ?? null : state.currentThreadId;
        return {
          threads: nextThreads,
          currentThreadId: nextThreadId,
          messages: nextThreadId ? state.messages : [],
        };
      });
      const nextId = get().currentThreadId;
      if (nextId) {
        await get().switchThread(nextId);
      }
    } catch (err) {
      console.error("Failed to delete thread:", err);
    }
  },

  // ── Message Actions with Adaptive Tier Routing ──────────────────────────────

  sendMessage: async (content, attachedPaths = [], attachedImages = []) => {
    const workspace = useWorkspaceStore.getState().currentWorkspace?.path || "";
    const restrictedMode = useWorkspaceStore.getState().restrictedMode;
    
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
        if (typeof window !== "undefined") {
          localStorage.setItem("code-os:active-chat-thread-id", id);
        }
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
      attached_images: attachedImages,
      created_at: new Date().toISOString(),
    };
    const assistantMessage: ExtendedChatMessage = {
      role: "assistant",
      content: "",
      model: get().model,
      created_at: new Date().toISOString(),
      agentStatus: { type: "thinking", message: "Connecting..." },
      agentPlan: null,
      agentToolHistory: [],
    };

    activeController = new AbortController();
    const now = Date.now();
    set((state) => ({
      messages: [...state.messages, userMessage, assistantMessage],
      streaming: true,
      error: null,
      streamStartTimestamp: now,
      lastTokenTimestamp: now,
      agentStatus: { type: "thinking", message: "Connecting..." },
      agentPlan: null,
      agentToolHistory: [],
      pendingUserResponse: null,
      pendingApproval: null,
      pendingApprovals: [],
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
          attached_images: attachedImages,
          workspace,
          agent_mode: get().agentMode,
          vision_model: get().visionModel,
        },
        (eventType, data: any) => {
          if (eventType === "tier_routing") {
            const tierVal = typeof data.tier === "number" ? data.tier : 0;
            const labelVal = data.label || (tierVal === 0 ? "Fast Answer" : (tierVal === 1 ? "Quick Task" : "Deep think"));
            const reasonVal = data.reason || labelVal;
            set({
              currentTier: tierVal,
              currentTierLabel: labelVal,
              currentTierReason: reasonVal,
            });
          } else if (eventType === "status") {
            const statusObj: AgentStatus = {
              type: data.type || "thinking",
              message: data.message || "",
              tool: data.tool,
              detail: data.detail,
              command: data.command,
              step: data.step,
              total: data.total,
              tier: data.tier,
              label: data.label,
              action_id: data.action_id,
              options: data.options,
              confirmed: data.confirmed,
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
          } else if (eventType === "ask_user" || eventType === "question") {
            const askObj: PendingUserResponseState = {
              action_id: data.action_id,
              question: data.question || "Please select an option:",
              options: data.options || [],
            };
            set({ pendingUserResponse: askObj });
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
            const now = Date.now();
            set((state) => {
              const messages = [...state.messages];
              const last = messages[messages.length - 1];
              if (last && last.role === "assistant") {
                messages[messages.length - 1] = { ...last, content: last.content + tokenStr };
              }
              return { messages, lastTokenTimestamp: now };
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
          } else if (eventType === "checkpoint") {
            const checkpointObj: CheckpointInfo = {
              turn_number: data.turn_number || 1,
              commit_hash: data.commit_hash || "",
              touched_files: data.touched_files || [],
            };
            set((state) => {
              const messages = [...state.messages];
              const last = messages[messages.length - 1];
              if (last && last.role === "assistant") {
                messages[messages.length - 1] = { ...last, checkpoint: checkpointObj };
              }
              return { messages };
            });
          } else if (eventType === "metrics") {
            if (typeof data.tokens_used === "number") {
              set({ currentTokensUsed: data.tokens_used });
            }
          } else if (eventType === "error") {
            const errMsg = typeof data === "string" ? data : (data.message || "Agent error");
            set({ error: errMsg, pendingApproval: null, pendingApprovals: [], pendingUserResponse: null });
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
                pendingUserResponse: null,
                messages,
              };
            });
          }
        },
        activeController.signal
      );

      await api.post(`/api/ai/threads/${threadId}/messages`, { messages: get().messages });
    } catch (error) {
      if (!(error instanceof DOMException && error.name === "AbortError")) {
        set({ error: error instanceof Error ? error.message : "Agent request failed" });
      }
    } finally {
      activeController = null;
      set({ streaming: false, pendingUserResponse: null, streamStartTimestamp: null, lastTokenTimestamp: null });
    }
  },

  sendAgentMessage: async (content, attachedPaths = []) => {
    return get().sendMessage(content, attachedPaths);
  },

  regenerate: async () => {
    const threadId = get().currentThreadId;
    if (!threadId) return;

    const messages = get().messages;
    const lastUserIndex = [...messages].reverse().findIndex((m) => m.role === "user");
    if (lastUserIndex === -1) return;
    const actualIndex = messages.length - 1 - lastUserIndex;

    const lastUser = messages[actualIndex];
    const nextMessages = messages.slice(0, actualIndex);
    set({ messages: nextMessages });

    await get().sendMessage(lastUser.content, lastUser.attached_paths);
  },

  editMessage: async (index, newContent) => {
    const threadId = get().currentThreadId;
    if (!threadId) return;

    const messages = get().messages;
    const targetMsg = messages[index];
    if (!targetMsg || targetMsg.role !== "user") return;

    const nextMessages = messages.slice(0, index);
    set({ messages: nextMessages });

    await get().sendMessage(newContent, targetMsg.attached_paths);
  },

  deleteMessagePair: async (index) => {
    const threadId = get().currentThreadId;
    if (!threadId) return;

    const messages = get().messages;
    const nextMessages = [...messages];
    if (nextMessages[index]?.role === "user") {
      if (nextMessages[index + 1]?.role === "assistant") {
        nextMessages.splice(index, 2);
      } else {
        nextMessages.splice(index, 1);
      }
    } else {
      nextMessages.splice(index, 1);
    }

    set({ messages: nextMessages });
    try {
      await api.post(`/api/ai/threads/${threadId}/messages`, { messages: nextMessages });
    } catch (err) {
      console.warn("Failed to sync message deletion to DB:", err);
    }
  },
}));
