import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { AgentRoster } from "../features/ai/console/AgentRoster";
import { useTeamStore, CustomAgentRole } from "../features/ai/console/teamStore";
import { DockedApprovalCard } from "../features/ai/DockedApprovalCard";
import { api } from "../lib/api";

// Mock API
vi.mock("../lib/api", () => ({
  api: {
    get: vi.fn(),
    post: vi.fn(),
    delete: vi.fn(),
  },
}));

describe("Phase B7 — Custom Agent Roles Frontend", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useTeamStore.setState({
      customRoles: [],
      agentMetrics: {
        architect: { total_tokens: 0, input_tokens: 0, output_tokens: 0, total_cost: 0, message_count: 0 },
        coder: { total_tokens: 0, input_tokens: 0, output_tokens: 0, total_cost: 0, message_count: 0 },
        reviewer: { total_tokens: 0, input_tokens: 0, output_tokens: 0, total_cost: 0, message_count: 0 },
        tester: { total_tokens: 0, input_tokens: 0, output_tokens: 0, total_cost: 0, message_count: 0 },
        devops: { total_tokens: 0, input_tokens: 0, output_tokens: 0, total_cost: 0, message_count: 0 },
      },
      tasks: [],
      jobStatus: "idle",
      isVerifying: false,
    });
  });

  // ── Test 1: Add Agent Modal Provisions Real Custom Role ───────────────────
  it("test_add_agent_modal_creates_role: opens modal, verifies safety bounds, and creates custom role", async () => {
    const mockCreatedRole: CustomAgentRole = {
      id: "crole_12345",
      workspace: ".",
      name: "Security Auditor",
      handle: "auditor",
      description: "Scans code for CVEs and vulnerabilities",
      color: "#f43f5e",
      icon: "shield",
      allowed_tools: ["read_file", "search_code"],
      provider: "anthropic",
      model: "claude-3-5-sonnet-latest",
    };

    (api.post as any).mockResolvedValueOnce({
      role: mockCreatedRole,
      success: true,
    });

    render(<AgentRoster />);

    // Click "Add Agent"
    const addBtn = screen.getByText(/Add Agent/i);
    fireEvent.click(addBtn);

    // Verify modal title & safety banner
    expect(screen.getByText("Provision Custom Agent")).toBeDefined();
    expect(screen.getByText("Strict Safety Bounds Enforced")).toBeDefined();

    // Fill form inputs
    const nameInput = screen.getByTestId("custom-role-name-input");
    const handleInput = screen.getByTestId("custom-role-handle-input");
    const descInput = screen.getByTestId("custom-role-desc-input");

    fireEvent.change(nameInput, { target: { value: "Security Auditor" } });
    fireEvent.change(handleInput, { target: { value: "auditor" } });
    fireEvent.change(descInput, { target: { value: "Scans code for CVEs and vulnerabilities" } });

    // Pick shield icon
    const shieldIconBtn = screen.getByTestId("icon-pick-shield");
    fireEvent.click(shieldIconBtn);

    // Pick rose color
    const roseColorBtn = screen.getByTestId("color-pick-#f43f5e");
    fireEvent.click(roseColorBtn);

    // Submit form
    const createBtn = screen.getByTestId("create-custom-role-btn");
    fireEvent.click(createBtn);

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith(
        "/api/team/roles",
        expect.objectContaining({
          name: "Security Auditor",
          handle: "auditor",
          icon: "shield",
          color: "#f43f5e",
        })
      );
    });

    // Custom role is stored in store
    const storeRoles = useTeamStore.getState().customRoles;
    expect(storeRoles.length).toBe(1);
    expect(storeRoles[0].handle).toBe("auditor");
  });

  // ── Test 2: Custom Role Card Renders & Can Be Deleted ─────────────────────
  it("test_custom_card_renders_and_removes: renders custom agent card with CUSTOM badge and delete action", async () => {
    const existingCustomRole: CustomAgentRole = {
      id: "crole_999",
      workspace: ".",
      name: "Performance Profiler",
      handle: "profiler",
      description: "Monitors memory and latency bottlenecks",
      color: "#06b6d4",
      icon: "cpu",
      allowed_tools: ["read_file", "search_code"],
      provider: "groq",
      model: "llama-3.3-70b-versatile",
    };

    useTeamStore.setState({
      customRoles: [existingCustomRole],
    });

    (api.delete as any).mockResolvedValueOnce({ success: true });

    render(<AgentRoster />);

    // Custom role card is rendered
    expect(screen.getByTestId("agent-card-profiler")).toBeDefined();
    expect(screen.getByText("Performance Profiler")).toBeDefined();
    expect(screen.getByText("@profiler")).toBeDefined();
    expect(screen.getByText("CUSTOM")).toBeDefined();

    // Click delete button
    const deleteBtn = screen.getByTestId("delete-role-profiler");
    fireEvent.click(deleteBtn);

    await waitFor(() => {
      expect(api.delete).toHaveBeenCalledWith(
        "/api/team/roles/crole_999",
        expect.anything()
      );
    });

    // Role removed from store
    expect(useTeamStore.getState().customRoles.length).toBe(0);
  });

  // ── Test 3: Approval Tagging Displays Custom Role Name ─────────────────────
  it("test_approval_shows_custom_role_name: renders custom role display name on approval badge (Refinement R3)", () => {
    const mockPendingApproval = {
      action_id: "appr_test_123",
      action_type: "command",
      agent_role: "CodeReviewer",
      command: "pytest tests/test_perf.py",
      detail: "pytest tests/test_perf.py",
      reason: "Running automated security test suite",
      status: "pending",
      metadata: {
        agent_role: "CodeReviewer",
        handle: "auditor",
      },
    };

    render(
      <DockedApprovalCard
        pendingApproval={mockPendingApproval}
        pendingApprovals={[mockPendingApproval]}
        onApprove={vi.fn()}
        onReject={vi.fn()}
      />
    );

    // Badge renders custom role display name
    expect(screen.getByText("CodeReviewer")).toBeDefined();
    expect(screen.getByTestId("approval-role-badge-auditor")).toBeDefined();
  });
});
