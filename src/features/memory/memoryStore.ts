import { create } from "zustand";
import { api } from "../../lib/api";

export interface AgentMemory {
  id: string;
  workspace: string;
  category: "rejected_edit" | "failed_test" | "repair_loop" | "user_correction" | "security_fix" | "manual" | string;
  lesson: string;
  raw_event?: string;
  source_event_id?: string;
  confidence: number;
  times_applied: number;
  created_at?: string;
  last_applied_at?: string;
}

interface MemoryState {
  memories: AgentMemory[];
  isLoading: boolean;
  error: string | null;
  activeCategory: string;
  searchQuery: string;

  // Actions
  fetchMemories: (workspace: string) => Promise<void>;
  addMemory: (workspace: string, lesson: string, category?: string, confidence?: number) => Promise<AgentMemory | null>;
  deleteMemory: (id: string) => Promise<boolean>;
  boostMemory: (id: string, amount?: number) => Promise<void>;
  logMistake: (workspace: string, category: string, raw_event: string) => Promise<AgentMemory | null>;
  setActiveCategory: (category: string) => void;
  setSearchQuery: (query: string) => void;
  reset: () => void;
}

export const useMemoryStore = create<MemoryState>((set, get) => ({
  memories: [],
  isLoading: false,
  error: null,
  activeCategory: "all",
  searchQuery: "",

  fetchMemories: async (workspace: string) => {
    if (!workspace) return;
    set({ isLoading: true, error: null });
    try {
      const data = await api.get<AgentMemory[]>("/api/memories", { workspace });
      set({ memories: Array.isArray(data) ? data : [], isLoading: false });
    } catch (err: any) {
      set({ error: err?.message || "Failed to load agent memories", isLoading: false });
    }
  },

  addMemory: async (workspace: string, lesson: string, category = "manual", confidence = 100) => {
    if (!workspace || !lesson.trim()) return null;
    set({ isLoading: true, error: null });
    try {
      const newMemory = await api.post<AgentMemory>("/api/memories", {
        workspace,
        lesson: lesson.trim(),
        category,
        confidence,
      });
      set((state) => ({
        memories: [newMemory, ...state.memories.filter((m) => m.id !== newMemory.id)],
        isLoading: false,
      }));
      return newMemory;
    } catch (err: any) {
      set({ error: err?.message || "Failed to create lesson", isLoading: false });
      return null;
    }
  },

  deleteMemory: async (id: string) => {
    try {
      await api.delete<{ success: boolean }>(`/api/memories/${id}`);
      set((state) => ({
        memories: state.memories.filter((m) => m.id !== id),
      }));
      return true;
    } catch (err: any) {
      set({ error: err?.message || "Failed to delete memory" });
      return false;
    }
  },

  boostMemory: async (id: string, amount = 10) => {
    try {
      const updated = await api.post<AgentMemory>(`/api/memories/${id}/boost`, { amount });
      if (updated && updated.id) {
        set((state) => ({
          memories: state.memories.map((m) => (m.id === id ? updated : m)),
        }));
      }
    } catch (err: any) {
      set({ error: err?.message || "Failed to boost memory" });
    }
  },

  logMistake: async (workspace: string, category: string, raw_event: string) => {
    try {
      const mem = await api.post<AgentMemory>("/api/memories/log-mistake", {
        workspace,
        category,
        raw_event,
      });
      set((state) => ({
        memories: [mem, ...state.memories.filter((m) => m.id !== mem.id)],
      }));
      return mem;
    } catch (err: any) {
      set({ error: err?.message || "Failed to log mistake" });
      return null;
    }
  },

  setActiveCategory: (category: string) => {
    set({ activeCategory: category });
  },

  setSearchQuery: (query: string) => {
    set({ searchQuery: query });
  },

  reset: () => {
    set({
      memories: [],
      isLoading: false,
      error: null,
      activeCategory: "all",
      searchQuery: "",
    });
  },
}));
