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
    | "thinking_progress"
    | "retry"
    | "tool"
    | "tool_result"
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
    | "tool_error"
    | "replan"
    | "partial_report"
    | "audit"
    | "vision"
    | "browser_open"
    | "browser_verify"
    | "browser_repair";
  message: string;
  tool?: string;
  detail?: string;
  command?: string;
  reason?: string;
  step?: number;
  total?: number;
  tier?: number;
  label?: string;
  action_id?: string;
  options?: string[];
  confirmed?: boolean;
  tokens?: number;
  retry_delay_seconds?: number;
  is_rate_limit?: boolean;
  attempt?: number;
  max_attempts?: number;
  success?: boolean;
  output?: string;
  screenshot_path?: string;
  screenshot_base64?: string;
  outcome?: string;
}

export interface SuggestedRecoveryModel {
  provider: string;
  model: string;
  name: string;
}

export interface AIRecoveryPayload {
  error: string;
  provider?: string;
  model?: string;
  category?: string;
  http_status?: number;
  error_body?: string;
  is_auth_error?: boolean;
  is_404?: boolean;
  is_429?: boolean;
  is_context_overflow?: boolean;
  suggested_models?: SuggestedRecoveryModel[];
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
  state?: "running" | "completed" | "failed" | "skipped";
  reason?: string;
  screenshot_path?: string;
  screenshot_base64?: string;
}

export interface CommandExecution {
  command: string;
  output: string;
  exit_code: number;
  success: boolean;
  reason?: string;
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

export interface TokenUsageStatus {
  provider: string;
  date: string;
  used_tokens: number;
  daily_limit: number;
  remaining_tokens: number;
  percent_used: number;
}

export interface ProviderHealthStatus {
  provider: string;
  status: "healthy" | "degraded" | "circuit_open";
  status_label: string;
  total_requests_last_hour: number;
  failures_last_hour: number;
  failure_rate: number;
  consecutive_failures: number;
  circuit_open: boolean;
  cooldown_remaining_seconds: number;
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
  retryStatus: { message: string; retry_delay_seconds?: number; attempt?: number; max_attempts?: number; is_rate_limit?: boolean } | null;
  recoveryPayload: AIRecoveryPayload | null;
  clearRecovery: () => void;
  interruptedState: InterruptedState | null;
  agentStatus: AgentStatus | null;
  agentPlan: AgentPlan | null;
  agentToolHistory: ToolEvent[];
  pendingApproval: PendingApprovalState | null;
  pendingApprovals: PendingApprovalState[];
  pendingUserResponse: PendingUserResponseState | null;
  interruptedTasks: any[];
  fetchInterruptedTasks: () => Promise<void>;
  streamStartTimestamp: number | null;
  lastTokenTimestamp: number | null;

  // Multi-thread state
  currentThreadId: string | null;
  threads: ChatThread[];

  // Token usage & provider health tracking
  tokenUsage: Record<string, TokenUsageStatus> | null;
  providerHealth: Record<string, ProviderHealthStatus> | null;
  fetchTokenUsage: () => Promise<void>;
  fetchProviderHealth: () => Promise<void>;

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

/**
 * Shared SSE event dispatcher with 50ms token batching to eliminate React re-render churn.
 * Preserves exact wire protocol and event names: tier_routing, status, ask_user, plan, token,
 * proposal, command_result, approval_request, checkpoint, metrics, error, done.
 */
export function createSSEStreamHandler(
  set: (fn: (state: AIState) => Partial<AIState> | AIState) => void,
  get: () => AIState
) {
  let tokenBuffer = "";
  let tokenFlushTimer: any = null;

  const flushTokens = () => {
    if (tokenFlushTimer) {
      clearTimeout(tokenFlushTimer);
      tokenFlushTimer = null;
    }
    if (!tokenBuffer) return;
    const chunk = tokenBuffer;
    tokenBuffer = "";
    const now = Date.now();
    set((state) => {
      const messages = [...state.messages];
      const last = messages[messages.length - 1];
      if (last && last.role === "assistant") {
        messages[messages.length - 1] = { ...last, content: last.content + chunk };
      }
      return { messages, lastTokenTimestamp: now };
    });
  };

  const handler = (eventType: string, data: any) => {
    if (eventType === "token") {
      const tokenStr = typeof data === "string" ? data : (data?.content || "");
      tokenBuffer += tokenStr;
      if (!tokenFlushTimer) {
        tokenFlushTimer = setTimeout(() => {
          tokenFlushTimer = null;
          flushTokens();
        }, 50);
      }
      return;
    }

    // Flush any pending buffered tokens before handling status, command, or completion events
    flushTokens();

    if (eventType === "tier_routing") {
      const tierVal = typeof data.tier === "number" ? data.tier : 0;
      const labelVal = data.label || (tierVal === 0 ? "Fast Answer" : (tierVal === 1 ? "Quick Task" : "Deep think"));
      const reasonVal = data.reason || labelVal;
      set(() => ({
        currentTier: tierVal,
        currentTierLabel: labelVal,
        currentTierReason: reasonVal,
      }));
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
        tokens: data.tokens,
        retry_delay_seconds: data.retry_delay_seconds,
        is_rate_limit: data.is_rate_limit === true,
        attempt: data.attempt,
        max_attempts: data.max_attempts,
        success: data.success,
        output: data.output,
        reason: data.reason,
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
            state: "running",
            screenshot_path: data.screenshot_path,
            screenshot_base64: data.screenshot_base64,
          });
        } else if ((statusObj.type === "tool_result" || statusObj.type === "tool_error" || statusObj.type === "tool_skipped") && statusObj.tool) {
          const previous = [...newHistory].reverse().findIndex((entry) => entry.tool === statusObj.tool && entry.state === "running");
          const isDone = statusObj.type === "tool_result" && data.success === true;
          const isSkipped = statusObj.type === "tool_skipped" || data.reason === "consecutive_failures";
          const stateVal = isDone ? "completed" : (isSkipped ? "skipped" : "failed");
          if (previous >= 0) {
            const index = newHistory.length - 1 - previous;
            newHistory[index] = {
              ...newHistory[index],
              success: isDone,
              state: stateVal,
              output_preview: data.output || data.message || "",
              reason: data.reason || "",
              screenshot_path: data.screenshot_path || newHistory[index].screenshot_path,
              screenshot_base64: data.screenshot_base64 || newHistory[index].screenshot_base64,
            };
          } else if (statusObj.type === "tool_skipped") {
            newHistory.push({
              tool: statusObj.tool,
              detail: statusObj.detail,
              timestamp: new Date().toISOString(),
              state: "skipped",
              success: false,
              output_preview: data.message || "",
              reason: data.reason || "consecutive_failures",
              screenshot_path: data.screenshot_path,
              screenshot_base64: data.screenshot_base64,
            });
          }
        }
        const tokenUpdate = typeof data.tokens === "number" ? { currentTokensUsed: data.tokens } : {};
        const retryUpdate = statusObj.type === "retry" ? { retryStatus: { message: statusObj.message, retry_delay_seconds: data.retry_delay_seconds, attempt: data.attempt, max_attempts: data.max_attempts, is_rate_limit: data.is_rate_limit === true } } : (statusObj.type === "thinking" || statusObj.type === "tool" ? { retryStatus: null } : {});
        return { agentStatus: statusObj, agentToolHistory: newHistory, pendingApproval: statusObj.type === "tool" ? null : state.pendingApproval, messages, ...tokenUpdate, ...retryUpdate };
      });
    } else if (eventType === "ask_user" || eventType === "question") {
      const askObj: PendingUserResponseState = {
        action_id: data.action_id,
        question: data.question || "Please select an option:",
        options: data.options || [],
      };
      set(() => ({ pendingUserResponse: askObj }));
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
    } else if (eventType === "proposal") {
      window.dispatchEvent(new CustomEvent("code-os:proposal-created"));
    } else if (eventType === "command_result") {
      const cmdResult: CommandExecution = {
        command: data.command || "",
        output: data.output || "",
        exit_code: typeof data.exit_code === "number" ? data.exit_code : (data.success ? 0 : 1),
        success: data.success ?? true,
        reason: data.reason || "",
      };
      set((state) => {
        const messages = [...state.messages];
        const last = messages[messages.length - 1];
        const newHistory = [...state.agentToolHistory];
        const prevRunningIdx = [...newHistory].reverse().findIndex(
          (entry) => (entry.tool === "run_command" || entry.tool === "run_test") && entry.state === "running"
        );
        if (prevRunningIdx >= 0) {
          const idx = newHistory.length - 1 - prevRunningIdx;
          newHistory[idx] = {
            ...newHistory[idx],
            success: cmdResult.success,
            state: cmdResult.success ? "completed" : "failed",
            output_preview: cmdResult.output.substring(0, 300),
            reason: cmdResult.reason,
          };
        } else {
          newHistory.push({
            tool: "run_command",
            detail: cmdResult.command,
            timestamp: new Date().toISOString(),
            success: cmdResult.success,
            state: cmdResult.success ? "completed" : "failed",
            output_preview: cmdResult.output.substring(0, 300),
            reason: cmdResult.reason,
          });
        }
        if (last && last.role === "assistant") {
          const existing = last.commands || [];
          messages[messages.length - 1] = {
            ...last,
            commands: [...existing, cmdResult],
            agentToolHistory: newHistory,
          };
        }
        return { messages, agentToolHistory: newHistory, pendingApproval: null, pendingApprovals: [] };
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
        set(() => ({ currentTokensUsed: data.tokens_used }));
      }
    } else if (eventType === "error") {
      const errMsg = typeof data === "string" ? data : (data.message || "Agent error");
      set((state) => {
        const messages = [...state.messages];
        const last = messages[messages.length - 1];
        if (last && last.role === "assistant" && !last.content) {
          const prov = state.provider || "API";
          const tip = getTaxonomyTip(prov, errMsg, typeof data === "object" ? data?.category : undefined, typeof data === "object" ? data?.is_429 : undefined);
          messages[messages.length - 1] = {
            ...last,
            content: `⚠️ **AI Provider Error (${prov}):**\n\n${errMsg}\n\n${tip}`,
            agentStatus: { type: "error", message: "Provider Error" },
          };
        }
        return {
          error: errMsg,
          messages,
          pendingApproval: null,
          pendingApprovals: [],
          interruptedTasks: [],
          pendingUserResponse: null,
          retryStatus: null,
        };
      });
    } else if (eventType === "done") {
      const isSuccess = data.success !== false;
      const doneMsg = data.message || (isSuccess ? "Task completed" : "Task stopped");
      const recPayload: AIRecoveryPayload | null = data.recovery || (!isSuccess ? { error: doneMsg } : null);
      set((state) => {
        const messages = [...state.messages];
        const last = messages[messages.length - 1];
        if (last && last.role === "assistant") {
          const prov = state.provider || "API";
          const tip = getTaxonomyTip(prov, doneMsg, recPayload?.category, recPayload?.is_429);
          const finalContent = last.content || (isSuccess ? "" : `⚠️ **AI Provider Error:**\n\n${doneMsg}\n\n${tip}`);
          messages[messages.length - 1] = {
            ...last,
            content: finalContent,
            agentStatus: { type: isSuccess ? "done" : "error", message: doneMsg },
            agentToolHistory: state.agentToolHistory,
          };
        }
        return {
          agentStatus: { type: isSuccess ? "done" : "error", message: doneMsg },
          pendingApproval: null,
          pendingApprovals: [],
          interruptedTasks: [],
          pendingUserResponse: null,
          streaming: false,
          interruptedState: null,
          recoveryPayload: recPayload,
          retryStatus: null,
          messages,
        };
      });
    }
  };
  return { handler, flushTokens };
}

export function getTaxonomyTip(provider: string, errMsg: string, category?: string, is429?: boolean): string {
  if (category === "rate_limit" || is429 === true) {
    return `*Tip: Rate limit reached on ${provider || "provider"}. Wait a moment or switch models below.*`;
  }
  if (category === "authentication") {
    return `*Tip: Authentication failed. Please verify your API key for ${provider || "provider"} in Settings.*`;
  }
  if (category === "not_found") {
    return `*Tip: Requested model not found on ${provider || "provider"}. Choose a supported model below.*`;
  }
  if (category === "context_overflow") {
    return `*Tip: Context window limit reached. The conversation history was compacted.*`;
  }
  if (category === "transient") {
    return `*Tip: Provider service is temporarily unreachable. Try again shortly or choose an alternative model below.*`;
  }
  const lower = errMsg.toLowerCase();
  if (lower.includes("http 429") || lower.includes("status 429")) {
    return `*Tip: Rate limit reached on ${provider || "provider"}. Wait a moment or switch models below.*`;
  }
  if (lower.includes("401") || lower.includes("403") || lower.includes("authentication") || lower.includes("unauthorized") || lower.includes("api key")) {
    return `*Tip: Authentication failed. Please verify your API key for ${provider || "provider"} in Settings.*`;
  }
  if (lower.includes("404") || lower.includes("not found") || lower.includes("does not exist")) {
    return `*Tip: Requested model not found on ${provider || "provider"}. Choose a supported model below.*`;
  }
  if (lower.includes("context") || lower.includes("too large") || lower.includes("token")) {
    return `*Tip: Context window limit reached. The conversation history was compacted.*`;
  }
  if (lower.includes("connection") || lower.includes("timeout") || lower.includes("500") || lower.includes("502") || lower.includes("503") || lower.includes("504") || lower.includes("network")) {
    return `*Tip: Provider service is temporarily unreachable. Try again shortly or choose an alternative model below.*`;
  }
  if (lower.includes("prose narration") || lower.includes("no tools")) {
    return `*Tip: The model described steps without emitting executable tool calls. Try re-prompting with explicit tool instructions.*`;
  }
  return `*Tip: You can switch providers or choose an alternative model below.*`;
}

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

  // Token usage & Provider health
  tokenUsage: null,
  providerHealth: null,

  // Agent mode defaults (OFF by default)
  agentMode: false,
  currentTier: null,
  currentTierLabel: null,
  currentTierReason: null,
  currentTokensUsed: null,
  retryStatus: null,
  recoveryPayload: null,
  clearRecovery: () => set({ recoveryPayload: null, retryStatus: null }),
  interruptedState: null,
  agentStatus: null,
  agentPlan: null,
  agentToolHistory: [],
  pendingApproval: null,
  pendingApprovals: [],
  interruptedTasks: [],
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
  interruptedTasks: [],
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

      const sseHandler = createSSEStreamHandler(set, get);
      await api.streamSSE(
        "/api/ai/chat-agent/resume",
        {
          workspace: ws,
          provider: get().provider,
          model: get().model,
          base_url: get().baseUrl || undefined,
          api_key_provider: get().apiKeyProvider || undefined,
        },
        sseHandler.handler,
        controller.signal
      );
      sseHandler.flushTokens();
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
    } catch (err) {
      console.warn("Approval endpoint notice:", err);
    } finally {
      set((state) => {
        const remaining = (state.pendingApprovals || []).filter((a) => a.action_id !== actionId);
        return {
          pendingApprovals: remaining,
          pendingApproval: remaining[0] || null,
        };
      });
    }
  },

  rejectAction: async (actionId: string) => {
    try {
      await api.post(`/api/ai/chat-agent/reject/${actionId}`);
    } catch (err) {
      console.warn("Reject endpoint notice:", err);
    } finally {
      set((state) => {
        const remaining = (state.pendingApprovals || []).filter((a) => a.action_id !== actionId);
        return {
          pendingApprovals: remaining,
          pendingApproval: remaining[0] || null,
        };
      });
    }
  },

    fetchPendingApprovals: async (workspace?: string) => {
    try {
      const list = await api.get<any[]>("/api/ai/pending-approvals", workspace ? { workspace } : undefined);
      if (Array.isArray(list) && list.length > 0) {
        const formatted: PendingApprovalState[] = list.map((item) => ({
          action_id: item.action_id,
          action_type: item.action_type || "command",
          detail: item.payload?.detail || item.action_id,
          reason: item.payload?.reason || "Action requires user approval",
          proposal_id: item.payload?.proposal_id,
          path: item.payload?.path,
          diff_summary: item.payload?.diff_summary,
          command: item.payload?.command,
          always_allow: false,
          trust_pattern: null,
        }));
        set({
          pendingApprovals: formatted,
          pendingApproval: formatted[0],
          agentStatus: {
            type: "approval_required",
            message: `Pending Approval: ${formatted[0].detail}`,
            step: 1,
          },
        });
      }
    } catch (err) {
      console.debug("Failed to fetch pending approvals:", err);
    }
  },

    fetchInterruptedTasks: async () => {
    try {
      const list = await api.get<any[]>("/api/agents/interrupted");
      if (Array.isArray(list)) {
        set({ interruptedTasks: list });
      }
    } catch (err) {
      console.debug("Failed to fetch interrupted tasks on startup:", err);
    }
  },

  resumeTask: async (taskId: string) => {
    try {
      await api.post(`/api/agents/${taskId}/resume`);
      return true;
    } catch (err) {
      console.error("Failed to resume task:", err);
      return false;
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

  fetchTokenUsage: async () => {
    try {
      const data = await api.get<Record<string, TokenUsageStatus>>("/api/ai/token-usage");
      set({ tokenUsage: data });
    } catch {
      // Ignore
    }
  },

  fetchProviderHealth: async () => {
    try {
      const data = await api.get<Record<string, ProviderHealthStatus>>("/api/ai/provider-health");
      set({ providerHealth: data });
    } catch {
      // Ignore
    }
  },

  stopGeneration: () => {
    activeController?.abort();
    activeController = null;
    void api.post("/api/ai/chat-agent/cancel").catch(() => {});
    set({
      streaming: false,
      pendingUserResponse: null,
      pendingApproval: null,
      pendingApprovals: [],
      interruptedTasks: [],
      streamStartTimestamp: null,
      lastTokenTimestamp: null,
      retryStatus: null,
    });
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
  interruptedTasks: [],
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
      const cleanTitle = content.trim().substring(0, 32) + (content.length > 32 ? "… " : "");
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
      retryStatus: null,
      recoveryPayload: null,
      streamStartTimestamp: now,
      lastTokenTimestamp: now,
      agentStatus: { type: "thinking", message: "Connecting..." },
      agentPlan: null,
      agentToolHistory: [],
      pendingUserResponse: null,
      pendingApproval: null,
      pendingApprovals: [],
  interruptedTasks: [],
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
      const sseHandler = createSSEStreamHandler(set, get);
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
        sseHandler.handler,
        activeController.signal
      );
      sseHandler.flushTokens();

      await api.post(`/api/ai/threads/${threadId}/messages`, { messages: get().messages });
    } catch (error) {
      if (!(error instanceof DOMException && error.name === "AbortError")) {
        const errMsg = error instanceof Error ? error.message : "Agent request failed";
        set((state) => {
          const messages = [...state.messages];
          const last = messages[messages.length - 1];
          if (last && last.role === "assistant" && !last.content) {
            messages[messages.length - 1] = {
              ...last,
              content: `⚠️ **Connection Error:**\n\n${errMsg}\n\n*Tip: Unable to communicate with the server. Check your connection or backend status.*`,
              agentStatus: { type: "error", message: "Connection Error" },
            };
          }
          return { error: errMsg, messages };
        });
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

