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
  enhancementError: string | null;
  stats: EnhancementStats;

  classifyOnInput: (prompt: string, activeFile?: string | null, workspace?: string | null) => void;
  enhance: (prompt?: string, activeFile?: string | null, workspace?: string | null) => Promise<string>;
  accept: () => Promise<void>;
  revert: () => Promise<void>;
  editManually: () => void;
  dismiss: () => void;
  reset: () => void;
  clearError: () => void;
  fetchStats: () => Promise<void>;
}

let classifyTimer: ReturnType<typeof setTimeout> | null = null;
let currentClassifyRevision = 0;
let classifyAbortController: AbortController | null = null;

export const useIntelligenceStore = create<IntelligenceState>((set, get) => ({
  quality: null,
  originalPrompt: "",
  enhancedPrompt: "",
  changes: [],
  modelUsed: "",
  showBar: false,
  showDiff: false,
  isEnhancing: false,
  enhancementError: null,
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
    if (classifyAbortController) {
      classifyAbortController.abort();
      classifyAbortController = null;
    }

    const trimmed = prompt.trim();
    if (!trimmed) {
      currentClassifyRevision++;
      set({ showBar: false, showDiff: false, quality: null, originalPrompt: "", enhancedPrompt: "", enhancementError: null });
      return;
    }

    // Check user settings toggle: Suggest prompt enhancements (default ON)
    const suggestEnabled = localStorage.getItem("code-os:ai.suggest_prompt_enhancements") !== "false";
    if (!suggestEnabled) {
      currentClassifyRevision++;
      set({ showBar: false, showDiff: false, enhancementError: null });
      return;
    }

    // AUD-013: Revision ID and AbortController gate to discard out-of-order/stale completions
    const thisRevision = ++currentClassifyRevision;
    const controller = new AbortController();
    classifyAbortController = controller;

    // Debounce by 600ms
    classifyTimer = setTimeout(async () => {
      try {
        const res = await api.post<PromptQuality>(
          "/api/intelligence/classify-prompt",
          {
            prompt: trimmed,
            active_file: activeFile ?? null,
          }
        );

        // Discard stale response if a newer input has arrived or this run was aborted (AUD-013)
        if (thisRevision !== currentClassifyRevision || controller.signal.aborted) {
          return;
        }

        if (res.quality === "weak" || res.quality === "vague" || res.quality !== "good") {
          set({
            quality: res,
            originalPrompt: trimmed,
            showBar: true,
            enhancementError: null,
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
            enhancementError: null,
          });
        }
      } catch (err: any) {
        if (err?.name === "AbortError" || thisRevision !== currentClassifyRevision) {
          return;
        }
        console.warn("[intelligenceStore] classification failed", err);
      }
    }, 600);
  },

  enhance: async (prompt?: string, activeFile?: string | null, workspace?: string | null): Promise<string> => {
    const textToEnhance = (prompt?.trim() || get().originalPrompt).trim();
    if (!textToEnhance) return "";

    set({ isEnhancing: true, originalPrompt: textToEnhance, enhancementError: null });

    try {
      const res = await api.post<{
        enhanced: string;
        original: string;
        changes: string[];
        model_used: string;
        error?: string | null;
      }>("/api/intelligence/enhance-prompt", {
        prompt: textToEnhance,
        quality: get().quality,
        active_file: activeFile ?? null,
        workspace: workspace ?? null,
      });

      // Conversational turns and already-good prompts pass through without diff card or error
      if (res.model_used === "pass-through") {
        set({
          enhancedPrompt: res.enhanced || textToEnhance,
          changes: [],
          modelUsed: res.model_used,
          showDiff: false,
          showBar: false,
          isEnhancing: false,
          enhancementError: null,
        });
        return res.enhanced || textToEnhance;
      }

      const isFailure =
        Boolean(res.error) ||
        res.model_used === "fail-open" ||
        res.model_used === "fallback" ||
        !res.enhanced ||
        res.enhanced.trim() === textToEnhance.trim() ||
        res.enhanced.trim() === (res.original || "").trim();

      if (isFailure) {
        const errorMsg =
          res.error ||
          (res.model_used === "fail-open"
            ? "Enhancement unavailable (model returned no changes or failed open)"
            : "Enhancement unavailable (model unreachable or timed out)");

        set({
          enhancedPrompt: textToEnhance,
          changes: [],
          modelUsed: res.model_used,
          showDiff: false,
          showBar: true, // Keep card visible per UX contract!
          isEnhancing: false,
          enhancementError: errorMsg,
        });
        return textToEnhance;
      }

      set({
        enhancedPrompt: res.enhanced,
        changes: res.changes,
        modelUsed: res.model_used,
        showDiff: true,
        showBar: true,
        isEnhancing: false,
        enhancementError: null,
      });

      return res.enhanced;
    } catch (err) {
      console.warn("[intelligenceStore] enhancement failed (fail-open)", err);
      set({
        enhancedPrompt: textToEnhance,
        changes: [],
        modelUsed: "fallback",
        showDiff: false,
        showBar: true, // Keep card visible per UX contract!
        isEnhancing: false,
        enhancementError: "Enhancement unavailable (request timed out or server error)",
      });
      return textToEnhance;
    }
  },

  accept: async () => {
    set({ showDiff: false, showBar: false, enhancementError: null });
    try {
      await api.post("/api/intelligence/record-action", { action: "accept" });
    } catch {
      // Non-blocking
    }
  },

  revert: async () => {
    set({ showDiff: false, showBar: false, enhancedPrompt: "", enhancementError: null });
    try {
      await api.post("/api/intelligence/record-action", { action: "revert" });
    } catch {
      // Non-blocking
    }
  },

  editManually: () => {
    set({ showDiff: false, showBar: false, enhancementError: null });
  },

  dismiss: () => {
    if (classifyTimer) {
      clearTimeout(classifyTimer);
      classifyTimer = null;
    }
    if (classifyAbortController) {
      classifyAbortController.abort();
      classifyAbortController = null;
    }
    currentClassifyRevision++;
    set({ showBar: false, showDiff: false, enhancementError: null });
    try {
      void api.post("/api/intelligence/record-action", { action: "dismiss" });
    } catch {
      // Non-blocking
    }
  },

  clearError: () => {
    set({ enhancementError: null });
  },

  reset: () => {
    if (classifyTimer) {
      clearTimeout(classifyTimer);
      classifyTimer = null;
    }
    if (classifyAbortController) {
      classifyAbortController.abort();
      classifyAbortController = null;
    }
    currentClassifyRevision++;
    set({
      quality: null,
      originalPrompt: "",
      enhancedPrompt: "",
      changes: [],
      modelUsed: "",
      showBar: false,
      showDiff: false,
      isEnhancing: false,
      enhancementError: null,
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
