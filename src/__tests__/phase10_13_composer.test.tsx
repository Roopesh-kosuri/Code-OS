import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { RonyChatUploadWrapper } from "../features/files/RonyChatUploadWrapper";
import { AIChatPanel } from "../features/ai/AIChatPanel";
import { useFileUploadStore } from "../features/files/fileUploadStore";
import { useAIStore } from "../stores/aiStore";

vi.mock("../lib/api", () => ({
  api: {
    get: vi.fn().mockResolvedValue([]),
    post: vi.fn().mockResolvedValue({}),
    delete: vi.fn().mockResolvedValue({}),
    streamSSE: vi.fn().mockResolvedValue(undefined),
  },
}));

describe("Phase 10.13: Drop-Spec Bar Removal & Composer Attachments", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useFileUploadStore.setState({
      uploadedFiles: [],
      isUploading: false,
      uploadProgress: {},
      activePreviewFile: null,
      isPreviewModalOpen: false,
    });
    useAIStore.setState({
      messages: [],
      streaming: false,
      error: null,
    });
  });

  // ── Test 1: test_composer_has_no_drop_spec_bar ─────────────────────────────
  it("test_composer_has_no_drop_spec_bar: composer does not render drop-spec bar or add-files button", () => {
    render(
      <RonyChatUploadWrapper>
        <AIChatPanel />
      </RonyChatUploadWrapper>
    );

    // Assert "Drop spec or code to inject" is completely absent
    expect(screen.queryByText(/Drop spec or code to inject/i)).toBeNull();

    // Assert "+ Add Files" toggle button is completely absent
    expect(screen.queryByText(/\+ Add Files/i)).toBeNull();
    expect(screen.queryByTestId("toggle-upload-zone-btn")).toBeNull();

    // Assert textarea is present with full space
    const textarea = screen.getByTestId("chat-prompt-textarea");
    expect(textarea).toBeDefined();
  });

  // ── Test 2: test_paperclip_attachment_still_works ──────────────────────────
  it("test_paperclip_attachment_still_works: bottom toolbar paperclip button is present and triggers file upload", () => {
    render(
      <RonyChatUploadWrapper>
        <AIChatPanel />
      </RonyChatUploadWrapper>
    );

    // Locate paperclip button in bottom toolbar
    const paperclipBtn = screen.getByTitle(/Attach file \/ context/i);
    expect(paperclipBtn).toBeDefined();

    // Locate hidden file input
    const fileInput = document.querySelector('input[type="file"]:not([accept*="image"])') as HTMLInputElement;
    expect(fileInput).toBeDefined();

    // Click triggers click on the file input
    const clickSpy = vi.spyOn(fileInput, "click");
    fireEvent.click(paperclipBtn);
    expect(clickSpy).toHaveBeenCalled();
  });

  // ── Test 3: test_textarea_drag_drop_still_works ────────────────────────────
  it("test_textarea_drag_drop_still_works: drag-over and drop events are accepted without error", () => {
    render(
      <RonyChatUploadWrapper>
        <AIChatPanel />
      </RonyChatUploadWrapper>
    );

    const textarea = screen.getByTestId("chat-prompt-textarea");
    const container = textarea.closest("form") || textarea.parentElement;
    expect(container).toBeDefined();

    // Fire dragOver
    fireEvent.dragOver(container!, { dataTransfer: { files: [] } });

    // Fire drop with a mock text file
    const mockFile = new File(["test content"], "spec.md", { type: "text/markdown" });
    fireEvent.drop(container!, {
      dataTransfer: {
        files: [mockFile],
      },
    });

    // Verify no throw and textarea remains intact
    expect(screen.getByTestId("chat-prompt-textarea")).toBeDefined();
  });
});
