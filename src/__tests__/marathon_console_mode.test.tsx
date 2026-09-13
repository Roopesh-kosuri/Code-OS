/**
 * Phase 8.1 — Marathon Mode Tab inside Agent Console tests
 * Requirements:
 * - test_marathon_tab_renders_in_agent_console (three tabs visible)
 * - test_marathon_tab_shows_dashboard_inline
 * - test_marathon_tab_badge_pulses_when_active
 * - test_sse_cleanup_on_tab_unmount (no duplicate subscriptions after switching Team Mode -> Marathon -> Team Mode -> Marathon)
 * - test_existing_modes_unchanged
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
import { AgentConsole } from "../features/ai/AgentConsole";
import { useMarathonStore } from "../features/marathon/marathonStore";
import { useWorkspaceStore } from "../stores/workspaceStore";
import { useBackendStore } from "../stores/backendStore";
import { api } from "../lib/api";
import type { MarathonStateResponse } from "../features/marathon/types";

// ── EventSource Mock ─────────────────────────────────────────────────────────

let eventSourceInstances: MockEventSource[] = [];

class MockEventSource {
  url: string;
  closed = false;
  addEventListener = vi.fn();
  removeEventListener = vi.fn();
  onerror: (() => void) | null = null;

  constructor(url: string) {
    this.url = url;
    eventSourceInstances.push(this);
  }

  close = vi.fn(() => {
    this.closed = true;
  });
}

vi.stubGlobal("EventSource", MockEventSource);

// ── Sample Marathon Data ─────────────────────────────────────────────────────

const MOCK_RUNNING_MARATHON: MarathonStateResponse = {
  marathon_id: "mrn_mode_test_1",
  goal: "Migrate database models and write tests",
  status: "running",
  tasks: [
    {
      id: "t1",
      title: "Design schemas",
      description: "Define base schemas",
      dependencies: [],
      complexity: "low",
      target_files: ["schemas.py"],
      target_modules: [],
      status: "completed",
      retry_count: 0,
      max_retries: 3,
      git_commit_hash: "def5678",
      error_log: [],
      started_at: 1000,
      completed_at: 1010,
      tokens_used: 1200,
      cost_usd: 0.01,
    },
    {
      id: "t2",
      title: "Implement migration",
      description: "Write migration script",
      dependencies: ["t1"],
      complexity: "medium",
      target_files: ["migrate.py"],
      target_modules: [],
      status: "in_progress",
      retry_count: 0,
      max_retries: 3,
      git_commit_hash: null,
      error_log: [],
      started_at: 1015,
      completed_at: null,
      tokens_used: 500,
      cost_usd: 0.005,
    },
  ],
  budget: {
    token_budget: 100000,
    time_budget_seconds: 3600,
    cost_budget_usd: 5.0,
  },
  usage: {
    tokens_used: 1700,
    elapsed_seconds: 45,
    cost_usd: 0.015,
  },
  progress_completed: 1,
  progress_total: 2,
  created_at: 990,
  updated_at: 1020,
  handoff_report: null,
};

describe("Phase 8.1 — Marathon Mode Tab inside Agent Console", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    eventSourceInstances = [];
    vi.spyOn(api, "get").mockResolvedValue([]);
    vi.spyOn(api, "post").mockResolvedValue({});

    useWorkspaceStore.setState({
      currentWorkspace: { path: "D:/test-workspace", name: "test-ws", is_current: true },
      trustedWorkspaces: { "D:/test-workspace": true },
    });
    useBackendStore.setState({ status: "connected" });

    // Reset marathon store
    useMarathonStore.setState({
      activeMarathon: null,
      marathonList: [],
      isLoading: false,
      error: null,
      showModal: false,
      liveLog: [],
      consoleMode: "standard",
      _sseSource: null,
    });
  });

  afterEach(() => {
    useMarathonStore.getState().disconnectSSE();
  });

  // ── Test 1: Mode switcher shows three tabs ─────────────────────────────────
  it("test_marathon_tab_renders_in_agent_console", () => {
    render(<AgentConsole />);

    expect(screen.getByTestId("mode-toggle-standard")).toBeDefined();
    expect(screen.getByTestId("mode-toggle-team")).toBeDefined();
    expect(screen.getByTestId("mode-toggle-marathon")).toBeDefined();

    expect(screen.getByText("Standard Workflow")).toBeDefined();
    expect(screen.getByText("Team Mode")).toBeDefined();
    expect(screen.getByText("Marathon")).toBeDefined();
  });

  // ── Test 2: Selecting Marathon renders dashboard inline ───────────────────
  it("test_marathon_tab_shows_dashboard_inline", async () => {
    await act(async () => {
      useMarathonStore.setState({ activeMarathon: MOCK_RUNNING_MARATHON });
    });

    await act(async () => {
      render(<AgentConsole />);
    });

    // Initially standard workflow is visible
    expect(screen.getByText("Agent Instruction")).toBeDefined();
    expect(screen.queryByTestId("marathon-dashboard")).toBeNull();

    // Click Marathon tab
    await act(async () => {
      fireEvent.click(screen.getByTestId("mode-toggle-marathon"));
    });

    // Marathon dashboard is rendered inline
    expect(screen.getByTestId("marathon-dashboard")).toBeDefined();
    expect(screen.getByTestId("marathon-console-view")).toBeDefined();
    expect(screen.getByText("Migrate database models and write tests")).toBeDefined();
    expect(screen.getByTestId("marathon-progress-bar")).toBeDefined();
    expect(screen.getByTestId("task-card-t1")).toBeDefined();
    expect(screen.getByTestId("task-card-t2")).toBeDefined();

    // Standard and Team console views are not rendered
    expect(screen.queryByText("Agent Instruction")).toBeNull();
    expect(screen.queryByTestId("team-console")).toBeNull();
  });

  // ── Test 3: Tab badge pulses when marathon is active or paused ─────────────
  it("test_marathon_tab_badge_pulses_when_active", async () => {
    // 1. Initially inactive -> no badge
    const { rerender } = render(<AgentConsole />);
    expect(screen.queryByTestId("marathon-tab-badge")).toBeNull();

    // 2. Active marathon running -> badge present with animate-pulse
    await act(async () => {
      useMarathonStore.setState({ activeMarathon: MOCK_RUNNING_MARATHON });
    });
    rerender(<AgentConsole />);

    const badgeRunning = screen.getByTestId("marathon-tab-badge");
    expect(badgeRunning).toBeDefined();
    expect(badgeRunning.className).toContain("animate-pulse");

    // 3. Marathon paused -> badge still present
    await act(async () => {
      useMarathonStore.setState({
        activeMarathon: { ...MOCK_RUNNING_MARATHON, status: "paused" },
      });
    });
    rerender(<AgentConsole />);

    const badgePaused = screen.getByTestId("marathon-tab-badge");
    expect(badgePaused).toBeDefined();
    expect(badgePaused.className).toContain("animate-pulse");

    // 4. Marathon completed -> badge removed
    await act(async () => {
      useMarathonStore.setState({
        activeMarathon: { ...MOCK_RUNNING_MARATHON, status: "completed" },
      });
    });
    rerender(<AgentConsole />);
    expect(screen.queryByTestId("marathon-tab-badge")).toBeNull();
  });

  // ── Test 4: SSE lifecycle clean on mount/unmount and tab switching ────────
  it("test_sse_cleanup_on_tab_unmount", async () => {
    useMarathonStore.setState({
      activeMarathon: MOCK_RUNNING_MARATHON,
      consoleMode: "team",
    });

    render(<AgentConsole />);

    // In Team Mode initially: no marathon SSE opened yet
    expect(eventSourceInstances.length).toBe(0);

    // Switch to Marathon mode -> mounts MarathonDashboard and connects SSE
    await act(async () => {
      fireEvent.click(screen.getByTestId("mode-toggle-marathon"));
    });

    expect(eventSourceInstances.length).toBe(1);
    expect(eventSourceInstances[0].closed).toBe(false);
    expect(eventSourceInstances[0].url).toContain(MOCK_RUNNING_MARATHON.marathon_id);

    // Switch back to Team Mode -> unmounts MarathonDashboard and closes SSE
    await act(async () => {
      fireEvent.click(screen.getByTestId("mode-toggle-team"));
    });

    expect(eventSourceInstances[0].close).toHaveBeenCalled();
    expect(eventSourceInstances[0].closed).toBe(true);

    // Switch to Marathon mode again -> opens clean new SSE without duplicating
    await act(async () => {
      fireEvent.click(screen.getByTestId("mode-toggle-marathon"));
    });

    expect(eventSourceInstances.length).toBe(2);
    // Previous instance was closed
    expect(eventSourceInstances[0].closed).toBe(true);
    // New instance is active
    expect(eventSourceInstances[1].closed).toBe(false);

    // Switch back to Team Mode -> cleanly disconnects again
    await act(async () => {
      fireEvent.click(screen.getByTestId("mode-toggle-team"));
    });

    expect(eventSourceInstances[1].close).toHaveBeenCalled();
    expect(eventSourceInstances[1].closed).toBe(true);
  });

  // ── Test 5: Existing modes behavior remains completely unchanged ──────────
  it("test_existing_modes_unchanged", async () => {
    render(<AgentConsole />);

    // Default view is Standard Workflow
    expect(screen.getByText("Agent Instruction")).toBeDefined();
    expect(screen.queryByTestId("team-console")).toBeNull();
    expect(screen.queryByTestId("marathon-dashboard")).toBeNull();

    // Switch to Team Mode
    await act(async () => {
      fireEvent.click(screen.getByTestId("mode-toggle-team"));
    });

    expect(screen.getByTestId("team-console")).toBeDefined();
    expect(screen.getByText("Agent Roster")).toBeDefined();
    expect(screen.queryByText("Agent Instruction")).toBeNull();
    expect(screen.queryByTestId("marathon-dashboard")).toBeNull();

    // Switch back to Standard Workflow
    await act(async () => {
      fireEvent.click(screen.getByTestId("mode-toggle-standard"));
    });

    expect(screen.getByText("Agent Instruction")).toBeDefined();
    expect(screen.queryByTestId("team-console")).toBeNull();
    expect(screen.queryByTestId("marathon-dashboard")).toBeNull();
  });
});
