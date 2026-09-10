import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { useFileUploadStore } from "../features/files/fileUploadStore";
import { useAIStore } from "../stores/aiStore";
import { useTeamStore } from "../features/ai/console/teamStore";
import { AIChatPanel } from "../features/ai/AIChatPanel";
import { api } from "../lib/api";

// Mock API
vi.mock("../lib/api", () => ({
  api: {
    get: vi.fn().mockResolvedValue([]),
    post: vi.fn().mockResolvedValue({ job_id: "team_job_test_1", status: "running", task_count: 4 }),
    delete: vi.fn().mockResolvedValue({}),
    streamSSE: vi.fn().mockResolvedValue(undefined),
  },
}));

describe("File Upload Context Injection Frontend Regression Tests", () => {
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
    useTeamStore.setState({
      teamMessages: [],
      activeJobId: null,
      jobStatus: "idle",
      tasks: [],
    });
  });

  // ── Test 1: file_ids sent with streamSSE request ─────────────────────────────
  it("test_file_ids_sent_with_stream_request: streamSSE includes file_ids from upload store", async () => {
    useFileUploadStore.setState({
      uploadedFiles: [
        {
          file_id: "file_alpha_123",
          filename: "system_architecture.pdf",
          mime_type: "application/pdf",
          size: 4096,
          content_preview: "System Architecture Overview",
          content: "System Architecture Overview with microservices and API gateways.",
        },
      ],
    });

    await useAIStore.getState().sendMessage("What is described in this document?");

    expect(api.streamSSE).toHaveBeenCalled();
    const [streamPath, streamBody] = (api.streamSSE as any).mock.calls[0];
    expect(streamPath).toBe("/api/ai/chat-agent/stream");
    expect(streamBody).toHaveProperty("file_ids");
    expect(streamBody.file_ids).toEqual(["file_alpha_123"]);
  });

  // ── Test 2: attached chip persists on user message bubble ───────────────────
  it("test_attached_chip_persists_on_message: sent message renders persistent chip", async () => {
    useAIStore.setState({
      messages: [
        {
          role: "user",
          content: "Summarize this architecture document",
          file_ids: ["file_alpha_123"],
          attached_files: [
            {
              file_id: "file_alpha_123",
              filename: "system_architecture.pdf",
              mime_type: "application/pdf",
              size: 4096,
              content_preview: "System Architecture Overview",
            },
          ],
          created_at: new Date().toISOString(),
        },
      ],
    });

    render(<AIChatPanel />);

    const chipsContainer = screen.getByTestId("message-attached-files-chips");
    expect(chipsContainer).toBeDefined();

    const fileChip = screen.getByTestId("message-file-chip-file_alpha_123");
    expect(fileChip).toBeDefined();
    expect(fileChip.textContent).toContain("system_architecture.pdf");
    expect(fileChip.textContent).toContain("4.0 KB");
  });

  // ── Test 3: chip click opens preview modal ──────────────────────────────────
  it("test_chip_opens_preview_modal: clicking persistent chip calls openPreview", async () => {
    const openPreviewSpy = vi.spyOn(useFileUploadStore.getState(), "openPreview");

    useAIStore.setState({
      messages: [
        {
          role: "user",
          content: "Explain the protocols in this spec",
          file_ids: ["spec_flux_456"],
          attached_files: [
            {
              file_id: "spec_flux_456",
              filename: "flux_spec.py",
              mime_type: "text/x-python",
              size: 1024,
              content: "FLUX_CAPACITOR_VOLTAGE = 1.21",
            },
          ],
          created_at: new Date().toISOString(),
        },
      ],
    });

    render(<AIChatPanel />);

    const fileChip = screen.getByTestId("message-file-chip-spec_flux_456");
    expect(fileChip).toBeDefined();

    fireEvent.click(fileChip);

    await waitFor(() => {
      expect(useFileUploadStore.getState().isPreviewModalOpen).toBe(true);
      expect(useFileUploadStore.getState().activePreviewFile?.filename).toBe("flux_spec.py");
    });
  });

  // ── Test 4: team console propagates file_ids ────────────────────────────────
  it("test_team_console_propagates_file_ids: team job submission includes file_ids", async () => {
    useFileUploadStore.setState({
      uploadedFiles: [
        {
          file_id: "team_file_789",
          filename: "team_spec.pdf",
          mime_type: "application/pdf",
          size: 8192,
          content_preview: "Team Spec",
        },
      ],
    });

    await useTeamStore.getState().submitTeamJob("/tmp/test_workspace", "Execute DAG workflow");

    expect(api.post).toHaveBeenCalledWith(
      "/api/team/jobs",
      expect.objectContaining({
        workspace: "/tmp/test_workspace",
        user_request: "Execute DAG workflow",
        file_ids: ["team_file_789"],
      })
    );
  });
});
