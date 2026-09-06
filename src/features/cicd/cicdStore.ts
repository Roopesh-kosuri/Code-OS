import { create } from "zustand";
import { api } from "../../lib/api";

export interface StackConfig {
  languages: string[];
  frameworks: string[];
  test_runners: string[];
  package_managers: string[];
  python_version?: string;
  node_version?: string;
  test_command?: string;
  build_command?: string;
  has_docker?: boolean;
}

interface CicdState {
  stackConfig: StackConfig | null;
  provider: "github" | "gitlab";
  yamlContent: string;
  filePath: string;
  isAnalyzing: boolean;
  isGenerating: boolean;
  isSaving: boolean;
  isEditable: boolean;
  copied: boolean;
  saveStatus: string | null;

  // Actions
  analyzeStack: (workspace: string) => Promise<StackConfig | null>;
  setProvider: (provider: "github" | "gitlab") => void;
  generateYaml: (workspace: string, provider?: "github" | "gitlab") => Promise<string>;
  setYamlContent: (content: string) => void;
  toggleManualEdit: () => void;
  savePipeline: (workspace: string, yamlContent?: string, filePath?: string) => Promise<boolean>;
  copyYaml: () => Promise<boolean>;
  reset: () => void;
}

export const useCicdStore = create<CicdState>((set, get) => ({
  stackConfig: null,
  provider: "github",
  yamlContent: "",
  filePath: ".github/workflows/ci.yml",
  isAnalyzing: false,
  isGenerating: false,
  isSaving: false,
  isEditable: false,
  copied: false,
  saveStatus: null,

  analyzeStack: async (workspace: string) => {
    if (!workspace) return null;
    set({ isAnalyzing: true });
    try {
      const res = await api.post<StackConfig>("/api/cicd/analyze", { workspace });
      set({ stackConfig: res, isAnalyzing: false });
      return res;
    } catch (err) {
      console.error("[cicdStore] analyzeStack error:", err);
      set({ isAnalyzing: false });
      return null;
    }
  },

  setProvider: (provider: "github" | "gitlab") => {
    const targetFile = provider === "gitlab" ? ".gitlab-ci.yml" : ".github/workflows/ci.yml";
    set({ provider, filePath: targetFile });
  },

  generateYaml: async (workspace: string, provider?: "github" | "gitlab") => {
    const prov = provider || get().provider;
    set({ isGenerating: true });
    try {
      const res = await api.post<{ yaml_content: string; file_path: string }>("/api/cicd/generate", {
        workspace,
        provider: prov,
        stack_config: get().stackConfig,
      });

      set({
        yamlContent: res.yaml_content || "",
        filePath: res.file_path || (prov === "gitlab" ? ".gitlab-ci.yml" : ".github/workflows/ci.yml"),
        isGenerating: false,
      });

      return res.yaml_content;
    } catch (err) {
      console.error("[cicdStore] generateYaml error:", err);
      set({ isGenerating: false });
      return "";
    }
  },

  setYamlContent: (content: string) => {
    set({ yamlContent: content });
  },

  toggleManualEdit: () => {
    set((state) => ({ isEditable: !state.isEditable }));
  },

  savePipeline: async (workspace: string, yamlContent?: string, filePath?: string) => {
    const content = yamlContent ?? get().yamlContent;
    const path = filePath ?? get().filePath;
    if (!workspace || !content) return false;

    set({ isSaving: true });
    try {
      const res = await api.post<{ success: boolean; file_path: string }>("/api/cicd/save", {
        workspace,
        yaml_content: content,
        file_path: path,
      });

      if (res.success) {
        set({
          isSaving: false,
          saveStatus: `Saved to ${res.file_path}`,
        });
        setTimeout(() => set({ saveStatus: null }), 2500);
        return true;
      }
      set({ isSaving: false });
      return false;
    } catch (err) {
      console.error("[cicdStore] savePipeline error:", err);
      set({ isSaving: false });
      return false;
    }
  },

  copyYaml: async () => {
    const yaml = get().yamlContent;
    if (!yaml) return false;

    try {
      if (typeof navigator !== "undefined" && navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(yaml);
      }
      set({ copied: true });
      setTimeout(() => set({ copied: false }), 2000);
      return true;
    } catch (err) {
      console.warn("[cicdStore] copy error:", err);
      return false;
    }
  },

  reset: () =>
    set({
      stackConfig: null,
      provider: "github",
      yamlContent: "",
      filePath: ".github/workflows/ci.yml",
      isAnalyzing: false,
      isGenerating: false,
      isSaving: false,
      isEditable: false,
      copied: false,
      saveStatus: null,
    }),
}));
