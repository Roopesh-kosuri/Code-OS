import { create } from "zustand";

import { api } from "../lib/api";
import type { IndexStatus } from "../types/api";
import { useWorkspaceStore } from "./workspaceStore";

type IndexState = {
  status: IndexStatus | null;
  error: string | null;
  refresh: () => Promise<void>;
  run: () => Promise<void>;
};

export const useIndexStore = create<IndexState>((set) => ({
  status: null,
  error: null,
  refresh: async () => {
    const workspace = useWorkspaceStore.getState().currentWorkspace;
    if (!workspace) {
      set({ status: null, error: null });
      return;
    }
    try {
      const status = await api.get<IndexStatus | null>("/api/index/status", { workspace: workspace.path });
      set({ status, error: null });
    } catch (error) {
      set({ error: error instanceof Error ? error.message : "Index status failed" });
    }
  },
  run: async () => {
    const workspace = useWorkspaceStore.getState().currentWorkspace;
    if (!workspace) return;
    await api.post("/api/index/run", undefined, { workspace: workspace.path });
  }
}));
