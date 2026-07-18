import { create } from "zustand";

import { api } from "../lib/api";
import type { FileNode, WorkspaceDto } from "../types/api";

type WorkspaceState = {
  currentWorkspace: WorkspaceDto | null;
  activeWorkspaces: WorkspaceDto[];
  recentWorkspaces: WorkspaceDto[];
  fileTree: FileNode | null;
  fileTrees: Record<string, FileNode | null>;
  loading: boolean;
  error: string | null;
  loadRecent: () => Promise<void>;
  restoreLastWorkspace: () => Promise<void>;
  isOpeningFolder: boolean;
  setOpeningFolder: (open: boolean) => void;
  openWorkspace: (path?: string) => Promise<void>;
  completeWorkspaceOpen: (path: string) => Promise<void>;
  closeWorkspace: (path?: string) => void;
  refreshTree: () => Promise<void>;
  selectWorkspaceForPath: (path: string) => void;
  pendingWorkspacePath: string | null;
  // Trust management
  trustedWorkspaces: Record<string, boolean>;
  restrictedMode: boolean;
  checkWorkspaceTrust: (path: string) => Promise<boolean>;
  setWorkspaceTrust: (path: string, trusted: boolean) => Promise<void>;
  setRestrictedMode: (restricted: boolean) => void;
};

export const useWorkspaceStore = create<WorkspaceState>((set, get) => ({
  currentWorkspace: null,
  activeWorkspaces: [],
  recentWorkspaces: [],
  fileTree: null,
  fileTrees: {},
  loading: false,
  error: null,
  isOpeningFolder: false,
  pendingWorkspacePath: null,
  setOpeningFolder: (open) => set({ isOpeningFolder: open }),
  trustedWorkspaces: {},
  restrictedMode: false,
  loadRecent: async () => {
    const response = await api.get<{ workspaces: WorkspaceDto[]; last_workspace: WorkspaceDto | null }>("/api/workspaces");
    set({ recentWorkspaces: response.workspaces });
  },
  restoreLastWorkspace: async () => {
    try {
      console.info("[workspace.restore] requesting last workspace");
      const last = await api.get<WorkspaceDto | null>("/api/workspaces/last");
      console.info("[workspace.restore] backend returned", last);
      
      const storedPaths = JSON.parse(localStorage.getItem("code-os:active-workspaces") ?? "[]") as string[];
      const activeList: WorkspaceDto[] = [];
      
      if (last) {
        activeList.push(last);
        await get().checkWorkspaceTrust(last.path);
      }
      
      for (const p of storedPaths) {
        if (last && last.path === p) continue;
        try {
          const ws = await api.post<WorkspaceDto>("/api/workspaces/open", { path: p });
          activeList.push(ws);
          await get().checkWorkspaceTrust(p);
        } catch {
          // Ignore invalid workspaces during restore.
        }
      }
      
      if (activeList.length > 0) {
        const current = last ?? activeList[0];
        const isTrusted = get().trustedWorkspaces[current.path] ?? false;
        set({
          activeWorkspaces: activeList,
          currentWorkspace: current,
          restrictedMode: !isTrusted
        });
        await get().refreshTree();
      }
      await get().loadRecent();
    } catch (error) {
      const message = error instanceof Error ? error.message : "Workspace restore failed";
      console.error("[workspace.restore] failed", error);
      set({ error: `Restore failed: ${message}` });
    }
  },
  openWorkspace: async (path?: string) => {
    set({ error: null });
    let selected = path;

    if (!selected) {
      if (window.codeOS) {
        console.info("[workspace.open] opening native desktop dialog");
        const nativeSelected = await window.codeOS.selectWorkspaceFolder();
        if (!nativeSelected) {
          return;
        }
        selected = nativeSelected;
      } else {
        // Trigger React modal in web context
        set({ isOpeningFolder: true });
        return;
      }
    }

    // Check workspace trust before opening
    const isTrusted = await get().checkWorkspaceTrust(selected);
    if (!isTrusted) {
      // Set pending workspace path and show trust dialog
      set({ pendingWorkspacePath: selected });
      return;
    }

    // If trusted or previously decided, proceed with opening
    await get().completeWorkspaceOpen(selected);
  },
  completeWorkspaceOpen: async (selected: string) => {
    set({ loading: true, isOpeningFolder: false, pendingWorkspacePath: null });
    try {
      console.info("[workspace.open] sending path to backend", selected);
      const workspace = await api.post<WorkspaceDto>("/api/workspaces/open", { path: selected });
      console.info("[workspace.open] backend accepted", workspace);
      
      const currentActives = get().activeWorkspaces;
      const alreadyActive = currentActives.find((w) => w.path === workspace.path);
      const nextActives = alreadyActive ? currentActives : [...currentActives, workspace];
      
      const isTrusted = await get().checkWorkspaceTrust(workspace.path);
      
      set({
        currentWorkspace: workspace,
        activeWorkspaces: nextActives,
        restrictedMode: !isTrusted
      });
      localStorage.setItem("code-os:last-workspace", workspace.path);
      localStorage.setItem("code-os:active-workspaces", JSON.stringify(nextActives.map((w) => w.path)));
      await get().refreshTree();
      await get().loadRecent();
    } catch (error) {
      const message = error instanceof Error ? error.message : "Failed to open workspace";
      console.error("[workspace.open] failed", error);
      set({ error: `Open failed: ${message}` });
    } finally {
      set({ loading: false });
    }
  },
  closeWorkspace: (path?: string) => {
    if (path) {
      const nextActives = get().activeWorkspaces.filter((w) => w.path !== path);
      set((state) => {
        const nextTrees = { ...state.fileTrees };
        delete nextTrees[path];
        const nextCurrent = state.currentWorkspace?.path === path ? nextActives[0] ?? null : state.currentWorkspace;
        
        if (nextCurrent) {
          localStorage.setItem("code-os:last-workspace", nextCurrent.path);
        } else {
          localStorage.removeItem("code-os:last-workspace");
        }
        localStorage.setItem("code-os:active-workspaces", JSON.stringify(nextActives.map((w) => w.path)));
        
        return {
          activeWorkspaces: nextActives,
          currentWorkspace: nextCurrent,
          fileTrees: nextTrees
        };
      });
      void get().refreshTree();
    } else {
      localStorage.removeItem("code-os:last-workspace");
      localStorage.removeItem("code-os:active-workspaces");
      set({ currentWorkspace: null, activeWorkspaces: [], fileTree: null, fileTrees: {}, error: null });
    }
  },
  refreshTree: async () => {
    const actives = get().activeWorkspaces;
    if (actives.length === 0) {
      set({ fileTree: null, fileTrees: {}, error: null });
      return;
    }
    try {
      const nextTrees: Record<string, FileNode | null> = { ...get().fileTrees };
      for (const ws of actives) {
        try {
          console.info("[workspace.tree] loading", ws.path);
          const response = await api.get<{ root: FileNode }>("/api/files/tree", { workspace: ws.path, max_depth: 8 });
          nextTrees[ws.path] = response.root;
        } catch (error) {
          console.error("[workspace.tree] failed", { workspace: ws.path, error });
          nextTrees[ws.path] = null;
        }
      }
      
      const legacyTree = get().currentWorkspace ? nextTrees[get().currentWorkspace!.path] : null;
      set({ fileTrees: nextTrees, fileTree: legacyTree ?? null, error: null });
    } catch (error) {
      const message = error instanceof Error ? error.message : "Workspace refresh failed";
      console.error("[workspace.tree] failed", error);
      set({ error: `Tree load failed: ${message}` });
    }
  },
  selectWorkspaceForPath: (path: string) => {
    const normPath = path.toLowerCase().replace(/\\/g, "/");
    const found = get().activeWorkspaces.find((w) => {
      const wNorm = w.path.toLowerCase().replace(/\\/g, "/");
      return normPath === wNorm || normPath.startsWith(wNorm + "/");
    });
    if (found && get().currentWorkspace?.path !== found.path) {
      console.info("[workspace.select] switching currentWorkspace to", found.path);
      const isTrusted = get().trustedWorkspaces[found.path] ?? false;
      set({ 
        currentWorkspace: found,
        restrictedMode: !isTrusted
      });
      localStorage.setItem("code-os:last-workspace", found.path);
      const legacyTree = get().fileTrees[found.path] ?? null;
      set({ fileTree: legacyTree });
    }
  },
  checkWorkspaceTrust: async (path: string) => {
    try {
      const response = await api.get<{ trusted: boolean }>(`/api/workspaces/trust/${encodeURIComponent(path)}`);
      set((state) => ({
        trustedWorkspaces: { ...state.trustedWorkspaces, [path]: response.trusted }
      }));
      return response.trusted;
    } catch (error) {
      console.error("[workspace.trust] check failed", error);
      return false;
    }
  },
  setWorkspaceTrust: async (path: string, trusted: boolean) => {
    try {
      await api.post("/api/workspaces/trust", { path, trusted, trust_level: trusted ? "full" : "restricted" });
      set((state) => ({
        trustedWorkspaces: { ...state.trustedWorkspaces, [path]: trusted },
        restrictedMode: !trusted
      }));
    } catch (error) {
      console.error("[workspace.trust] set failed", error);
      throw error;
    }
  },
  setRestrictedMode: (restricted: boolean) => set({ restrictedMode: restricted })
}));

if (typeof window !== "undefined") {
  (window as any).useWorkspaceStore = useWorkspaceStore;
}
