/**
 * staging_review.test.tsx — Frontend test suite for Smart Staging / PR View.
 *
 * Required Tests:
 * 1. test_file_list_renders_all_staged_files
 * 2. test_diff_viewer_shows_monaco_diff
 * 3. test_checkbox_approves_file
 * 4. test_chunk_approve_reject_buttons_work
 * 5. test_apply_button_writes_approved_to_disk
 */

import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { StagingReviewPanel } from "../features/staging/StagingReviewPanel";
import { useStagingStore, type StagedFile, type MonacoDiffData } from "../features/staging/stagingStore";
import { api } from "../lib/api";

// Mock API
vi.mock("../lib/api", () => ({
  api: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
  },
}));

describe("Smart Staging / PR View Frontend Suite", () => {
  const mockFiles: StagedFile[] = [
    {
      path: "src/auth/login.ts",
      status: "modified",
      lines_added: 12,
      lines_removed: 3,
      approved: false,
      chunks: [
        {
          index: 0,
          type: "context",
          content: "import { auth } from './core';\n",
          approved: null,
          start_line: 1,
          end_line: 1,
        },
        {
          index: 1,
          type: "delete",
          content: "const oldToken = getLegacy();\n",
          original_lines: ["const oldToken = getLegacy();"],
          new_lines: [],
          approved: false,
          start_line: 2,
          end_line: 2,
        },
        {
          index: 2,
          type: "insert",
          content: "const newToken = await getSecureToken();\n",
          original_lines: [],
          new_lines: ["const newToken = await getSecureToken();"],
          approved: false,
          start_line: 2,
          end_line: 2,
        },
      ],
    },
    {
      path: "src/components/Header.tsx",
      status: "added",
      lines_added: 25,
      lines_removed: 0,
      approved: false,
      chunks: [
        {
          index: 0,
          type: "insert",
          content: "export function Header() { return <header />; }\n",
          original_lines: [],
          new_lines: ["export function Header() { return <header />; }"],
          approved: false,
          start_line: 1,
          end_line: 1,
        },
      ],
    },
    {
      path: "src/deprecated/oldUtil.ts",
      status: "deleted",
      lines_added: 0,
      lines_removed: 18,
      approved: false,
      chunks: [
        {
          index: 0,
          type: "delete",
          content: "export const unused = true;\n",
          original_lines: ["export const unused = true;"],
          new_lines: [],
          approved: false,
          start_line: 1,
          end_line: 1,
        },
      ],
    },
  ];

  const mockDiffData: MonacoDiffData = {
    job_id: "job_pr_123",
    path: "src/auth/login.ts",
    file_path: "src/auth/login.ts",
    status: "modified",
    lines_added: 12,
    lines_removed: 3,
    approved: false,
    original_content: "import { auth } from './core';\nconst oldToken = getLegacy();\n",
    updated_content: "import { auth } from './core';\nconst newToken = await getSecureToken();\n",
    diff_text: "--- a/src/auth/login.ts\n+++ b/src/auth/login.ts\n@@ -1,2 +1,2 @@\n",
    lines: [
      {
        line_number: 1,
        orig_line_number: 1,
        new_line_number: 1,
        type: "context",
        content: "import { auth } from './core';",
        chunk_index: 0,
      },
      {
        line_number: 2,
        orig_line_number: 2,
        new_line_number: null,
        type: "delete",
        content: "const oldToken = getLegacy();",
        chunk_index: 1,
      },
      {
        line_number: 3,
        orig_line_number: null,
        new_line_number: 2,
        type: "insert",
        content: "const newToken = await getSecureToken();",
        chunk_index: 2,
      },
    ],
    chunks: mockFiles[0].chunks,
  };

  beforeEach(() => {
    vi.clearAllMocks();
    useStagingStore.setState({
      files: [...mockFiles],
      selectedFile: "src/auth/login.ts",
      activeDiff: { ...mockDiffData },
      selectedFilePaths: ["src/auth/login.ts"],
      jobId: "job_pr_123",
      isOpen: true,
      isLoading: false,
      isApplying: false,
      error: null,
    });
  });

  it("test_file_list_renders_all_staged_files", async () => {
    render(<StagingReviewPanel />);

    // Check all files rendered in left column
    expect(screen.getByTestId("staged-file-item-src/auth/login.ts")).toBeTruthy();
    expect(screen.getByTestId("staged-file-item-src/components/Header.tsx")).toBeTruthy();
    expect(screen.getByTestId("staged-file-item-src/deprecated/oldUtil.ts")).toBeTruthy();

    // Check status badges
    expect(screen.getByTestId("status-badge-src/auth/login.ts").textContent).toContain("modified");
    expect(screen.getByTestId("status-badge-src/components/Header.tsx").textContent).toContain("added");
    expect(screen.getByTestId("status-badge-src/deprecated/oldUtil.ts").textContent).toContain("deleted");

    // Check top bar summary statistics
    const stats = screen.getByTestId("staging-summary-stats");
    expect(stats.textContent).toContain("3 files changed");
    expect(stats.textContent).toContain("37 insertions(+)");
    expect(stats.textContent).toContain("21 deletions(-)");
  });

  it("test_diff_viewer_shows_monaco_diff", async () => {
    render(<StagingReviewPanel />);

    // Diff viewer container present
    expect(screen.getByTestId("diff-viewer")).toBeTruthy();
    expect(screen.getByTestId("monaco-diff-viewer")).toBeTruthy();

    // Line 1: Context line
    const contextLine = screen.getByTestId("diff-line-context-1");
    expect(contextLine).toBeTruthy();
    expect(contextLine.textContent).toContain("import { auth } from './core';");

    // Line 2: Deletion (red line)
    const deleteLine = screen.getByTestId("diff-line-delete-2");
    expect(deleteLine).toBeTruthy();
    expect(deleteLine.textContent).toContain("-");
    expect(deleteLine.textContent).toContain("const oldToken = getLegacy();");

    // Line 3: Insertion (green line)
    const insertLine = screen.getByTestId("diff-line-insert-3");
    expect(insertLine).toBeTruthy();
    expect(insertLine.textContent).toContain("+");
    expect(insertLine.textContent).toContain("const newToken = await getSecureToken();");
  });

  it("test_checkbox_approves_file", async () => {
    (api.post as any).mockResolvedValueOnce({
      success: true,
      approved_files: ["src/auth/login.ts"],
    });

    render(<StagingReviewPanel />);

    // Click "Approve (1)" bulk button for selected file
    const approveBtn = screen.getByTestId("approve-selected-btn");
    expect(approveBtn).toBeTruthy();
    fireEvent.click(approveBtn);

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith("/api/staging/approve-files", {
        job_id: "job_pr_123",
        file_paths: ["src/auth/login.ts"],
      });
    });

    // Check that state updated to approved
    await waitFor(() => {
      expect(screen.getByTestId("file-approved-badge-src/auth/login.ts")).toBeTruthy();
      expect(screen.getByTestId("staging-progress-stats").textContent).toContain("1 approved");
    });
  });

  it("test_chunk_approve_reject_buttons_work", async () => {
    (api.post as any).mockResolvedValue({ success: true });

    render(<StagingReviewPanel />);

    // Find chunk 1 approve button and click it
    const approveChunk1 = screen.getByTestId("approve-chunk-1");
    expect(approveChunk1).toBeTruthy();
    fireEvent.click(approveChunk1);

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith("/api/staging/approve-chunk", {
        job_id: "job_pr_123",
        file_path: "src/auth/login.ts",
        chunk_index: 1,
      });
    });

    // Find chunk 2 reject button and click it
    const rejectChunk2 = screen.getByTestId("reject-chunk-2");
    expect(rejectChunk2).toBeTruthy();
    fireEvent.click(rejectChunk2);

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith("/api/staging/reject-chunk", {
        job_id: "job_pr_123",
        file_path: "src/auth/login.ts",
        chunk_index: 2,
      });
    });
  });

  it("test_apply_button_writes_approved_to_disk", async () => {
    (api.post as any).mockResolvedValueOnce({
      success: true,
      applied_files: ["src/auth/login.ts"],
      rejected_files: ["src/deprecated/oldUtil.ts"],
    });

    // Mark 1 file approved so Apply button is active
    useStagingStore.setState((state) => ({
      files: state.files.map((f, i) => (i === 0 ? { ...f, approved: true } : f)),
    }));

    const dispatchSpy = vi.spyOn(window, "dispatchEvent");
    render(<StagingReviewPanel />);

    const applyBtn = screen.getByTestId("apply-approved-btn") as HTMLButtonElement;
    expect(applyBtn.disabled).toBe(false);
    expect(applyBtn.textContent).toContain("Apply All Approved (1/3)");

    fireEvent.click(applyBtn);

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith("/api/staging/apply", {
        job_id: "job_pr_123",
      });
    });

    await waitFor(() => {
      expect(dispatchSpy).toHaveBeenCalledWith(
        expect.objectContaining({
          type: "code-os:staging-applied",
        })
      );
      expect(useStagingStore.getState().isOpen).toBe(false);
    });
  });
});
