import { create } from "zustand";
import { api } from "../lib/api";

export interface PromptQuality {
  quality: "good" | "weak" | "vague";
  issues: string[];
  score: number;
}

export interface EnhancementStats {
  enhanced_count: number;
  accepted_count: number;
  reverted_count: number;
  tokens_saved_estimate: number;
}

interface IntelligenceState {
  quality: PromptQuality | null;
  originalPrompt: string;
  enhancedPrompt: string;
  changes: string[];
  modelUsed: string;
  showBar: boolean;
  showDiff: boolean;
  isEnhancing: boolean;
  stats: EnhancementStats;

  classifyOnInput: (prompt: string, activeFile?: string | null, workspace?: string | null) => void;
  enhance: (prompt?: string, activeFile?: string | null, workspace?: string | null) => Promise<string>;
  accept: () => Promise<void>;
  revert: () => Promise<void>;
  editManually: () => void;
  dismiss: () => void;
  reset: () => void;
  fetchStats: () => Promise<void>;
}

let classifyTimer: ReturnType<typeof setTimeout> | null = null;

export const useIntelligenceStore = create<IntelligenceState>((set, get) => ({
  quality: null,
  originalPrompt: "",
  enhancedPrompt: "",
  changes: [],
  modelUsed: "",
  showBar: false,
  showDiff: false,
  isEnhancing: false,
  stats: {
    enhanced_count: 0,
    accepted_count: 0,
    reverted_count: 0,
    tokens_saved_estimate: 0,
  },

  classifyOnInput: (prompt: string, activeFile?: string | null, workspace?: string | null) => {
    if (classifyTimer) {
      clearTimeout(classifyTimer);
      classifyTimer = null;
    }

    const trimmed = prompt.trim();
    if (!trimmed) {
      set({ showBar: false, showDiff: false, quality: null, originalPrompt: "", enhancedPrompt: "" });
      return;
    }

    // Check user settings toggle: Suggest prompt enhancements (default ON)
    const suggestEnabled = localStorage.getItem("code-os:ai.suggest_prompt_enhancements") !== "false";
    if (!suggestEnabled) {
      set({ showBar: false, showDiff: false });
      return;
    }

    // Debounce by 600ms
    classifyTimer = setTimeout(async () => {
      try {
        const res = await api.post<PromptQuality>("/api/intelligence/classify-prompt", {
          prompt: trimmed,
          active_file: activeFile ?? null,
        });

        if (res.quality === "weak" || res.quality === "vague" || res.quality !== "good") {
          set({
            quality: res,
            originalPrompt: trimmed,
            showBar: true,
          });

          // Check if auto-enhance is enabled (default OFF)
          const autoEnhance = localStorage.getItem("code-os:ai.auto_enhance_weak_prompts") === "true";
          if (autoEnhance && !get().showDiff && !get().isEnhancing) {
            void get().enhance(trimmed, activeFile, workspace);
          }
        } else {
          set({
            quality: res,
            showBar: false,
          });
        }
      } catch (err) {
        console.warn("[intelligenceStore] classification failed", err);
      }
    }, 600);
  },

  enhance: async (prompt?: string, activeFile?: string | null, workspace?: string | null): Promise<string> => {
    const textToEnhance = (prompt ?? get().originalPrompt).trim();
    if (!textToEnhance) return "";

    set({ isEnhancing: true, originalPrompt: textToEnhance });

    try {
      const res = await api.post<{
        enhanced: string;
        original: string;
        changes: string[];
        model_used: string;
      }>("/api/intelligence/enhance-prompt", {
        prompt: textToEnhance,
        quality: get().quality,
        active_file: activeFile ?? null,
        workspace: workspace ?? null,
      });

      set({
        enhancedPrompt: res.enhanced,
        changes: res.changes,
        modelUsed: res.model_used,
        showDiff: true,
        showBar: true,
        isEnhancing: false,
      });

      return res.enhanced;
    } catch (err) {
      console.warn("[intelligenceStore] enhancement failed (fail-open)", err);
      set({
        enhancedPrompt: textToEnhance,
        changes: [],
        modelUsed: "fallback",
        showDiff: false,
        isEnhancing: false,
      });
      return textToEnhance;
    }
  },

  accept: async () => {
    set({ showDiff: false, showBar: false });
    try {
      await api.post("/api/intelligence/record-action", { action: "accept" });
    } catch {
      // Non-blocking
    }
  },

  revert: async () => {
    set({ showDiff: false, showBar: false, enhancedPrompt: "" });
    try {
      await api.post("/api/intelligence/record-action", { action: "revert" });
    } catch {
      // Non-blocking
    }
  },

  editManually: () => {
    set({ showDiff: false, showBar: false });
  },

  dismiss: () => {
    set({ showBar: false, showDiff: false });
    try {
      void api.post("/api/intelligence/record-action", { action: "dismiss" });
    } catch {
      // Non-blocking
    }
  },

  reset: () => {
    set({
      quality: null,
      originalPrompt: "",
      enhancedPrompt: "",
      changes: [],
      modelUsed: "",
      showBar: false,
      showDiff: false,
      isEnhancing: false,
    });
  },

  fetchStats: async () => {
    try {
      const stats = await api.get<EnhancementStats>("/api/intelligence/enhancement-stats");
      set({ stats });
    } catch (err) {
      console.warn("[intelligenceStore] failed to fetch stats", err);
    }
  },
}));
