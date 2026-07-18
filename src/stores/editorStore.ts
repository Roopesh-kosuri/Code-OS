import { create } from "zustand";

import { api } from "../lib/api";
import type { OpenFile } from "../types/api";
import { useWorkspaceStore } from "./workspaceStore";

type EditorState = {
  openFiles: OpenFile[];
  activePath: string | null;
  splitPath: string | null;
  autoSave: boolean;
  fontSize: number;
  tabSize: number;
  openFile: (filePath: string) => Promise<void>;
  closeFile: (filePath: string) => void;
  updateContent: (filePath: string, content: string) => Promise<void>;
  saveFile: (filePath: string) => Promise<void>;
  saveAll: () => Promise<void>;
  restoreTabs: () => Promise<void>;
  closeWorkspaceTabs: () => void;
  setAutoSave: (autoSave: boolean) => void;
  setEditorSetting: (setting: { fontSize?: number; tabSize?: number }) => void;
  loadEditorSettings: () => Promise<void>;
  toggleSplit: (filePath: string | null) => void;
};

function filename(filePath: string): string {
  return filePath.split(/[\\/]/).pop() ?? filePath;
}

export const useEditorStore = create<EditorState>((set, get) => ({
  openFiles: [],
  activePath: null,
  splitPath: null,
  autoSave: localStorage.getItem("code-os:auto-save") !== "false",
  fontSize: Number(localStorage.getItem("code-os:font-size") ?? "14"),
  tabSize: Number(localStorage.getItem("code-os:tab-size") ?? "2"),
  openFile: async (filePath) => {
    console.info("[editor.open] requested", filePath);
    useWorkspaceStore.getState().selectWorkspaceForPath(filePath);
    const workspace = useWorkspaceStore.getState().currentWorkspace;
    if (!workspace) {
      return;
    }
    const existing = get().openFiles.find((file) => file.path === filePath);
    if (existing) {
      set({ activePath: filePath });
      return;
    }
    const response = await api.get<{ path: string; content: string; language: string }>("/api/files/read", {
      workspace: workspace.path,
      path: filePath
    });
    console.info("[editor.open] loaded", { path: filePath, language: response.language, bytes: response.content.length });
    set((state) => ({
      openFiles: [...state.openFiles, { path: filePath, name: filename(filePath), content: response.content, language: response.language, dirty: false }],
      activePath: filePath
    }));
    localStorage.setItem("code-os:open-tabs", JSON.stringify(get().openFiles.map((file) => file.path)));
  },
  closeFile: (filePath) =>
    set((state) => {
      const openFiles = state.openFiles.filter((file) => file.path !== filePath);
      const nextActivePath = state.activePath === filePath ? openFiles.at(-1)?.path ?? null : state.activePath;
      if (nextActivePath) {
        useWorkspaceStore.getState().selectWorkspaceForPath(nextActivePath);
      }
      localStorage.setItem("code-os:open-tabs", JSON.stringify(openFiles.map((file) => file.path)));
      return {
        openFiles,
        activePath: nextActivePath,
        splitPath: state.splitPath === filePath ? null : state.splitPath
      };
    }),
  updateContent: async (filePath, content) => {
    set((state) => ({
      openFiles: state.openFiles.map((file) => (file.path === filePath ? { ...file, content, dirty: true } : file))
    }));
    if (get().autoSave) {
      await get().saveFile(filePath);
    }
  },
  saveFile: async (filePath) => {
    console.info("[editor.save] requested", filePath);
    useWorkspaceStore.getState().selectWorkspaceForPath(filePath);
    const workspace = useWorkspaceStore.getState().currentWorkspace;
    const file = get().openFiles.find((item) => item.path === filePath);
    if (!workspace || !file) {
      return;
    }
    await api.post("/api/files/write", { workspace: workspace.path, path: file.path, content: file.content });
    console.info("[editor.save] written", filePath);
    set((state) => ({
      openFiles: state.openFiles.map((item) => (item.path === filePath ? { ...item, dirty: false } : item))
    }));
  },
  saveAll: async () => {
    await Promise.all(get().openFiles.map((file) => get().saveFile(file.path)));
  },
  restoreTabs: async () => {
    const paths = JSON.parse(localStorage.getItem("code-os:open-tabs") ?? "[]") as string[];
    for (const filePath of paths) {
      try {
        await get().openFile(filePath);
      } catch {
        // Missing files are ignored during session restore.
      }
    }
  },
  closeWorkspaceTabs: () => {
    localStorage.removeItem("code-os:open-tabs");
    set({ openFiles: [], activePath: null, splitPath: null });
  },
  setAutoSave: async (autoSave) => {
    localStorage.setItem("code-os:auto-save", String(autoSave));
    set({ autoSave });
    // Persist to backend
    try {
      await api.post("/api/settings", { key: "editor.autoSave", value: String(autoSave) });
    } catch (error) {
      console.error("Failed to save autoSave setting:", error);
    }
  },
  setEditorSetting: async (setting) => {
    if (setting.fontSize !== undefined) {
      localStorage.setItem("code-os:font-size", String(setting.fontSize));
      set({ fontSize: setting.fontSize });
      try {
        await api.post("/api/settings", { key: "editor.fontSize", value: String(setting.fontSize) });
      } catch (error) {
        console.error("Failed to save fontSize setting:", error);
      }
    }
    if (setting.tabSize !== undefined) {
      localStorage.setItem("code-os:tab-size", String(setting.tabSize));
      set({ tabSize: setting.tabSize });
      try {
        await api.post("/api/settings", { key: "editor.tabSize", value: String(setting.tabSize) });
      } catch (error) {
        console.error("Failed to save tabSize setting:", error);
      }
    }
  },
  loadEditorSettings: async () => {
    try {
      const response = await api.get<{ key: string; value: string }[]>("/api/settings");
      const settings = Object.fromEntries(response.map((item) => [item.key, item.value]));
      
      if (settings["editor.autoSave"] !== undefined) {
        const autoSave = settings["editor.autoSave"] === "true";
        localStorage.setItem("code-os:auto-save", String(autoSave));
        set({ autoSave });
      }
      if (settings["editor.fontSize"] !== undefined) {
        const fontSize = Number(settings["editor.fontSize"]);
        localStorage.setItem("code-os:font-size", String(fontSize));
        set({ fontSize });
      }
      if (settings["editor.tabSize"] !== undefined) {
        const tabSize = Number(settings["editor.tabSize"]);
        localStorage.setItem("code-os:tab-size", String(tabSize));
        set({ tabSize });
      }
    } catch (error) {
      console.error("Failed to load editor settings:", error);
    }
  },
  toggleSplit: (filePath) => set({ splitPath: filePath })
}));

if (typeof window !== "undefined") {
  (window as any).useEditorStore = useEditorStore;
}
