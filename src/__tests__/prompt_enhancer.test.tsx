import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
import { PromptEnhancerBar } from "../features/intelligence/PromptEnhancerBar";
import { useIntelligenceStore } from "../stores/intelligenceStore";
import { api } from "../lib/api";

describe("Phase 5: Prompt Enhancement Engine UI Tests", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    localStorage.clear();
    useIntelligenceStore.getState().reset();
    vi.spyOn(api, "post").mockResolvedValue({});
    vi.spyOn(api, "get").mockResolvedValue({});
  });

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
});
