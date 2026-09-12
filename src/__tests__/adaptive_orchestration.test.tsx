import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";

import { AIChatPanel } from "../features/ai/AIChatPanel";
import { useAIStore } from "../stores/aiStore";
import { useWorkspaceStore } from "../stores/workspaceStore";
import { api } from "../lib/api";

// Mock Monaco Editor
vi.mock("@monaco-editor/react", () => ({
  default: ({ value }: any) => (
    <div data-testid="mock-monaco-editor">
      <pre>{value}</pre>
    </div>
  ),
  DiffEditor: ({ original, modified }: any) => (
    <div data-testid="mock-diff-editor">
      <div data-testid="diff-original">{original}</div>
      <div data-testid="diff-modified">{modified}</div>
    </div>
  ),
  loader: {
    config: vi.fn(),
    init: vi.fn(),
  },
}));

describe("Phase 7: Adaptive Orchestration Frontend Tests", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    localStorage.clear();
    useAIStore.setState({
      messages: [],
      streaming: false,
      escalationRecommended: false,
      escalationReasoning: "",
      escalationConfidence: 0.0,
      escalationInProgress: false,
      escalationJobId: null,
      escalationError: null,
    });
    useWorkspaceStore.setState({
      currentWorkspace: {
        path: "D:/test-workspace",
        name: "test-workspace",
        last_opened_at: new Date().toISOString(),
      },
    });
    vi.spyOn(api, "get").mockResolvedValue([]);
    vi.spyOn(api, "post").mockResolvedValue({});
  });

  it("test_escalation_card_appears: renders escalation card with 5-agent breakdown and action buttons", async () => {
    useAIStore.setState({
      messages: [
        {
          role: "user",
          content: "Refactor the authentication system across handler, validators, sessions, and rate_limiter",
        },
        {
          role: "assistant",
          content: "I have analyzed this task and it involves multi-file refactoring and security hardening.",
          escalation_recommended: true,
          escalation_reasoning: "multi-file refactor and security hardening across auth modules",
          escalation_confidence: 0.75,
        },
      ],
      escalationRecommended: true,
      escalationReasoning: "multi-file refactor and security hardening across auth modules",
    });

    await act(async () => {
      render(<AIChatPanel />);
    });

    // Verify Escalation Card is rendered
    const card = screen.getByTestId("escalation-card");
    expect(card).toBeTruthy();
    expect(card.textContent).toContain("Complex Task Detected");
    expect(card.textContent).toContain("multi-file refactor and security hardening across auth modules");

    // Verify 5-agent team breakdown
    expect(card.textContent).toContain("Planner: decompose into subtasks");
    expect(card.textContent).toContain("Coder: implement changes");
    expect(card.textContent).toContain("Tester: verify with tests");
    expect(card.textContent).toContain("Reviewer: code quality + security");
    expect(card.textContent).toContain("Documenter: update docs");

    // Verify buttons
    const escalateBtn = screen.getByTestId("escalate-btn");
    expect(escalateBtn).toBeTruthy();
    expect(escalateBtn.textContent).toContain("Escalate to Agent Console");

    const continueBtn = screen.getByTestId("continue-rony-btn");
    expect(continueBtn).toBeTruthy();
    expect(continueBtn.textContent).toContain("Continue with Rony");
  });

  it("test_escalate_button_posts_job: clicking Escalate posts to /api/team/jobs/from-rony and shows badge", async () => {
    const postSpy = vi.spyOn(api, "post").mockImplementation(async (url: string) => {
      if (url === "/api/team/jobs/from-rony") {
        return {
          job_id: "team_oauth_test123",
          ws_url: "/ws/team/jobs/team_oauth_test123",
          status: "queued",
          priority: "high",
        };
      }
      return {};
    });

    useAIStore.setState({
      messages: [
        {
          role: "user",
          content: "Refactor auth and sessions",
        },
        {
          role: "assistant",
          content: "Analyzing task...",
          escalation_recommended: true,
          escalation_reasoning: "multi-file refactor and security hardening",
          escalation_confidence: 0.75,
        },
      ],
      escalationRecommended: true,
      escalationReasoning: "multi-file refactor and security hardening",
    });

    await act(async () => {
      render(<AIChatPanel />);
    });

    const escalateBtn = screen.getByTestId("escalate-btn");
    await act(async () => {
      fireEvent.click(escalateBtn);
    });

    await waitFor(() => {
      expect(postSpy).toHaveBeenCalledWith(
        "/api/team/jobs/from-rony",
        expect.objectContaining({
          task: "Refactor auth and sessions",
          escalation_reason: "multi-file refactor and security hardening",
        })
      );
    });

    // Badge should now appear
    await waitFor(() => {
      const badge = screen.getByTestId("escalated-badge");
      expect(badge).toBeTruthy();
      expect(badge.textContent).toContain("Escalated to Agent Console");
    });
  });

  it("test_continue_button_records_decline: clicking Continue logs escalation_declined and removes card", async () => {
    const postSpy = vi.spyOn(api, "post").mockResolvedValue({ success: true });

    useAIStore.setState({
      messages: [
        {
          role: "user",
          content: "Fix typo and clean up functions",
        },
        {
          role: "assistant",
          content: "Understood, proceeding...",
          escalation_recommended: true,
          escalation_reasoning: "architectural changes",
        },
      ],
      escalationRecommended: true,
      escalationReasoning: "architectural changes",
    });

    await act(async () => {
      render(<AIChatPanel />);
    });

    const continueBtn = screen.getByTestId("continue-rony-btn");
    await act(async () => {
      fireEvent.click(continueBtn);
    });

    await waitFor(() => {
      expect(postSpy).toHaveBeenCalledWith(
        "/api/intelligence/record-action",
        expect.objectContaining({
          action: "escalation_declined",
        })
      );
    });

    // Escalation card should disappear
    await waitFor(() => {
      expect(screen.queryByTestId("escalation-card")).toBeNull();
    });
  });
});
