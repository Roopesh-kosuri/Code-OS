import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import { useTeamStore, type TeamMessage } from "../features/ai/console/teamStore";
import { TeamChatPanel } from "../features/ai/console/TeamChatPanel";
import { api } from "../lib/api";

describe("Phase B4 — Live Team Chat + Operator Injection", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    act(() => {
      useTeamStore.getState().reset();
      useTeamStore.setState({ activeJobId: "job_b4_test", jobStatus: "running" });
    });
  });

  afterEach(() => {
    act(() => {
      useTeamStore.getState().reset();
    });
  });

  // ── Test 1: Live chat renders messages with correct role badges ───────────────
  it("test_live_chat_renders_role_badges: renders messages with all role badges and icons", () => {
    const messages: TeamMessage[] = [
      { id: 1, job_id: "job_b4_test", sender_role: "architect", recipient_role: "all", message_type: "chat", content: "Designed schema", timestamp: 100 },
      { id: 2, job_id: "job_b4_test", sender_role: "coder", recipient_role: "reviewer", message_type: "chat", content: "Implemented code", timestamp: 101 },
      { id: 3, job_id: "job_b4_test", sender_role: "reviewer", recipient_role: "coder", message_type: "chat", content: "Reviewed PR", timestamp: 102 },
      { id: 4, job_id: "job_b4_test", sender_role: "tester", recipient_role: "all", message_type: "chat", content: "Executed tests", timestamp: 103 },
      { id: 5, job_id: "job_b4_test", sender_role: "devops", recipient_role: "all", message_type: "chat", content: "Configured deployment", timestamp: 104 },
      { id: 6, job_id: "job_b4_test", sender_role: "operator", recipient_role: "all", message_type: "injection", content: "Operator instruction", timestamp: 105 },
      { id: 7, job_id: "job_b4_test", sender_role: "system", recipient_role: "all", message_type: "system", content: "System initialized", timestamp: 106 },
    ];

    act(() => {
      useTeamStore.setState({ teamMessages: messages });
    });

    render(<TeamChatPanel />);

    // Verify badges for each role
    expect(screen.getByTestId("badge-architect")).toBeTruthy();
    expect(screen.getByTestId("badge-coder")).toBeTruthy();
    expect(screen.getByTestId("badge-reviewer")).toBeTruthy();
    expect(screen.getByTestId("badge-tester")).toBeTruthy();
    expect(screen.getByTestId("badge-devops")).toBeTruthy();
    expect(screen.getByTestId("badge-operator")).toBeTruthy();
    expect(screen.getByTestId("system-message").textContent).toContain("System initialized");
  });

  // ── Test 2: Decision message expands and collapses rationale ──────────────────
  it("test_decision_message_expands_collapses_rationale: toggles expandable rationale view", () => {
    const decisionMessage: TeamMessage = {
      id: 10,
      job_id: "job_b4_test",
      sender_role: "architect",
      recipient_role: "all",
      message_type: "decision",
      content: "I chose Argon2id for password hashing because of GPU resistance.",
      details: {
        rationale: "Argon2id protects against both side-channel and GPU cracking attacks with configurable memory cost.",
      },
      timestamp: 200,
    };

    act(() => {
      useTeamStore.setState({ teamMessages: [decisionMessage] });
    });

    render(<TeamChatPanel />);

    expect(screen.getByText("I chose Argon2id for password hashing because of GPU resistance.")).toBeTruthy();
    // Rationale should not be visible before clicking expand
    expect(screen.queryByTestId("decision-rationale")).toBeNull();

    // Click Expand Rationale
    const toggleBtn = screen.getByTestId("decision-toggle");
    expect(toggleBtn.textContent).toContain("Expand Rationale");
    act(() => {
      fireEvent.click(toggleBtn);
    });

    // Rationale should now be visible
    const rationaleEl = screen.getByTestId("decision-rationale");
    expect(rationaleEl).toBeTruthy();
    expect(rationaleEl.textContent).toContain("Argon2id protects against both side-channel");
    expect(toggleBtn.textContent).toContain("Collapse Rationale");

    // Click Collapse Rationale
    act(() => {
      fireEvent.click(toggleBtn);
    });
    expect(screen.queryByTestId("decision-rationale")).toBeNull();
  });

  // ── Test 3: Handoff click opens Handoff Inspector Modal ─────────────────────────
  it("test_handoff_click_opens_inspector_modal: opens modal with preview and JSON tabs", async () => {
    const handoffMessage: TeamMessage = {
      id: 20,
      job_id: "job_b4_test",
      sender_role: "coder",
      recipient_role: "reviewer",
      message_type: "handoff",
      content: "Transferred auth.py implementation diff",
      artifact: {
        type: "diffs",
        from_role: "coder",
        to_role: "reviewer",
        summary: "Transferred auth.py implementation diff",
        payload: {
          modified_files: ["auth.py", "test_auth.py"],
          diffs: [{ path: "auth.py", diff: "+ import argon2\n+ def hash_pw(): pass" }],
        },
      },
      timestamp: 300,
    };

    act(() => {
      useTeamStore.setState({ teamMessages: [handoffMessage] });
    });

    render(<TeamChatPanel />);

    // Inspector modal not open initially
    expect(screen.queryByTestId("handoff-inspector-modal")).toBeNull();

    // Click handoff card
    const handoffCard = screen.getByTestId("handoff-card");
    act(() => {
      fireEvent.click(handoffCard);
    });

    // Modal is now open
    expect(screen.getByTestId("handoff-inspector-modal")).toBeTruthy();
    expect(screen.getByText("Handoff Inspector")).toBeTruthy();
    expect(screen.getByText("Modified Files (2)")).toBeTruthy();
    expect(screen.getAllByText("auth.py").length).toBeGreaterThan(0);

    // Switch to Raw JSON tab
    const jsonTab = screen.getByTestId("tab-json");
    act(() => {
      fireEvent.click(jsonTab);
    });
    expect(screen.getByTestId("handoff-json-view")).toBeTruthy();

    // Close modal
    const closeBtn = screen.getByTestId("close-handoff-inspector");
    act(() => {
      fireEvent.click(closeBtn);
    });
    expect(screen.queryByTestId("handoff-inspector-modal")).toBeNull();
  });

  // ── Test 4: Operator injection sends POST and renders gold badge ───────────────
  it("test_operator_injection_sends_post_and_renders_gold_badge: submits injection and renders badge", async () => {
    const postSpy = vi.spyOn(api, "post").mockResolvedValue({
      success: true,
      job_id: "job_b4_test",
      message_id: 88,
      target_role: "all",
      content: "Ensure test coverage is 100%",
    });

    render(<TeamChatPanel />);

    const input = screen.getByTestId("operator-prompt-input");
    act(() => {
      fireEvent.change(input, { target: { value: "Ensure test coverage is 100%" } });
    });

    const submitBtn = screen.getByTestId("operator-submit-btn");
    await act(async () => {
      fireEvent.click(submitBtn);
    });

    await waitFor(() => {
      expect(postSpy).toHaveBeenCalledWith("/api/team/jobs/job_b4_test/inject", {
        prompt: "Ensure test coverage is 100%",
        target_role: "all",
        urgent: false,
      });
    });

    // Injected message rendered with Operator gold badge
    await waitFor(() => {
      expect(screen.getByTestId("operator-message")).toBeTruthy();
      expect(screen.getByTestId("badge-operator")).toBeTruthy();
      expect(screen.getByText("Ensure test coverage is 100%")).toBeTruthy();
    });
  });

  // ── Test 5: Urgent injection sets urgent priority ─────────────────────────────
  it("test_urgent_injection_sets_urgent_priority: toggles urgent flag and triggers urgent injection", async () => {
    const postSpy = vi.spyOn(api, "post").mockResolvedValue({
      success: true,
      job_id: "job_b4_test",
      message_id: 99,
      target_role: "coder",
      content: "Urgent: roll back broken database migration",
      urgent: true,
      acknowledged: true,
    });

    render(<TeamChatPanel />);

    // Select role target 'coder'
    const targetSelect = screen.getByTestId("operator-target-select");
    act(() => {
      fireEvent.change(targetSelect, { target: { value: "coder" } });
    });

    // Toggle urgent priority
    const urgentToggle = screen.getByTestId("operator-urgent-toggle");
    act(() => {
      fireEvent.click(urgentToggle);
    });
    expect(urgentToggle.textContent).toContain("Urgent (Pause)");

    // Type prompt
    const input = screen.getByTestId("operator-prompt-input");
    act(() => {
      fireEvent.change(input, { target: { value: "Urgent: roll back broken database migration" } });
    });

    // Submit
    const submitBtn = screen.getByTestId("operator-submit-btn");
    await act(async () => {
      fireEvent.click(submitBtn);
    });

    await waitFor(() => {
      expect(postSpy).toHaveBeenCalledWith("/api/team/jobs/job_b4_test/inject", {
        prompt: "Urgent: roll back broken database migration",
        target_role: "coder",
        urgent: true,
      });
    });

    // Verify Urgent badge and Acknowledged note is rendered in chat feed
    await waitFor(() => {
      expect(screen.getByText("Urgent")).toBeTruthy();
      expect(screen.getByText(/Acknowledged by \[Coder\]/i)).toBeTruthy();
    });
  });

  // ── Test 6: Role filter hides/shows messages correctly ─────────────────────────
  it("test_role_filter_hides_and_shows_messages: filters chat feed by selected role", () => {
    const messages: TeamMessage[] = [
      { id: 1, job_id: "job_b4_test", sender_role: "architect", recipient_role: "all", message_type: "chat", content: "Architect plan v1", timestamp: 10 },
      { id: 2, job_id: "job_b4_test", sender_role: "coder", recipient_role: "reviewer", message_type: "chat", content: "Coder implemented auth", timestamp: 20 },
      { id: 3, job_id: "job_b4_test", sender_role: "tester", recipient_role: "all", message_type: "chat", content: "Tester finished suite", timestamp: 30 },
    ];

    act(() => {
      useTeamStore.setState({ teamMessages: messages });
    });

    render(<TeamChatPanel />);

    // All 3 messages visible initially
    expect(screen.getByText("Architect plan v1")).toBeTruthy();
    expect(screen.getByText("Coder implemented auth")).toBeTruthy();
    expect(screen.getByText("Tester finished suite")).toBeTruthy();

    // Select role filter: 'coder'
    const filterSelect = screen.getByTestId("role-filter");
    act(() => {
      fireEvent.change(filterSelect, { target: { value: "coder" } });
    });

    // Only coder message should be visible
    expect(screen.getByText("Coder implemented auth")).toBeTruthy();
    expect(screen.queryByText("Architect plan v1")).toBeNull();
    expect(screen.queryByText("Tester finished suite")).toBeNull();

    // Reset filter to 'all'
    act(() => {
      fireEvent.change(filterSelect, { target: { value: "all" } });
    });
    expect(screen.getByText("Architect plan v1")).toBeTruthy();
    expect(screen.getByText("Coder implemented auth")).toBeTruthy();
    expect(screen.getByText("Tester finished suite")).toBeTruthy();
  });

  // ── Test 7: Auto-scroll toggle ────────────────────────────────────────────────
  it("test_autoscroll_toggle: toggles auto-scroll state between ON and OFF", () => {
    render(<TeamChatPanel />);

    const autoScrollBtn = screen.getByTestId("autoscroll-toggle");
    expect(autoScrollBtn.textContent).toContain("Auto-scroll: ON");

    act(() => {
      fireEvent.click(autoScrollBtn);
    });
    expect(autoScrollBtn.textContent).toContain("Auto-scroll: OFF");

    act(() => {
      fireEvent.click(autoScrollBtn);
    });
    expect(autoScrollBtn.textContent).toContain("Auto-scroll: ON");
  });
});
