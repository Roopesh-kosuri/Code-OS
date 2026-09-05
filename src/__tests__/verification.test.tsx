import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, act } from "@testing-library/react";
import { useTeamStore } from "../features/ai/console/teamStore";
import { AgentRoster } from "../features/ai/console/AgentRoster";
import { TeamChatPanel } from "../features/ai/console/TeamChatPanel";
import { TeamConsole } from "../features/ai/console/TeamConsole";

// Mock workspaceStore to provide active workspace
vi.mock("../stores/workspaceStore", () => ({
  useWorkspaceStore: (selector: any) =>
    selector({
      currentWorkspace: { path: "/fake/workspace", name: "Test Workspace" },
    }),
}));

describe("Phase B5 — Verification Gate + Repair Loop", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    act(() => {
      useTeamStore.getState().reset();
      useTeamStore.setState({ activeJobId: "job_b5_test", jobStatus: "running" });
    });
  });

  afterEach(() => {
    act(() => {
      useTeamStore.getState().reset();
    });
  });

  // ── Test 1: Verification badge shows during verify ──────────────────────────
  it("test_verification_badge_shows_during_verify: displays 'Verification in progress...' badge in AgentRoster", () => {
    // Initial state: not verifying
    const { rerender } = render(<AgentRoster />);
    expect(screen.queryByTestId("verification-badge")).toBeNull();

    // Trigger verification in progress
    act(() => {
      useTeamStore.getState().handleSSEEvent("team_status", {
        job_id: "job_b5_test",
        status: "verifying",
        round: 1,
      });
    });

    rerender(<AgentRoster />);
    const badge = screen.getByTestId("verification-badge");
    expect(badge).toBeTruthy();
    expect(badge.textContent).toContain("Verification in progress...");
  });

  // ── Test 2: Repair banner renders on team_repair event ───────────────────────
  it("test_repair_banner_renders: renders warning banner on team_repair event", () => {
    render(<TeamChatPanel />);
    expect(screen.queryByTestId("repair-banner")).toBeNull();

    // Dispatch team_repair event
    act(() => {
      useTeamStore.getState().handleSSEEvent("team_repair", {
        job_id: "job_b5_test",
        round: 2,
        max_rounds: 3,
        failures: ["test_auth_timeout", "test_sql_injection", "test_stubs"],
        reason: "3 test failures detected",
      });
    });

    const banner = screen.getByTestId("repair-banner");
    expect(banner).toBeTruthy();
    expect(banner.textContent).toContain("Repair Round 2/3: Coder fixing 3 test failures");
  });

  // ── Test 3: Final report card renders on completion ─────────────────────────
  it("test_final_report_card_renders: displays files, tests, review notes, repair rounds, and total cost", () => {
    // Dispatch completion with final report card
    act(() => {
      useTeamStore.getState().handleSSEEvent("team_status", {
        job_id: "job_b5_test",
        status: "completed",
        final_report: {
          files_changed: 5,
          tests_run: 24,
          tests_passed: 24,
          tests_failed: 0,
          review_notes: 0,
          repair_rounds: 2,
          total_cost: 0.15,
        },
      });
    });

    render(<TeamConsole />);

    const reportCard = screen.getByTestId("final-report-card");
    expect(reportCard).toBeTruthy();
    expect(reportCard.textContent).toContain("Job Verification Passed — Final Report");
    expect(reportCard.textContent).toContain("Files Changed");
    expect(reportCard.textContent).toContain("5");
    expect(reportCard.textContent).toContain("Tests Run");
    expect(reportCard.textContent).toContain("24");
    expect(reportCard.textContent).toContain("passed: 24, failed: 0");
    expect(reportCard.textContent).toContain("Review Notes");
    expect(reportCard.textContent).toContain("0 blockers found");
    expect(reportCard.textContent).toContain("Repair Rounds");
    expect(reportCard.textContent).toContain("2");
    expect(reportCard.textContent).toContain("Total Cost");
    expect(reportCard.textContent).toContain("$0.15");
  });
});
