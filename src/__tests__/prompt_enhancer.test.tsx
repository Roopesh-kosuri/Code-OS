import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
import { PromptEnhancerBar } from "../features/intelligence/PromptEnhancerBar";
import { AIChatPanel } from "../features/ai/AIChatPanel";
import { useIntelligenceStore } from "../stores/intelligenceStore";
import { useAIStore } from "../stores/aiStore";
import { api } from "../lib/api";

describe("Phase 5 & 5.1: Prompt Enhancement Engine UI Tests", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    localStorage.clear();
    useIntelligenceStore.getState().reset();
    useAIStore.setState({ messages: [], streaming: false });
    vi.spyOn(api, "post").mockResolvedValue({});
    vi.spyOn(api, "get").mockResolvedValue({});
  });

  // ── Phase 5.1 Required Regression Tests ────────────────────────────────────

  it("test_prompt_enhancer_bar_mounted_in_chat_panel", async () => {
    act(() => {
      useIntelligenceStore.setState({
        showBar: true,
        showDiff: false,
        quality: {
          quality: "weak",
          issues: ["Prompt is too brief (< 15 characters)"],
          score: 0.2,
        },
        originalPrompt: "fix it",
      });
    });

    await act(async () => {
      render(<AIChatPanel />);
    });

    // PromptEnhancerBar is mounted above the form in AIChatPanel
    const hintBar = screen.getByTestId("prompt-enhancer-hint-bar");
    expect(hintBar).toBeTruthy();
    expect(screen.getByText(/This prompt could be clearer. Enhance it\?/i)).toBeTruthy();
  });

  it("test_onchange_triggers_classify", async () => {
    vi.useFakeTimers();
    const postSpy = vi.spyOn(api, "post").mockResolvedValue({
      quality: "weak",
      issues: ["Prompt is too brief (< 15 characters)"],
      score: 0.2,
    });

    useIntelligenceStore.getState().classifyOnInput("fix it", "main.cpp");

    // Before 600ms debounce -> not called
    vi.advanceTimersByTime(500);
    expect(postSpy).not.toHaveBeenCalled();

    // At 600ms -> called with prompt and active_file
    await act(async () => {
      vi.advanceTimersByTime(100);
    });

    expect(postSpy).toHaveBeenCalledWith("/api/intelligence/classify-prompt", {
      prompt: "fix it",
      active_file: "main.cpp",
    });

    vi.useRealTimers();
  });

  it("test_settings_default_suggest_on", async () => {
    vi.useFakeTimers();
    const postSpy = vi.spyOn(api, "post").mockResolvedValue({
      quality: "weak",
      issues: [],
      score: 0.2,
    });

    // 1. By default, suggest is ON
    expect(localStorage.getItem("code-os:ai.suggest_prompt_enhancements") !== "false").toBe(true);

    useIntelligenceStore.getState().classifyOnInput("fix it");
    await act(async () => {
      vi.advanceTimersByTime(600);
    });
    expect(postSpy).toHaveBeenCalledTimes(1);

    // 2. When turned off in settings, classification is skipped
    localStorage.setItem("code-os:ai.suggest_prompt_enhancements", "false");
    postSpy.mockClear();

    useIntelligenceStore.getState().classifyOnInput("another weak prompt");
    await act(async () => {
      vi.advanceTimersByTime(600);
    });
    expect(postSpy).not.toHaveBeenCalled();

    vi.useRealTimers();
  });

  it("test_show_bar_set_on_weak_quality", async () => {
    vi.useFakeTimers();
    vi.spyOn(api, "post").mockResolvedValue({
      quality: "weak",
      issues: ["Lacks specific targets (no file paths, symbols, classes)"],
      score: 0.25,
    });

    useIntelligenceStore.getState().classifyOnInput("improve this");
    await act(async () => {
      vi.advanceTimersByTime(600);
    });

    const state = useIntelligenceStore.getState();
    expect(state.showBar).toBe(true);
    expect(state.quality?.quality).toBe("weak");
    expect(state.quality?.issues).toContain("Lacks specific targets (no file paths, symbols, classes)");

    vi.useRealTimers();
  });

  it("test_enhance_button_calls_backend", async () => {
    const postSpy = vi.spyOn(api, "post").mockResolvedValue({
      enhanced: "Fix bcrypt salt rounds in src/auth.py and verify 401 on incorrect credentials.",
      original: "fix it",
      changes: ["Identified specific target file", "Added verification"],
      model_used: "groq/openai/gpt-oss-20b",
    });

    act(() => {
      useIntelligenceStore.setState({
        showBar: true,
        showDiff: false,
        quality: { quality: "weak", issues: ["Too brief"], score: 0.2 },
        originalPrompt: "fix it",
      });
    });

    const mockApply = vi.fn();
    render(<PromptEnhancerBar currentPrompt="fix it" activeFile="main.cpp" onApplyEnhanced={mockApply} />);

    const enhanceBtn = screen.getByTestId("prompt-enhance-button");
    await act(async () => {
      fireEvent.click(enhanceBtn);
    });

    expect(postSpy).toHaveBeenCalledWith("/api/intelligence/enhance-prompt", expect.objectContaining({
      prompt: "fix it",
      active_file: "main.cpp",
    }));

    const state = useIntelligenceStore.getState();
    expect(state.showDiff).toBe(true);
    expect(state.enhancedPrompt).toContain("Fix bcrypt salt rounds");
  });

  it("test_use_enhanced_replaces_textarea_value", async () => {
    const original = "fix it";
    const enhanced = "Fix bcrypt salt rounds in src/auth.py and verify 401 on incorrect credentials.";

    act(() => {
      useIntelligenceStore.setState({
        showBar: true,
        showDiff: true,
        originalPrompt: original,
        enhancedPrompt: enhanced,
        changes: ["Identified specific target file"],
        modelUsed: "groq/openai/gpt-oss-20b",
      });
    });

    const mockApply = vi.fn();
    render(<PromptEnhancerBar currentPrompt={original} onApplyEnhanced={mockApply} />);

    const useEnhancedBtn = screen.getByTestId("prompt-use-enhanced-button");
    await act(async () => {
      fireEvent.click(useEnhancedBtn);
    });

    // Replaces textarea value via callback
    expect(mockApply).toHaveBeenCalledWith(enhanced);
    // Closes diff card and resets showBar
    expect(useIntelligenceStore.getState().showDiff).toBe(false);
    expect(useIntelligenceStore.getState().showBar).toBe(false);
  });

  // ── Baseline Phase 5 Tests ────────────────────────────────────────────────

  it("test_bar_appears_for_weak_prompt", () => {
    act(() => {
      useIntelligenceStore.setState({
        showBar: true,
        showDiff: false,
        quality: {
          quality: "weak",
          issues: ["Prompt is too brief (< 15 characters)"],
          score: 0.2,
        },
        originalPrompt: "fix it",
      });
    });

    const mockApply = vi.fn();
    render(<PromptEnhancerBar currentPrompt="fix it" onApplyEnhanced={mockApply} />);

    expect(screen.getByTestId("prompt-enhancer-hint-bar")).toBeTruthy();
    expect(screen.getByText(/This prompt could be clearer. Enhance it\?/i)).toBeTruthy();
    expect(screen.getByTestId("prompt-enhance-button")).toBeTruthy();
  });

  it("test_diff_card_shows_original_and_enhanced", () => {
    const original = "fix it";
    const enhanced = "Fix bcrypt salt rounds in src/auth.py and verify 401 on incorrect credentials.";

    act(() => {
      useIntelligenceStore.setState({
        showBar: true,
        showDiff: true,
        originalPrompt: original,
        enhancedPrompt: enhanced,
        changes: ["Identified specific target file(s)", "Added concrete verification & success criteria"],
        modelUsed: "groq/openai/gpt-oss-20b",
      });
    });

    const mockApply = vi.fn();
    render(<PromptEnhancerBar currentPrompt={original} onApplyEnhanced={mockApply} />);

    expect(screen.getByTestId("prompt-enhancer-diff-card")).toBeTruthy();
    expect(screen.getByText(original)).toBeTruthy();
    expect(screen.getByText(enhanced)).toBeTruthy();
    expect(screen.getByText(/groq\/openai\/gpt-oss-20b/i)).toBeTruthy();
  });

  it("test_accept_sends_enhanced_text", async () => {
    const original = "make better";
    const enhanced = "Refactor database connection pool in src/db.ts to handle reconnects cleanly.";

    act(() => {
      useIntelligenceStore.setState({
        showBar: true,
        showDiff: true,
        originalPrompt: original,
        enhancedPrompt: enhanced,
        changes: ["Identified specific target file(s)"],
        modelUsed: "openai/gpt-4o-mini",
      });
    });

    const mockApply = vi.fn();
    render(<PromptEnhancerBar currentPrompt={original} onApplyEnhanced={mockApply} />);

    const useEnhancedBtn = screen.getByTestId("prompt-use-enhanced-button");
    await act(async () => {
      fireEvent.click(useEnhancedBtn);
    });

    expect(mockApply).toHaveBeenCalledWith(enhanced);
    expect(useIntelligenceStore.getState().showDiff).toBe(false);
    expect(useIntelligenceStore.getState().showBar).toBe(false);
  });

  it("test_keep_original_sends_original", async () => {
    const original = "do the thing";
    const enhanced = "Execute automated database migration scripts.";

    act(() => {
      useIntelligenceStore.setState({
        showBar: true,
        showDiff: true,
        originalPrompt: original,
        enhancedPrompt: enhanced,
        changes: [],
        modelUsed: "groq/openai/gpt-oss-20b",
      });
    });

    const mockApply = vi.fn();
    render(<PromptEnhancerBar currentPrompt={original} onApplyEnhanced={mockApply} />);

    const keepOriginalBtn = screen.getByTestId("prompt-keep-original-button");
    await act(async () => {
      fireEvent.click(keepOriginalBtn);
    });

    expect(mockApply).not.toHaveBeenCalled();
    expect(useIntelligenceStore.getState().showDiff).toBe(false);
    expect(useIntelligenceStore.getState().showBar).toBe(false);
  });

  it("test_auto_enhance_off_requires_confirm", () => {
    localStorage.setItem("code-os:ai.auto_enhance_weak_prompts", "false");

    const store = useIntelligenceStore.getState();
    expect(store.showDiff).toBe(false);

    act(() => {
      useIntelligenceStore.setState({
        showBar: true,
        showDiff: false,
        quality: { quality: "weak", issues: ["Too brief"], score: 0.2 },
        originalPrompt: "fix bug",
      });
    });

    const mockApply = vi.fn();
    render(<PromptEnhancerBar currentPrompt="fix bug" onApplyEnhanced={mockApply} />);

    // Shows hint bar asking for confirmation, diff card is not open until user clicks Enhance
    expect(screen.getByTestId("prompt-enhancer-hint-bar")).toBeTruthy();
    expect(screen.queryByTestId("prompt-enhancer-diff-card")).toBeNull();
  });

  it("test_diff_card_header_only_title_and_badge_no_pseudo_buttons", () => {
    act(() => {
      useIntelligenceStore.setState({
        showBar: true,
        showDiff: true,
        originalPrompt: "fix it",
        enhancedPrompt: "Fix bug in main.py",
        changes: ["Identified specific target file", "Added verification criteria"],
        modelUsed: "groq/openai/gpt-oss-20b",
      });
    });

    const mockApply = vi.fn();
    render(<PromptEnhancerBar currentPrompt="fix it" onApplyEnhanced={mockApply} />);

    // Header has title and badge
    expect(screen.getByText("Enhanced Prompt Preview")).toBeTruthy();
    expect(screen.getByText("groq/openai/gpt-oss-20b")).toBeTruthy();
    // Truncated pseudo buttons are removed
    expect(screen.queryByText("+ Identified specific target file")).toBeNull();
    expect(screen.queryByText("+ Added verification criteria")).toBeNull();
  });

  it("test_pass_through_results_do_not_pop_card", async () => {
    // Conversational queries pass through without popping diff card or showing error
    vi.spyOn(api, "post").mockResolvedValueOnce({
      enhanced: "hi how are you?",
      original: "hi how are you?",
      changes: [],
      model_used: "pass-through",
      error: null,
    });

    const res = await useIntelligenceStore.getState().enhance("hi how are you?");
    expect(res).toBe("hi how are you?");
    expect(useIntelligenceStore.getState().showDiff).toBe(false);
    expect(useIntelligenceStore.getState().showBar).toBe(false);
    expect(useIntelligenceStore.getState().enhancementError).toBeNull();
  });

  it("test_enhance_action_updates_store_state", async () => {
    // 1. Success case: updates showDiff=true, showBar=true, error=null
    vi.spyOn(api, "post").mockResolvedValueOnce({
      enhanced: "Fix authentication handler in src/auth.py",
      original: "fix it",
      changes: ["Identified target file"],
      model_used: "groq/llama-3.1-8b-instant",
      error: null,
    });

    await useIntelligenceStore.getState().enhance("fix it", "src/auth.py");
    const stateSuccess = useIntelligenceStore.getState();
    expect(stateSuccess.showDiff).toBe(true);
    expect(stateSuccess.showBar).toBe(true);
    expect(stateSuccess.enhancedPrompt).toBe("Fix authentication handler in src/auth.py");
    expect(stateSuccess.enhancementError).toBeNull();

    // 2. Fail case: sets showDiff=false, showBar=true (never silently disappears), error message set
    vi.spyOn(api, "post").mockResolvedValueOnce({
      enhanced: "fix it",
      original: "fix it",
      changes: [],
      model_used: "fail-open",
      error: "Enhancement model returned an empty or invalid response",
    });

    await useIntelligenceStore.getState().enhance("fix it", "src/auth.py");
    const stateFail = useIntelligenceStore.getState();
    expect(stateFail.showDiff).toBe(false);
    expect(stateFail.showBar).toBe(true); // Must remain visible per UX contract!
    expect(stateFail.enhancementError).toBe("Enhancement model returned an empty or invalid response");
  });

  it("test_enhance_timeout_shows_error_not_disappear", async () => {
    vi.spyOn(api, "post").mockRejectedValueOnce(new Error("Network timeout after 3000ms"));

    act(() => {
      useIntelligenceStore.setState({
        showBar: true,
        showDiff: false,
        originalPrompt: "fix it",
        quality: { quality: "weak", issues: ["Too brief"], score: 0.2 },
      });
    });

    const mockApply = vi.fn();
    const { rerender } = render(
      <PromptEnhancerBar currentPrompt="fix it" onApplyEnhanced={mockApply} />
    );

    // Click Enhance
    const enhanceBtn = screen.getByTestId("prompt-enhance-button");
    await act(async () => {
      fireEvent.click(enhanceBtn);
    });

    // Re-render component with new store state
    rerender(<PromptEnhancerBar currentPrompt="fix it" onApplyEnhanced={mockApply} />);

    // Card NEVER disappears silently! Error card is shown.
    const errorCard = screen.getByTestId("prompt-enhancer-error-card");
    expect(errorCard).toBeTruthy();
    expect(screen.getByText(/Enhancement unavailable/i)).toBeTruthy();

    // Explicit actions available: [Use Original], [Retry], [Dismiss]
    const useOrigBtn = screen.getByTestId("prompt-use-original-button");
    const retryBtn = screen.getByTestId("prompt-retry-button");
    const dismissBtn = screen.getByTestId("prompt-dismiss-button");
    expect(useOrigBtn).toBeTruthy();
    expect(retryBtn).toBeTruthy();
    expect(dismissBtn).toBeTruthy();

    // Clicking [Use Original] preserves original prompt and dismisses error
    await act(async () => {
      fireEvent.click(useOrigBtn);
    });
    expect(useIntelligenceStore.getState().showBar).toBe(false);
    expect(useIntelligenceStore.getState().enhancementError).toBeNull();
    // Textarea was not overwritten with garbage
    expect(mockApply).not.toHaveBeenCalled();
  });

  it("test_enhance_model_unreachable_shows_clear_error", async () => {
    vi.spyOn(api, "post").mockResolvedValueOnce({
      enhanced: "improve performance",
      original: "improve performance",
      changes: [],
      model_used: "fallback",
      error: "Enhancement unavailable (model server unreachable)",
    });

    act(() => {
      useIntelligenceStore.setState({
        showBar: true,
        showDiff: false,
        originalPrompt: "improve performance",
        quality: { quality: "weak", issues: ["Too brief"], score: 0.2 },
      });
    });

    const mockApply = vi.fn();
    render(<PromptEnhancerBar currentPrompt="improve performance" onApplyEnhanced={mockApply} />);

    // Trigger enhance
    await act(async () => {
      await useIntelligenceStore.getState().enhance("improve performance");
    });

    // Error card appears with clear message
    expect(screen.getByTestId("prompt-enhancer-error-card")).toBeTruthy();
    expect(screen.getByText("Enhancement unavailable (model server unreachable)")).toBeTruthy();
    expect(screen.getByTestId("prompt-retry-button")).toBeTruthy();
    expect(screen.getByTestId("prompt-use-original-button")).toBeTruthy();
  });
});


