import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { InlineConsoleApprovalCard } from "../features/ai/InlineConsoleApprovalCard";
import { sanitizeDisplayText } from "../lib/sanitizer";
import { useAIStore, type PendingApprovalState } from "../stores/aiStore";

// Mock Monaco Editor
vi.mock("@monaco-editor/react", () => ({
  DiffEditor: ({ original, modified }: { original: string; modified: string }) => (
    <div data-testid="mock-monaco-diff">
      <div data-testid="monaco-original">{original}</div>
      <div data-testid="monaco-modified">{modified}</div>
    </div>
  ),
}));

describe("Phase 10.19: Inline Console Approval Card & Sanitization", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    useAIStore.setState({
      pendingApproval: null,
      pendingApprovals: [],
    });
  });

  it("renders inline approval card with role badge, path, and Monaco diff", async () => {
    const handleApprove = vi.fn();
    const handleReject = vi.fn();

    const sampleApproval: PendingApprovalState = {
      action_id: "act-401",
      action_type: "edit",
      path: "backend/main.py",
      agent_role: "coder",
      diff: "@@ -1 +1 @@\n-old code\n+new code",
      detail: "Edit backend/main.py",
    };

    render(
      <InlineConsoleApprovalCard
        pendingApproval={sampleApproval}
        onApprove={handleApprove}
        onReject={handleReject}
      />
    );

    expect(screen.getByTestId("inline-approval-card")).toBeDefined();
    expect(screen.getByText("Coder")).toBeDefined();
    expect(screen.getByText("backend/main.py")).toBeDefined();
    expect(screen.getByTestId("inline-diff-viewer")).toBeDefined();

    // Trigger approve
    const approveBtn = screen.getByTestId("inline-approval-approve-btn");
    fireEvent.click(approveBtn);
    expect(handleApprove).toHaveBeenCalledWith("act-401");

    await waitFor(() => {
      expect(approveBtn.textContent).toContain("Approve");
    });

    // Trigger reject
    const rejectBtn = screen.getByTestId("inline-approval-reject-btn");
    fireEvent.click(rejectBtn);
    expect(handleReject).toHaveBeenCalledWith("act-401");
  });

  it("gates approval when integrity warning is present until checkbox is confirmed", () => {
    const handleApprove = vi.fn();
    const handleReject = vi.fn();

    const warningApproval: PendingApprovalState = {
      action_id: "act-402",
      action_type: "edit",
      path: "calculator.py",
      agent_role: "coder",
      integrity_status: "syntax_error",
      integrity_warning: "Syntax error detected in proposed code",
      detail: "Edit calculator.py",
    };

    render(
      <InlineConsoleApprovalCard
        pendingApproval={warningApproval}
        onApprove={handleApprove}
        onReject={handleReject}
      />
    );

    expect(screen.getByTestId("inline-integrity-warning")).toBeDefined();
    const approveBtn = screen.getByTestId("inline-approval-approve-btn");
    expect(approveBtn.hasAttribute("disabled")).toBe(true);

    // Clicking disabled approve button does nothing
    fireEvent.click(approveBtn);
    expect(handleApprove).not.toHaveBeenCalled();

    // Check confirmation checkbox
    const checkbox = screen.getByRole("checkbox");
    fireEvent.click(checkbox);
    expect(approveBtn.hasAttribute("disabled")).toBe(false);

    // Now clicking approve proceeds
    fireEvent.click(approveBtn);
    expect(handleApprove).toHaveBeenCalledWith("act-402");
  });

  it("single-resolve guard: dispatching proposal-applied clears pendingApproval immediately", async () => {
    const approval1: PendingApprovalState = {
      action_id: "prop-sync-1",
      action_type: "edit",
      path: "app.ts",
      detail: "Edit app.ts",
    };

    useAIStore.setState({
      pendingApproval: approval1,
      pendingApprovals: [approval1],
    });

    expect(useAIStore.getState().pendingApproval?.action_id).toBe("prop-sync-1");

    // Simulate approval resolution from another surface (e.g. Proposals tab / DiffViewer)
    window.dispatchEvent(new CustomEvent("code-os:proposal-applied", { detail: "prop-sync-1" }));

    await waitFor(() => {
      expect(useAIStore.getState().pendingApproval).toBeNull();
      expect(useAIStore.getState().pendingApprovals).toEqual([]);
    });
  });

  it("universal marker sanitizer strips all control tokens, proposals, and tool call blocks", () => {
    const dirtyText = `
<|im_start|>assistant
Here is the plan.
[TOOL_CALL: run_command]
{"command": "pytest"}
[/TOOL_CALL]
[PROPOSAL: test.py]
<<<< ORIGINAL
x = 1
====
x = 2
>>>>
Finished successfully!
[DONE]
<|im_end|>
`;
    const clean = sanitizeDisplayText(dirtyText);
    expect(clean).not.toContain("[PROPOSAL:");
    expect(clean).not.toContain("<<<<");
    expect(clean).not.toContain("====");
    expect(clean).not.toContain(">>>>");
    expect(clean).not.toContain("[TOOL_CALL:");
    expect(clean).not.toContain("[/TOOL_CALL]");
    expect(clean).not.toContain("[DONE]");
    expect(clean).not.toContain("<|im_start|>");
    expect(clean).not.toContain("<|im_end|>");
    expect(clean).toContain("Here is the plan.");
    expect(clean).toContain("Finished successfully!");
  });
});
