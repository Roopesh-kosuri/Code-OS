import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { TopBar } from "../components/layout/TopBar";
import { CostDashboardModal } from "../features/ai/cost/CostDashboardModal";
import { SettingsModal } from "../components/settings/SettingsModal";
import { useCostStore } from "../stores/costStore";
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

describe("Cost Dashboard & Budget Guard Frontend Suite", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    (api.get as any).mockImplementation((url: string) => {
      if (url.includes("/api/settings/api-keys")) return Promise.resolve([]);
      if (url.includes("/api/settings")) return Promise.resolve([]);
      if (url.includes("/api/cost/budget")) {
        return Promise.resolve({
          daily_limit_usd: 5.0,
          session_limit_usd: null,
          today_spend_usd: 0.47,
          usage_percent: 9.4,
          status: "none",
          ok: true,
          downgrade_model: "groq/llama-3.3-70b",
          auto_downgrade_at_percent: 90,
          hard_stop_at_percent: 100,
        });
      }
      if (url.includes("/api/cost/summary")) {
        return Promise.resolve({
          total_usd: 0.47,
          per_provider: { groq: 0.47 },
          per_model: { "llama-3.3-70b": 0.47 },
          per_job: [],
        });
      }
      if (url.includes("/api/cost/breakdown")) {
        return Promise.resolve([
          { date: "2026-09-06", usd: 0.47, job_count: 1, token_count: 15000 },
        ]);
      }
      return Promise.resolve([]);
    });

    useWorkspaceStore.setState({
      currentWorkspace: { path: "/mock/workspace", name: "MockWorkspace" },
      restrictedMode: false,
    });
    useCostStore.setState({
      budget: {
        daily_limit_usd: 5.0,
        session_limit_usd: null,
        auto_downgrade_at_percent: 90,
        hard_stop_at_percent: 100,
        downgrade_model: "groq/llama-3.3-70b",
        today_spend_usd: 0.47,
        usage_percent: 9.4,
        status: "none",
        ok: true,
      },
      summary: {
        total_usd: 0.47,
        per_provider: { groq: 0.47 },
        per_model: { "llama-3.3-70b": 0.47 },
        per_job: [],
      },
      dailyBreakdown: [
        { date: "2026-09-06", usd: 0.47, job_count: 1, token_count: 15000 },
      ],
      isModalOpen: false,
      activePeriod: "today",
      isLoading: false,
      error: null,
    });
  });

  // ── Test 1: Global Pill renders today spend ──────────────────────────────
  it("test_global_pill_renders_today_spend: displays formatted spend and limit in top bar", () => {
    (api.get as any).mockResolvedValue({
      daily_limit_usd: 5.0,
      today_spend_usd: 0.47,
      usage_percent: 9.4,
      status: "none",
      ok: true,
    });

    render(<TopBar onOpenSettings={vi.fn()} activeView="main" onViewChange={vi.fn()} />);

    const pill = screen.getByRole("button", { name: /Today: \$0\.47 \/ \$5\.00/i });
    expect(pill).toBeDefined();
    expect(pill.id).toBe("global-cost-pill");
    expect(pill.className).toContain("text-emerald-400");
  });

  // ── Test 2: Pill turns red over 90 percent ────────────────────────────────
  it("test_pill_turns_red_over_90_percent: shifts to rose/red styling above 90% threshold and pulses at 100%", () => {
    useCostStore.setState({
      budget: {
        daily_limit_usd: 5.0,
        session_limit_usd: null,
        auto_downgrade_at_percent: 90,
        hard_stop_at_percent: 100,
        downgrade_model: "groq/llama-3.3-70b",
        today_spend_usd: 4.65,
        usage_percent: 93.0,
        status: "downgrade",
        ok: true,
      },
    });

    const { unmount } = render(<TopBar onOpenSettings={vi.fn()} activeView="main" onViewChange={vi.fn()} />);
    let pill = screen.getByRole("button", { name: /Today: \$4\.65 \/ \$5\.00/i });
    expect(pill.className).toContain("text-rose-400");
    unmount();

    // 100% hard stop -> pulsing red
    useCostStore.setState({
      budget: {
        daily_limit_usd: 5.0,
        session_limit_usd: null,
        auto_downgrade_at_percent: 90,
        hard_stop_at_percent: 100,
        downgrade_model: "groq/llama-3.3-70b",
        today_spend_usd: 5.10,
        usage_percent: 102.0,
        status: "block",
        ok: false,
      },
    });

    render(<TopBar onOpenSettings={vi.fn()} activeView="main" onViewChange={vi.fn()} />);
    pill = screen.getByRole("button", { name: /Today: \$5\.10 \/ \$5\.00/i });
    expect(pill.className).toContain("animate-pulse");
    expect(pill.className).toContain("border-rose-500");
  });

  // ── Test 3: Modal opens with charts ───────────────────────────────────────
  it("test_modal_opens_with_charts: renders modal with KPI cards, period tabs, and charts", () => {
    useCostStore.setState({
      summary: {
        total_usd: 12.84,
        per_provider: { openai: 8.50, groq: 4.34 },
        per_model: { "gpt-5": 8.50, "llama-3.3-70b": 4.34 },
        per_job: [
          {
            job_id: "job-123",
            workspace: "/mock/workspace",
            provider: "openai",
            model: "gpt-5",
            cost_usd: 8.50,
            token_count: 65000,
            timestamp: Date.now() / 1000,
          },
        ],
      },
      dailyBreakdown: [
        { date: "2026-09-05", usd: 4.34, job_count: 1, token_count: 20000 },
        { date: "2026-09-06", usd: 8.50, job_count: 1, token_count: 45000 },
      ],
    });

    render(<CostDashboardModal isOpen={true} onClose={vi.fn()} />);

    expect(screen.getByText(/Cost Dashboard & Spend Intelligence/i)).toBeDefined();
    expect(screen.getByText(/Daily Spend Over Time/i)).toBeDefined();
    expect(screen.getByText(/Spend by Provider/i)).toBeDefined();
    expect(screen.getByTestId("bar-chart")).toBeDefined();
    expect(screen.getByTestId("pie-chart")).toBeDefined();
    expect(screen.getByText(/Export CSV/i)).toBeDefined();
  });

  // ── Test 4: Settings save budget limits ────────────────────────────────────
  it("test_settings_save_budget_limits: saves updated budget caps via PUT /api/cost/budget", async () => {
    (api.put as any).mockResolvedValue({
      daily_limit_usd: 10.0,
      session_limit_usd: 2.0,
      auto_downgrade_at_percent: 90,
      hard_stop_at_percent: 100,
      downgrade_model: "groq/llama-3.3-70b",
      today_spend_usd: 0.47,
      usage_percent: 4.7,
      status: "none",
      ok: true,
    });

    render(<SettingsModal onClose={vi.fn()} />);

    // Click "Budget & Costs" nav category
    const budgetTab = screen.getByRole("button", { name: /Budget & Costs/i });
    fireEvent.click(budgetTab);

    expect(screen.getByText(/Budget Guard & Spending Caps/i)).toBeDefined();
    expect(screen.getByText(/Show Spend in Top Bar/i)).toBeDefined();
    expect(screen.getByText(/Daily Spending Limit/i)).toBeDefined();

    // Toggle daily limit switch (card 1)
    const checkboxes = screen.getAllByRole("checkbox");
    const dailyToggle = checkboxes[1];
    fireEvent.click(dailyToggle);

    await waitFor(() => {
      expect(api.put).toHaveBeenCalledWith("/api/cost/budget", expect.objectContaining({
        daily_limit_usd: expect.any(Number),
      }));
    });
  });

  // ── Test 5: Pill hides when toggled off in settings ─────────────────────────
  it("test_pill_hides_when_toggled_off_in_settings: toggling off hides pill from top bar immediately", async () => {
    (api.put as any).mockResolvedValue({
      daily_limit_usd: 5.0,
      show_topbar_pill: false,
      today_spend_usd: 0.47,
      usage_percent: 9.4,
      status: "none",
      ok: true,
    });

    // 1. Initially on -> TopBar renders pill
    useCostStore.setState({ showTopBarPill: true });
    const { unmount } = render(<TopBar onOpenSettings={vi.fn()} activeView="main" onViewChange={vi.fn()} />);
    expect(screen.getByRole("button", { name: /Today: \$0\.47 \/ \$5\.00/i })).toBeDefined();
    unmount();

    // 2. Open settings and toggle off "Show Spend in Top Bar"
    const { container } = render(<SettingsModal onClose={vi.fn()} />);
    const budgetTab = screen.getByRole("button", { name: /Budget & Costs/i });
    fireEvent.click(budgetTab);

    const topbarToggle = container.querySelector("#toggle-topbar-cost-pill") as HTMLInputElement;
    expect(topbarToggle).toBeDefined();
    fireEvent.click(topbarToggle);

    await waitFor(() => {
      expect(api.put).toHaveBeenCalledWith("/api/cost/budget", expect.objectContaining({
        show_topbar_pill: false,
      }));
    });

    // 3. Now verify TopBar does NOT render the pill when showTopBarPill is false
    useCostStore.setState({ showTopBarPill: false });
    render(<TopBar onOpenSettings={vi.fn()} activeView="main" onViewChange={vi.fn()} />);
    expect(screen.queryByRole("button", { name: /Today:/i })).toBeNull();
    expect(screen.queryByTestId("global-cost-pill")).toBeNull();
  });
});
