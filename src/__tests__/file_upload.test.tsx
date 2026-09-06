import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { FileUploadZone } from "../features/files/FileUploadZone";
import { FilePreviewModal } from "../features/files/FilePreviewModal";
import { RonyChatUploadWrapper } from "../features/files/RonyChatUploadWrapper";
import { useFileUploadStore } from "../features/files/fileUploadStore";
import { api } from "../lib/api";

// Mock API
vi.mock("../lib/api", () => ({
  api: {
    get: vi.fn(),
    post: vi.fn(),
    delete: vi.fn(),
    streamSSE: vi.fn(),
  },
}));

describe("File Upload & Context Injection Frontend Tests", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useFileUploadStore.setState({
      uploadedFiles: [],
      isUploading: false,
      uploadProgress: {},
      activePreviewFile: null,
      isPreviewModalOpen: false,
    });
  });

  // ── Test 1: Upload zone renders ─────────────────────────────────────────────
  it("test_upload_zone_renders: displays dashed drop zone and browse instructions", () => {
    render(<FileUploadZone />);

    const dropzone = screen.getByTestId("drag-drop-dropzone");
    expect(dropzone).toBeDefined();
    expect(dropzone.textContent).toContain("Drop files here or click to browse");

    const hiddenInput = screen.getByTestId("file-input-hidden") as HTMLInputElement;
    expect(hiddenInput).toBeDefined();
    expect(hiddenInput.getAttribute("multiple")).not.toBeNull();
    expect(hiddenInput.getAttribute("accept")).toContain(".pdf");
  });

  // ── Test 2: Drag & drop uploads file ────────────────────────────────────────
  it("test_drag_drop_uploads_file: dropping a file triggers API upload and updates store", async () => {
    const mockResponse = {
      file_id: "file-uuid-123",
      filename: "spec.pdf",
      content_preview: "Architecture Specification for Code-OS multi-agent orchestrator.",
      metadata: {
        filename: "spec.pdf",
        size_bytes: 2048,
        mime_type: "application/pdf",
        page_count: 2,
        word_count: 50,
        extracted_at: new Date().toISOString(),
      },
    };
    (api.post as any).mockResolvedValueOnce(mockResponse);

    render(<FileUploadZone />);

    const dropzone = screen.getByTestId("drag-drop-dropzone");
    const testFile = new File(["dummy pdf content"], "spec.pdf", { type: "application/pdf" });

    // Trigger drop event
    fireEvent.drop(dropzone, {
      dataTransfer: {
        files: [testFile],
      },
    });

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith("/api/files/upload", expect.any(FormData));
    });

    await waitFor(() => {
      const state = useFileUploadStore.getState();
      expect(state.uploadedFiles.length).toBe(1);
      expect(state.uploadedFiles[0].filename).toBe("spec.pdf");
      expect(state.uploadedFiles[0].file_id).toBe("file-uuid-123");
    });
  });

  // ── Test 3: Uploaded file shows preview ─────────────────────────────────────
  it("test_uploaded_file_shows_preview: displays filename, size, and preview snippet", () => {
    useFileUploadStore.setState({
      uploadedFiles: [
        {
          file_id: "file-code-456",
          filename: "algorithm.py",
          mime_type: "text/x-python",
          size: 1024,
          content_preview: "def binary_search(arr, target):\n    low = 0\n    high = len(arr) - 1",
          content: "def binary_search(arr, target):\n    low = 0\n    high = len(arr) - 1\n    return -1",
          metadata: {
            filename: "algorithm.py",
            size_bytes: 1024,
            mime_type: "text/x-python",
            word_count: 12,
            extracted_at: new Date().toISOString(),
          },
        },
      ],
    });

    render(<FileUploadZone />);

    expect(screen.getByText("algorithm.py")).toBeDefined();
    expect(screen.getByText("(1.0 KB)")).toBeDefined();

    const snippet = screen.getByTestId("file-preview-snippet-file-code-456");
    expect(snippet).toBeDefined();
    expect(snippet.textContent).toContain("def binary_search");
  });

  // ── Test 4: Remove file clears from list ─────────────────────────────────────
  it("test_remove_file_clears_from_list: clicking remove deletes file from state and calls API", async () => {
    (api.delete as any).mockResolvedValueOnce({ status: "ok", deleted: true });

    useFileUploadStore.setState({
      uploadedFiles: [
        {
          file_id: "file-to-delete-789",
          filename: "delete_me.txt",
          mime_type: "text/plain",
          size: 512,
          content_preview: "Temporary data to remove.",
        },
      ],
    });

    render(<FileUploadZone />);

    expect(screen.getByText("delete_me.txt")).toBeDefined();

    const removeBtn = screen.getByTestId("remove-file-btn-file-to-delete-789");
    fireEvent.click(removeBtn);

    await waitFor(() => {
      expect(useFileUploadStore.getState().uploadedFiles.length).toBe(0);
      expect(api.delete).toHaveBeenCalledWith("/api/files/file-to-delete-789", expect.anything());
    });
  });

  // ── Test 5: File preview modal opens ────────────────────────────────────────
  it("test_file_preview_modal_opens: clicking file opens modal showing full content and copy button", async () => {
    const fileItem = {
      file_id: "file-preview-999",
      filename: "architecture_spec.pdf",
      mime_type: "application/pdf",
      size: 4096,
      content_preview: "Full Architecture Specification Content",
      content: "Full Architecture Specification Content Page 1\n\n--- Page 2 ---\nPage 2 Implementation Details",
      metadata: {
        filename: "architecture_spec.pdf",
        size_bytes: 4096,
        mime_type: "application/pdf",
        page_count: 2,
        word_count: 35,
        extracted_at: new Date().toISOString(),
      },
    };

    useFileUploadStore.setState({
      uploadedFiles: [fileItem],
    });

    render(
      <>
        <FileUploadZone />
        <FilePreviewModal />
      </>
    );

    // Click on preview trigger
    const previewBtn = screen.getByTestId("preview-btn-file-preview-999");
    fireEvent.click(previewBtn);

    await waitFor(() => {
      expect(screen.getByTestId("file-preview-modal")).toBeDefined();
    });

    // Content and metadata visible
    expect(screen.getAllByText("architecture_spec.pdf").length).toBeGreaterThanOrEqual(2);
    expect(screen.getByTestId("copy-content-btn")).toBeDefined();
    expect(screen.getAllByText(/Full Architecture Specification/).length).toBeGreaterThanOrEqual(2);

    // Close button closes modal
    const closeBtn = screen.getByTestId("close-preview-btn");
    fireEvent.click(closeBtn);

    await waitFor(() => {
      expect(screen.queryByTestId("file-preview-modal")).toBeNull();
    });
  });

  // ── Test 6: Attached files badge in chat ────────────────────────────────────
  it("test_attached_files_badge_in_chat: shows '3 files attached' badge and opens preview on click", async () => {
    useFileUploadStore.setState({
      uploadedFiles: [
        { file_id: "f1", filename: "spec.pdf", mime_type: "application/pdf", size: 1000, content_preview: "Spec" },
        { file_id: "f2", filename: "models.py", mime_type: "text/x-python", size: 2000, content_preview: "Models" },
        { file_id: "f3", filename: "diagram.png", mime_type: "image/png", size: 50000, content_preview: "Diagram" },
      ],
    });

    render(
      <RonyChatUploadWrapper>
        <div data-testid="dummy-chat-panel">Mock Chat Content</div>
      </RonyChatUploadWrapper>
    );

    const badge = screen.getByTestId("attached-files-badge");
    expect(badge).toBeDefined();
    expect(badge.textContent).toContain("3 files attached");

    // Click badge opens preview modal
    fireEvent.click(badge);

    await waitFor(() => {
      expect(screen.getByTestId("file-preview-modal")).toBeDefined();
      expect(useFileUploadStore.getState().isPreviewModalOpen).toBe(true);
    });
  });
});
