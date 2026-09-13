/**
 * Phase 8 — Marathon Dashboard frontend tests
 * Tests: modal renders, dashboard shows progress, pause button sends stop signal
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
import React from "react";

// ── Mocks ─────────────────────────────────────────────────────────────────────

vi.mock("../stores/backendStore", () => ({
  useBackendStore: (selector: (s: { token: string; status: string }) => unknown) =>
    selector({ token: "test-token", status: "connected" }),
}));

vi.mock("../stores/workspaceStore", () => ({
  useWorkspaceStore: (selector: (s: { currentWorkspace: { path: string } | null }) => unknown) =>
    selector({ currentWorkspace: { path: "/test/workspace" } }),
}));

// Mock global fetch
const mockFetch = vi.fn();
global.fetch = mockFetch;

// Mock EventSource
class MockEventSource {
  addEventListener = vi.fn();
  close = vi.fn();
  onerror: (() => void) | null = null;
}
vi.stubGlobal("EventSource", MockEventSource);

// ── Test store state ──────────────────────────────────────────────────────────

import type { MarathonStateResponse } from "../features/marathon/types";

const MOCK_MARATHON: MarathonStateResponse = {
  marathon_id: "mrn_test1234",
  goal: "Create 5 dummy python files with hello world and a test for each",
  status: "running",
  tasks: [
    {
      id: "t1",
      title: "Create hello.py",
      description: "Create a hello world file",
      dependencies: [],
      complexity: "trivial",
      target_files: ["hello.py"],
      target_modules: [],
      status: "completed",
      retry_count: 0,
      max_retries: 3,
      git_commit_hash: "abc1234",
      error_log: [],
      started_at: Date.now() / 1000 - 10,
      completed_at: Date.now() / 1000 - 5,
      tokens_used: 1000,
      cost_usd: 0.01,
    },
    {
      id: "t2",
      title: "Create world.py",
      description: "Create second hello world file",
      dependencies: ["t1"],
      complexity: "trivial",
      target_files: ["world.py"],
      target_modules: [],
      status: "in_progress",
      retry_count: 0,
      max_retries: 3,
      git_commit_hash: null,
      error_log: [],
      started_at: Date.now() / 1000,
      completed_at: null,
      tokens_used: 500,
      cost_usd: 0.005,
    },
    {
      id: "t3",
      title: "Write tests",
      description: "Write pytest tests",
      dependencies: ["t2"],
      complexity: "low",
      target_files: ["test_hello.py"],
      target_modules: [],
      status: "todo",
      retry_count: 0,
      max_retries: 3,
      git_commit_hash: null,
      error_log: [],
      started_at: null,
      completed_at: null,
      tokens_used: 0,
      cost_usd: 0,
    },
  ],
  budget: { token_budget: 100_000, time_budget_seconds: 3600, cost_budget_usd: 5.0 },
  usage: { tokens_used: 5000, cost_usd: 0.05, elapsed_seconds: 120, started_at: Date.now() / 1000 - 120 },
  progress_completed: 1,
  progress_total: 3,
  handoff_report: null,
  clarifying_question: null,
  created_at: Date.now() / 1000,
  updated_at: Date.now() / 1000,
};

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("Marathon Modal", () => {
  it("test_start_marathon_modal_renders", async () => {
    const { MarathonModal } = await import("../features/marathon/MarathonModal");
    const { useMarathonStore } = await import("../features/marathon/marathonStore");

    // Set store to show modal
    useMarathonStore.setState({ showModal: true, isLoading: false, error: null });

    const { unmount } = render(<MarathonModal />);

    // Goal textarea
    const textarea = screen.getByPlaceholderText(/e\.g\./i);
    expect(textarea).toBeTruthy();
    expect(document.getElementById("marathon-goal-input")).toBeTruthy();

    // Budget sliders
    expect(document.getElementById("marathon-token-slider")).toBeTruthy();
    expect(document.getElementById("marathon-time-slider")).toBeTruthy();
    expect(document.getElementById("marathon-cost-slider")).toBeTruthy();

    // Start button exists and is disabled when no goal
    const startBtn = document.getElementById("marathon-start-btn") as HTMLButtonElement;
    expect(startBtn).toBeTruthy();
    expect(startBtn.disabled).toBe(true);

    // Type a goal — start button should become enabled
    fireEvent.change(textarea, { target: { value: "Build a FastAPI backend with auth" } });
    expect(startBtn.disabled).toBe(false);

    unmount();
  });
});

describe("Marathon Dashboard", () => {
  beforeEach(() => {
    mockFetch.mockClear();
  });

  it("test_live_dashboard_shows_progress", async () => {
    const { MarathonDashboard } = await import("../features/marathon/MarathonDashboard");
    const { useMarathonStore } = await import("../features/marathon/marathonStore");

    useMarathonStore.setState({
      activeMarathon: MOCK_MARATHON,
      showModal: false,
      liveLog: ["[16:00:00] task_started: Create hello.py"],
    });

    const { unmount } = render(<MarathonDashboard />);

    // Dashboard rendered
    expect(document.getElementById("marathon-dashboard")).toBeTruthy();

    // Progress bar
    const progressBar = screen.getByTestId("marathon-progress-bar");
    expect(progressBar).toBeTruthy();

    // Progress text "1/3"
    expect(screen.getByText(/1\/3 tasks/i)).toBeTruthy();

    // Kanban columns should exist — tasks in their correct columns
    // "Create hello.py" should be in Done column (completed)
    expect(screen.getByTestId("task-card-t1")).toBeTruthy();
    // "Create world.py" should be in In Progress
    expect(screen.getByTestId("task-card-t2")).toBeTruthy();
    // "Write tests" should be in To Do
    expect(screen.getByTestId("task-card-t3")).toBeTruthy();

    // Status badge shows RUNNING
    expect(screen.getByText("RUNNING")).toBeTruthy();

    // Live log rendered
    const log = screen.getByTestId("marathon-live-log");
    expect(log.textContent).toContain("task_started");

    unmount();
  });

  it("test_pause_button_sends_stop_signal", async () => {
    const { MarathonDashboard } = await import("../features/marathon/MarathonDashboard");
    const { useMarathonStore } = await import("../features/marathon/marathonStore");

    // Spy on the store's pauseMarathon action directly
    const pauseSpy = vi.fn().mockResolvedValue(undefined);
    useMarathonStore.setState({
      activeMarathon: MOCK_MARATHON,
      showModal: false,
      pauseMarathon: pauseSpy,
    });

    render(<MarathonDashboard />);

    const pauseBtn = document.getElementById("marathon-pause-btn");
    expect(pauseBtn).toBeTruthy();

    await act(async () => {
      fireEvent.click(pauseBtn!);
    });

    // pauseMarathon must have been called with the workspace path
    expect(pauseSpy).toHaveBeenCalledTimes(1);
    expect(pauseSpy).toHaveBeenCalledWith("/test/workspace");
  });
});
