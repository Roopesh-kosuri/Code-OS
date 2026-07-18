import { create } from "zustand";
import { api } from "../lib/api";
import { getPreset } from "../lib/providerPresets";
import type { ChatMessage, ModelDto } from "../types/api";
import { useWorkspaceStore } from "./workspaceStore";
import { useEditorStore } from "./editorStore";

// ── Extended types ────────────────────────────────────────────────────────────

export interface ExtendedChatMessage extends ChatMessage {
  id?: string;
  model?: string;
  attached_paths?: string[];
  created_at?: string;
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

  // Multi-thread state
  currentThreadId: string | null;
  threads: ChatThread[];

  setPreset: (presetId: string, baseUrlOverride?: string) => void;
  setModel: (model: string) => void;
  setBaseUrl: (baseUrl: string) => void;
  refreshModels: () => Promise<void>;
  stopGeneration: () => void;

  // Actions
  loadThreads: (workspace: string) => Promise<void>;
  switchThread: (threadId: string) => Promise<void>;
  newThread: (workspace?: string) => Promise<void>;
  renameThread: (threadId: string, title: string) => Promise<void>;
  deleteThread: (threadId: string) => Promise<void>;
  
  sendMessage: (content: string, attachedPaths?: string[]) => Promise<void>;
  regenerate: () => Promise<void>;
  editMessage: (index: number, newContent: string) => Promise<void>;
  deleteMessagePair: (index: number) => Promise<void>;
};

let activeController: AbortController | null = null;

export const useAIStore = create<AIState>((set, get) => ({
  preset: "ollama",
  provider: "ollama",
  apiKeyProvider: null,
  model: "",
  baseUrl: "http://127.0.0.1:11434",
  messages: [],
  models: [],
  streaming: false,
  error: null,

  currentThreadId: null,
  threads: [],

  setPreset: (presetId, baseUrlOverride) => {
    const p = getPreset(presetId);
    if (!p) return;
    // Auto-fill the example model when switching to a new preset
    // so users never need to type a model name for API providers
    const currentPreset = get().preset;
    const currentModel = get().model;
    const autoModel = presetId !== currentPreset
      ? (p.model_example || currentModel)   // switch → use example
      : currentModel;                        // same preset → keep current
    set({
      preset: presetId,
      provider: p.provider,
      apiKeyProvider: p.api_key_provider,
      baseUrl: baseUrlOverride ?? p.base_url,
      model: autoModel,
      models: [],
    });
    void get().refreshModels();
  },

  setModel: (model) => set({ model }),
  setBaseUrl: (baseUrl) => set({ baseUrl }),

  refreshModels: async () => {
    const state = get();
    try {
      const models = await api.get<ModelDto[]>("/api/ai/models", {
        provider: state.provider,
        base_url: state.baseUrl,
        api_key_provider: state.apiKeyProvider,
      });
      // Auto-select: use first fetched model only if no model is already set
      const bestModel = state.model || models[0]?.name || "";
      set({ models, model: bestModel });
    } catch {
      // Don't clear models on failure — keep existing list / current model
      set({ models: [] });
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
          set((state) => {
            const messages = [...state.messages];
            const last = messages[messages.length - 1];
            if (last?.role === "assistant") {
              messages[messages.length - 1] = { ...last, content: last.content + token };
            }
            return { messages };
          });
        },
        activeController.signal
      );

      // Sync final response to db
      await api.post(`/api/ai/threads/${threadId}/messages`, { messages: get().messages });
    } catch (error) {
      if (!(error instanceof DOMException && error.name === "AbortError")) {
        set({ error: error instanceof Error ? error.message : "AI request failed" });
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
