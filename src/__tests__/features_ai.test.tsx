import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { AgentStatusIndicator } from "../features/ai/AgentStatusIndicator";
import { DockedApprovalCard } from "../features/ai/DockedApprovalCard";
import { DiffViewer } from "../features/ai/DiffViewer";
import { MemoryPanel } from "../features/settings/MemoryPanel";
import { CoderAgentPanel } from "../features/coder/CoderAgentPanel";
import { DualCoderPanel } from "../features/dual_coder/DualCoderPanel";
import { useWorkspaceStore } from "../stores/workspaceStore";
import { useBackendStore } from "../stores/backendStore";
import { api } from "../lib/api";

describe("Frontend AI Features & Panels", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    useWorkspaceStore.setState({
      currentWorkspace: { path: "D:/ws", name: "ws", is_current: true },
    });
    useBackendStore.setState({ status: "connected" });
  });

  describe("<AgentStatusIndicator />", () => {
    it("renders thinking, tool, and done states", () => {
      const { rerender } = render(
        <AgentStatusIndicator
          status={{
            type: "thinking",
            message: "Decomposing task into DAG steps...",
            step: 1,
            total: 3,
          }}
        />
      );

      expect(screen.getByText(/Decomposing task into DAG steps/i)).toBeDefined();

      rerender(
        <AgentStatusIndicator
          status={{
            type: "tool",
            message: "Running test suite...",
            tool: "run_command",
            command: "pytest tests/",
          }}
        />
      );
      expect(screen.getByText(/Running test suite/i)).toBeDefined();
    });
  });

  describe("<DockedApprovalCard />", () => {
    it("renders pending approval card and triggers approve and reject callbacks", () => {
      const handleApprove = vi.fn();
      const handleReject = vi.fn();

      render(
        <DockedApprovalCard
          pendingApproval={{
            action_id: "act_101",
            action_type: "command",
            command: "npm run build",
            reason: "Compile TypeScript before running tests",
          }}
          onApprove={handleApprove}
          onReject={handleReject}
        />
      );

      expect(screen.getAllByText(/npm run build/i).length).toBeGreaterThanOrEqual(1);

      const approveBtn = screen.getByRole("button", { name: /Approve/i });
      fireEvent.click(approveBtn);
      expect(handleApprove).toHaveBeenCalled();

      const rejectBtn = screen.getByRole("button", { name: /Deny/i });
      fireEvent.click(rejectBtn);
      expect(handleReject).toHaveBeenCalledWith("act_101");
    });
  });

  describe("<DiffViewer />", () => {
    it("fetches and renders pending edit proposals or empty state", async () => {
      vi.spyOn(api, "get").mockResolvedValue([]);

      render(<DiffViewer />);

      await waitFor(() => {
        expect(screen.getByText(/No pending proposals/i)).toBeDefined();
      });
    });
  });

  describe("<MemoryPanel />", () => {
    it("renders memory panel with persistent workspace rules", async () => {
      vi.spyOn(api, "get").mockResolvedValue({
        styleGuide: "Always use strict typing",
        preferences: "Prefer functional programming",
      });

      render(<MemoryPanel />);
      expect(screen.getByText(/Project AI Memory/i)).toBeDefined();
      expect(screen.getByText(/Coding Style Rules/i)).toBeDefined();
    });
  });

  describe("<CoderAgentPanel />", () => {
    it("renders coder agent panel with task input", () => {
      render(<CoderAgentPanel />);
      expect(screen.getAllByText(/Coder Agent/i).length).toBeGreaterThanOrEqual(1);
      expect(screen.getByText(/Single-model fast code generator/i)).toBeDefined();
    });
  });

  describe("<DualCoderPanel />", () => {
    it("renders dual coder dual model selection controls", () => {
      render(<DualCoderPanel />);
      expect(screen.getAllByText(/Dual Coder/i).length).toBeGreaterThanOrEqual(1);
    });
  });
});
