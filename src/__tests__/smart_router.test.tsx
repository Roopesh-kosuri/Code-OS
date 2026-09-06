import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { AgentRoster } from "../features/ai/console/AgentRoster";
import { DAGBoard } from "../features/ai/console/DAGBoard";
import { useTeamStore, TeamTask } from "../features/ai/console/teamStore";
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

describe("Smart Model Router Frontend Tests", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useTeamStore.setState({
      smartRouterEnabled: false,
      taskDifficultyMap: {},
      customRoles: [],
      tasks: [],
      jobStatus: "idle",
      isVerifying: false,
      agentMetrics: {
        architect: { total_tokens: 0, input_tokens: 0, output_tokens: 0, total_cost: 0, message_count: 0 },
        coder: { total_tokens: 0, input_tokens: 0, output_tokens: 0, total_cost: 0, message_count: 0 },
        reviewer: { total_tokens: 0, input_tokens: 0, output_tokens: 0, total_cost: 0, message_count: 0 },
        tester: { total_tokens: 0, input_tokens: 0, output_tokens: 0, total_cost: 0, message_count: 0 },
        devops: { total_tokens: 0, input_tokens: 0, output_tokens: 0, total_cost: 0, message_count: 0 },
      },
    });
  });

  // ── Test 1: Toggle renders and toggles smart router ─────────────────────────
  it("test_smart_router_toggle_renders: renders toggle with tooltip and toggles state", () => {
    render(<AgentRoster />);

    const toggle = screen.getByTestId("smart-model-router-toggle");
    expect(toggle).toBeDefined();
    expect(toggle.getAttribute("title")).toBe("Automatically routes tasks to optimal models");
    expect(toggle.textContent).toContain("OFF");

    // Click toggle
    fireEvent.click(toggle);

    expect(useTeamStore.getState().smartRouterEnabled).toBe(true);
    expect(toggle.textContent).toContain("ON");
  });

  // ── Test 2: Difficulty badge renders on DAG task node ──────────────────────
  it("test_difficulty_badge_renders_on_task_node: displays difficulty badge and model in DAGBoard", () => {
    const mockTasks: TeamTask[] = [
      {
        id: "task-crypto-1",
        title: "Implement cryptographic HMAC verification and token auth",
        assigned_agent: "coder",
        status: "running",
        dependencies: [],
        started_at: 100,
      },
    ];

    useTeamStore.setState({
      tasks: mockTasks,
      taskDifficultyMap: {
        "task-crypto-1": {
          difficulty: "HARD",
          confidence: 0.95,
          assigned_model: "glm-5.2",
          tier: "HARD",
        },
      },
    });

    render(<DAGBoard />);

    const badge = screen.getByTestId("task-difficulty-badge-task-crypto-1");
    expect(badge).toBeDefined();
    expect(badge.textContent).toContain("HARD");

    const assignedModelEl = screen.getByTestId("task-assigned-model-task-crypto-1");
    expect(assignedModelEl).toBeDefined();
    expect(assignedModelEl.textContent).toContain("glm-5.2");
  });

  // ── Test 3: Assigned model shows in roster card ─────────────────────────────
  it("test_assigned_model_shows_in_roster_card: displays model tier indicator on agent cards when enabled", () => {
    useTeamStore.setState({
      smartRouterEnabled: true,
      taskDifficultyMap: {},
    });

    render(<AgentRoster />);

    // Check architect card has GLM 5.2 (HARD)
    const architectTier = screen.getByTestId("smart-router-tier-architect");
    expect(architectTier).toBeDefined();
    expect(architectTier.textContent).toContain("GLM 5.2 (HARD)");

    // Check tester card has Groq (EASY)
    const testerTier = screen.getByTestId("smart-router-tier-tester");
    expect(testerTier).toBeDefined();
    expect(testerTier.textContent).toContain("Groq (EASY)");
  });

  // ── Test 4: Smart Router Settings Modal Opens ──────────────────────────────
  it("test_smart_router_settings_modal_opens: opens settings panel when Tiers button is clicked", async () => {
    (api.get as any).mockResolvedValueOnce({
      tiers: {
        HARD: { name: "Tier 1", model: "glm-5.2", provider: "zai" },
        MEDIUM: { name: "Tier 2", model: "claude-sonnet-4", provider: "anthropic" },
        EASY: { name: "Tier 3", model: "llama-3.1-8b-instant", provider: "groq" },
      },
      task_counts: { HARD: 5, MEDIUM: 10, EASY: 25 },
      cost_savings: { estimated_dollars: 12.45, pct_reduction: 68 },
    });

    render(<AgentRoster />);

    const settingsBtn = screen.getByTestId("smart-router-settings-btn");
    expect(settingsBtn).toBeDefined();

    fireEvent.click(settingsBtn);

    // Modal title should appear
    await waitFor(() => {
      expect(screen.getByText("Smart Model Router Configuration")).toBeDefined();
    });

    // Check test classification input is present
    const testInput = screen.getByTestId("test-classifier-input");
    expect(testInput).toBeDefined();

    // Check tier labels are visible
    expect(screen.getByText("Tier 1 — HARD Tasks")).toBeDefined();
    expect(screen.getByText("Tier 2 — MEDIUM Tasks")).toBeDefined();
    expect(screen.getByText("Tier 3 — EASY Tasks")).toBeDefined();
  });
});
