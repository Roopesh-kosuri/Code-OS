import { create } from "zustand";
import { api } from "../../lib/api";

export interface RAGChunkResult {
  file_path: string;
  chunk_text: string;
  score: number;
  line_range: string;
  language?: string;
}

export interface RAGIndexStatus {
  indexed_files: number;
  total_chunks: number;
  last_indexed_at: string | null;
}

export interface RAGStoreState {
  indexStatus: RAGIndexStatus;
  searchResults: RAGChunkResult[];
  searchQuery: string;
  isIndexing: boolean;
  isSearching: boolean;
  useRagInChat: boolean;
  error: string | null;

  setSearchQuery: (query: string) => void;
  toggleUseRagInChat: () => void;
  setUseRagInChat: (val: boolean) => void;
  clearResults: () => void;
  clearError: () => void;
  indexWorkspace: (workspace: string) => Promise<void>;
  indexFile: (workspace: string, filePath: string) => Promise<void>;
  search: (workspace: string, query: string, top_k?: number) => Promise<RAGChunkResult[]>;
  checkStatus: (workspace: string) => Promise<RAGIndexStatus | null>;
}

export const useRAGStore = create<RAGStoreState>((set, get) => ({
  indexStatus: {
    indexed_files: 0,
    total_chunks: 0,
    last_indexed_at: null,
  },
  searchResults: [],
  searchQuery: "",
  isIndexing: false,
  isSearching: false,
  useRagInChat: true,
  error: null,

  setSearchQuery: (searchQuery: string) => set({ searchQuery }),
  toggleUseRagInChat: () => set((state) => ({ useRagInChat: !state.useRagInChat })),
  setUseRagInChat: (useRagInChat: boolean) => set({ useRagInChat }),
  clearResults: () => set({ searchResults: [], error: null }),
  clearError: () => set({ error: null }),

  indexWorkspace: async (workspace: string) => {
    if (!workspace) return;
    set({ isIndexing: true, error: null });
    try {
      const res = await api.post<RAGIndexStatus & { ok: boolean }>("/api/rag/index-workspace", { workspace });
      set({
        indexStatus: {
          indexed_files: res.indexed_files || 0,
          total_chunks: res.total_chunks || 0,
          last_indexed_at: res.last_indexed_at || null,
        },
        isIndexing: false,
      });
    } catch (err: any) {
      set({
        isIndexing: false,
        error: err.message || "Failed to index workspace",
      });
    }
  },

  indexFile: async (workspace: string, filePath: string) => {
    if (!workspace || !filePath) return;
    try {
      await api.post("/api/rag/index-file", { workspace, file_path: filePath });
      void get().checkStatus(workspace);
    } catch (err: any) {
      set({ error: err.message || `Failed to index file ${filePath}` });
    }
  },

  search: async (workspace: string, query: string, top_k = 5): Promise<RAGChunkResult[]> => {
    if (!workspace || !query.trim()) {
      set({ searchResults: [] });
      return [];
    }
    set({ isSearching: true, error: null });
    try {
      const res = await api.post<{ ok: boolean; results: RAGChunkResult[] }>("/api/rag/search", {
        workspace,
        query: query.trim(),
        top_k,
      });
      const results = res.results || [];
      set({ searchResults: results, isSearching: false });
      return results;
    } catch (err: any) {
      set({
        isSearching: false,
        error: err.message || "Search failed",
        searchResults: [],
      });
      return [];
    }
  },

  checkStatus: async (workspace: string): Promise<RAGIndexStatus | null> => {
    if (!workspace) return null;
    try {
      const res = await api.get<RAGIndexStatus & { ok: boolean }>("/api/rag/status", { workspace });
      const status: RAGIndexStatus = {
        indexed_files: res.indexed_files || 0,
        total_chunks: res.total_chunks || 0,
        last_indexed_at: res.last_indexed_at || null,
      };
      set({ indexStatus: status });
      return status;
    } catch {
      return null;
    }
  },
}));
