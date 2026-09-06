import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { TopBar } from "../components/layout/TopBar";
import { SessionReplayPanel } from "../features/ai/session/SessionReplayPanel";
import { useSessionStore } from "../features/ai/session/sessionStore";
import { useWorkspaceStore } from "../stores/workspaceStore";
import { api } from "../lib/api";

// Mock API
vi.mock("../lib/api", () => ({
  api: {
    get: vi.fn(),
    put: vi.fn(),
    post: vi.fn(),
    delete: vi.fn(),
  },
}));

// Mock recharts for headless JSDOM stability
vi.mock("recharts", () => ({
  ResponsiveContainer: ({ children }: any) => <div data-testid="responsive-container">{children}</div>,
  BarChart: ({ children }: any) => <div data-testid="bar-chart">{children}</div>,
  Bar: () => <div data-testid="bar" />,
  XAxis: () => <div data-testid="x-axis" />,
  YAxis: () => <div data-testid="y-axis" />,
  Tooltip: () => <div data-testid="tooltip" />,
  CartesianGrid: () => <div data-testid="cartesian-grid" />,
  PieChart: ({ children }: any) => <div data-testid="pie-chart">{children}</div>,
  Pie: ({ children }: any) => <div data-testid="pie">{children}</div>,
  Cell: () => <div data-testid="cell" />,
  Legend: () => <div data-testid="legend" />,
}));

describe("Session Replay & Time Travel Frontend Suite", () => {
  const mockSessions = [
    {
      job_id: "job_test_123",
      workspace: "/mock/workspace",
      title: "Build Authentication System",
      created_at: "2026-09-06T10:00:00Z",
      completed_at: "2026-09-06T10:05:00Z",
      duration: 300,
      status: "completed",
      cost_usd: 0.0452,
      step_count: 2,
      token_usage: 12500,
    },
    {
      job_id: "job_test_456",
      workspace: "/mock/workspace",
      title: "Refactor Database Schema",
      created_at: "2026-09-06T11:00:00Z",
      completed_at: "2026-09-06T11:02:00Z",
      duration: 120,
      status: "completed",
      cost_usd: 0.0185,
      step_count: 1,
      token_usage: 4200,
    },
  ];

  const mockTimeline = [
    {
      step_id: "step_1",
      task_id: "task_1",
      step_num: 1,
      timestamp: 1788640000,
      agent_role: "architect",
      action_type: "plan",
      tool_name: "create_architecture_plan",
      status: "completed",
      input: { architecture: "JWT tokens with HTTP-only cookies" },
      output: { status: "spec approved" },
      file_changes: [{ path: "docs/auth.md", updated: "# Auth Spec\nJWT with cookies" }],
      thinking: "Architecting the authentication layer using secure HTTP cookies.",
      cost_usd: 0.012,
    },
    {
      step_id: "step_2",
      task_id: "task_2",
      step_num: 2,
      timestamp: 1788640050,
      agent_role: "coder",
      action_type: "file_edit",
      tool_name: "write_to_file",
      status: "completed",
      input: { filepath: "src/auth/jwt.py", content: "def verify_token(): pass" },
      output: { written: true },
      file_changes: [{ path: "src/auth/jwt.py", updated: "def verify_token(): return True" }],
      thinking: "Implementing token verification logic.",
      cost_usd: 0.024,
    },
  ];

  const mockSnapshot = {
    job_id: "job_test_123",
    step_id: "step_1",
    step_num: 1,
    agent_role: "architect",
    timestamp: 1788640000,
    status: "completed",
    messages: [{ role: "user", content: "Implement auth system" }],
    staged_changes: [{ path: "docs/auth.md", updated: "# Auth Spec" }],
    workspace_manifest: {
      "docs/auth.md": { purpose: "Auth Architecture Spec", agent_role: "architect" },
    },
    agent_state: {
      active_role: "architect",
      completed_steps: 1,
      total_steps: 2,
    },
  };

  beforeEach(() => {
    vi.clearAllMocks();

    (api.get as any).mockImplementation((url: string) => {
      if (url.includes("/api/sessions") && url.includes("/timeline")) {
        return Promise.resolve(mockTimeline);
      }
      if (url.includes("/api/sessions") && url.includes("/snapshot")) {
        return Promise.resolve(mockSnapshot);
      }
      if (url.startsWith("/api/sessions")) {
        return Promise.resolve(mockSessions);
      }
      if (url.includes("/api/cost/budget")) {
        return Promise.resolve({
          daily_limit_usd: 10.0,
          today_spend_usd: 0.05,
          usage_percent: 0.5,
          ok: true,
        });
      }
      return Promise.resolve([]);
    });

    (api.post as any).mockImplementation((url: string, body: any) => {
      if (url.includes("/fork")) {
        return Promise.resolve({
          job_id: "job_fork_999",
          status: "forked",
          original_job: "job_test_123",
          fork_step_id: body.step_id,
        });
      }
      return Promise.resolve({ ok: true });
    });

    useWorkspaceStore.setState({
      currentWorkspace: { path: "/mock/workspace", name: "MockWorkspace" },
      restrictedMode: false,
    });

    useSessionStore.setState({
      sessions: mockSessions,
      activeSessionId: "job_test_123",
      activeSession: mockSessions[0],
      timeline: mockTimeline,
      activeStepId: "step_1",
      activeSnapshot: mockSnapshot,
      isLoadingSessions: false,
      isLoadingTimeline: false,
      isLoadingSnapshot: false,
      isForkModalOpen: false,
      forkTargetStepId: null,
      isForking: false,
      error: null,
    });
  });

  it("test_sessions_tab_renders_list", async () => {
    // 1. TopBar does NOT render Sessions (moved to sidebar)
    const { unmount: unmountTopBar } = render(
      <TopBar onOpenSettings={vi.fn()} activeView="main" onViewChange={vi.fn()} />
    );
    expect(screen.queryByRole("button", { name: "Sessions" })).toBeNull();
    unmountTopBar();

    // 2. Render SessionReplayPanel in compact sidebar mode
    const onOpenFullView = vi.fn();
    const { container: compactContainer, unmount } = render(
      <SessionReplayPanel compact onOpenFullView={onOpenFullView} />
    );

    expect(compactContainer.querySelector("#session-replay-sidebar-panel")).toBeDefined();

    await waitFor(() => {
      expect(screen.getByText("Build Authentication System")).toBeDefined();
      expect(screen.getByText("Refactor Database Schema")).toBeDefined();
    });

    // Test expand to full view
    const expandBtn = compactContainer.querySelector("#btn-sidebar-expand-sessions") as HTMLButtonElement;
    expect(expandBtn).toBeDefined();
    fireEvent.click(expandBtn);
    expect(onOpenFullView).toHaveBeenCalled();

    unmount();

    // 3. Render SessionReplayPanel in full mode
    const { container: fullContainer } = render(<SessionReplayPanel />);
    expect(fullContainer.querySelector("#session-replay-panel")).toBeDefined();
    await waitFor(() => {
      expect(screen.getByText("Sessions (2)")).toBeDefined();
    });
  });

  it("test_click_session_opens_replay_panel", async () => {
    const { container } = render(<SessionReplayPanel />);

    // Open drawer
    const drawerBtn = container.querySelector("#btn-toggle-session-drawer") as HTMLButtonElement;
    fireEvent.click(drawerBtn);

    // Click second session: Refactor Database Schema
    const sessionCard = screen.getByText("Refactor Database Schema");
    fireEvent.click(sessionCard);

    await waitFor(() => {
      expect(api.get).toHaveBeenCalledWith("/api/sessions/job_test_456/timeline");
    });
  });

  it("test_timeline_scrubber_updates_step_view", async () => {
    const { container } = render(<SessionReplayPanel />);

    // Initial step 1 is active
    expect(screen.getByText("Architecting the authentication layer using secure HTTP cookies.")).toBeDefined();

    // Click step 2 in timeline scrubber
    const step2Entry = screen.getByText("write_to_file");
    expect(step2Entry).toBeDefined();
    fireEvent.click(step2Entry);

    await waitFor(() => {
      expect(useSessionStore.getState().activeStepId).toBe("step_2");
    });

    // Verify step 2 info is displayed
    expect(screen.getByText("Implementing token verification logic.")).toBeDefined();
  });

  it("test_fork_modal_opens_and_submits", async () => {
    const { container } = render(<SessionReplayPanel />);

    // Click "Fork from this step" button
    const forkBtn = container.querySelector("#btn-fork-from-step") as HTMLButtonElement;
    expect(forkBtn).toBeDefined();
    fireEvent.click(forkBtn);

    // Fork modal is now open
    expect(screen.getByText("Fork Session Timeline")).toBeDefined();
    const promptInput = container.querySelector("#fork-prompt-input") as HTMLTextAreaElement;
    expect(promptInput).toBeDefined();

    // Type new directive
    fireEvent.change(promptInput, {
      target: { value: "Switch to Argon2 hashing instead of bcrypt" },
    });

    // Click confirm fork button
    const confirmForkBtn = container.querySelector("#btn-confirm-fork") as HTMLButtonElement;
    fireEvent.click(confirmForkBtn);

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith(
        "/api/sessions/job_test_123/fork",
        expect.objectContaining({
          new_prompt: "Switch to Argon2 hashing instead of bcrypt",
        })
      );
    });
  });

  it("test_export_buttons_download_files", async () => {
    // Mock global fetch for export endpoint
    const originalFetch = global.fetch;
    const fetchMock = vi.fn().mockImplementation((url: string) => {
      return Promise.resolve({
        ok: true,
        text: () => Promise.resolve("# Session Transcript Export\nStep 1: Architect"),
      });
    });
    global.fetch = fetchMock;

    const { container } = render(<SessionReplayPanel />);

    // 1. Export Markdown
    const exportMdBtn = container.querySelector("#btn-export-markdown") as HTMLButtonElement;
    expect(exportMdBtn).toBeDefined();
    fireEvent.click(exportMdBtn);

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("/api/sessions/job_test_123/export?format=markdown")
      );
    });

    // 2. Export JSON
    const exportJsonBtn = container.querySelector("#btn-export-json") as HTMLButtonElement;
    expect(exportJsonBtn).toBeDefined();
    fireEvent.click(exportJsonBtn);

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("/api/sessions/job_test_123/export?format=json")
      );
    });

    global.fetch = originalFetch;
  });
});
