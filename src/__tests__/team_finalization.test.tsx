import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, act, fireEvent } from "@testing-library/react";
import { useTeamStore } from "../features/ai/console/teamStore";
import { AgentRoster } from "../features/ai/console/AgentRoster";
import { TeamConsole } from "../features/ai/console/TeamConsole";
import { DockedApprovalCard } from "../features/ai/DockedApprovalCard";
import type { PendingApprovalState } from "../stores/aiStore";

// Mock workspaceStore to provide active workspace
vi.mock("../stores/workspaceStore", () => ({
  useWorkspaceStore: (selector: any) =>
    selector({
      currentWorkspace: { path: "/fake/workspace", name: "Test Workspace" },
    }),
}));

describe("Phase B6 — Final Polish: Approval Tagging + Cost Tracking + Report Persistence", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    act(() => {
      useTeamStore.getState().reset();
    });
  });

  afterEach(() => {
    act(() => {
      useTeamStore.getState().reset();
    });
  });

  // ── Test 1: Approval card shows agent badge with colored role ───────────────
  it("test_approval_card_shows_agent_badge: renders colored role badge on approval card", () => {
    const coderApproval: PendingApprovalState = {
      action_id: "appr_coder_1",
      action_type: "edit",
      detail: "backend/server.py",
      reason: "Coder agent needs to apply bugfix to server.py",
      path: "backend/server.py",
      agent_role: "coder",
      team_mode: true,
      metadata: { agent_role: "coder", team_mode: true },
    };

    const { rerender } = render(
      <DockedApprovalCard
        pendingApproval={coderApproval}
        onApprove={vi.fn()}
        onReject={vi.fn()}
      />
    );

    const coderBadge = screen.getByTestId("approval-role-badge-coder");
    expect(coderBadge).toBeTruthy();
    expect(coderBadge.textContent).toContain("Coder");
    expect(coderBadge.className).toContain("text-emerald-300");

    // Test DevOps role badge (red badge)
    const devopsApproval: PendingApprovalState = {
      action_id: "appr_devops_2",
      action_type: "command",
      detail: "npm run deploy",
      reason: "DevOps agent requires command execution",
      command: "npm run deploy",
      agent_role: "devops",
      team_mode: true,
      metadata: { agent_role: "devops", team_mode: true },
    };

    rerender(
      <DockedApprovalCard
        pendingApproval={devopsApproval}
        onApprove={vi.fn()}
        onReject={vi.fn()}
      />
    );

    const devopsBadge = screen.getByTestId("approval-role-badge-devops");
    expect(devopsBadge).toBeTruthy();
    expect(devopsBadge.textContent).toContain("DevOps");
    expect(devopsBadge.className).toContain("text-red-300");
  });

  // ── Test 2: Live cost breakdown per role renders in roster ──────────────────
  it("test_cost_breakdown_renders_in_roster: renders Input tokens, Output tokens, and Total cost per role", () => {
    act(() => {
      useTeamStore.setState({
        activeJobId: "job_b6_cost_test",
        jobStatus: "running",
        agentMetrics: {
          architect: { total_tokens: 25000, input_tokens: 20000, output_tokens: 5000, total_cost: 0.10, message_count: 2 },
          coder: { total_tokens: 60000, input_tokens: 50000, output_tokens: 10000, total_cost: 0.30, message_count: 5 },
          reviewer: { total_tokens: 15000, input_tokens: 12000, output_tokens: 3000, total_cost: 0.06, message_count: 2 },
          tester: { total_tokens: 18000, input_tokens: 15000, output_tokens: 3000, total_cost: 0.02, message_count: 3 },
          devops: { total_tokens: 5000, input_tokens: 4000, output_tokens: 1000, total_cost: 0.01, message_count: 1 },
        },
      });
    });

    render(<AgentRoster />);

    // Check Coder role cost breakdown container
    const coderCostBlock = screen.getByTestId("cost-breakdown-coder");
    expect(coderCostBlock).toBeTruthy();
    expect(coderCostBlock.textContent).toContain("Input tokens: 50,000");
    expect(coderCostBlock.textContent).toContain("Output tokens: 10,000");
    expect(coderCostBlock.textContent).toContain("Total: $0.30");

    // Check Architect role cost breakdown container
    const archCostBlock = screen.getByTestId("cost-breakdown-architect");
    expect(archCostBlock).toBeTruthy();
    expect(archCostBlock.textContent).toContain("Input tokens: 20,000");
    expect(archCostBlock.textContent).toContain("Output tokens: 5,000");
    expect(archCostBlock.textContent).toContain("Total: $0.10");
  });

  // ── Test 3: Export report button downloads report ───────────────────────────
  it("test_export_report_button_works: clicking Export Report triggers markdown export", async () => {
    act(() => {
      useTeamStore.setState({
        activeJobId: "job_export_42",
        jobStatus: "completed",
        finalReport: {
          files_changed: 4,
          tests_run: 12,
          tests_passed: 12,
          tests_failed: 0,
          review_notes: 0,
          repair_rounds: 1,
          total_cost: 0.075,
        },
      });
    });

    // Mock exportReportMarkdown spy
    const exportSpy = vi.fn().mockResolvedValue("# Verification Report — Job `job_export_42`");
    useTeamStore.setState({ exportReportMarkdown: exportSpy });

    // Mock URL.createObjectURL and click simulation
    const originalCreateObjectURL = window.URL.createObjectURL;
    const originalRevokeObjectURL = window.URL.revokeObjectURL;
    window.URL.createObjectURL = vi.fn().mockReturnValue("blob:http://localhost/test-uuid");
    window.URL.revokeObjectURL = vi.fn();

    render(<TeamConsole />);

    const exportBtn = screen.getByTestId("export-report-btn");
    expect(exportBtn).toBeTruthy();
    expect(exportBtn.textContent).toContain("Export Report");

    await act(async () => {
      fireEvent.click(exportBtn);
    });

    expect(exportSpy).toHaveBeenCalled();
    expect(window.URL.createObjectURL).toHaveBeenCalled();

    // Restore URL mocks
    window.URL.createObjectURL = originalCreateObjectURL;
    window.URL.revokeObjectURL = originalRevokeObjectURL;
  });
});
