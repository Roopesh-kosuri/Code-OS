import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { useTeamStore, TeamTask, TeamConfig, DEFAULT_TEAM_CONFIG } from "../features/ai/console/teamStore";
import { AgentRoster } from "../features/ai/console/AgentRoster";
import { DAGBoard } from "../features/ai/console/DAGBoard";
import { TeamConsole } from "../features/ai/console/TeamConsole";
import { AgentConsole } from "../features/ai/AgentConsole";
import { useWorkspaceStore } from "../stores/workspaceStore";
import { useBackendStore } from "../stores/backendStore";
import { api } from "../lib/api";

describe("Phase B3 — Frontend Core: Team Console, DAG Board & Agent Roster", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.spyOn(api, "get").mockResolvedValue([]);
    useTeamStore.getState().reset();
    useWorkspaceStore.setState({
      currentWorkspace: { path: "D:/test-workspace", name: "test-ws", is_current: true },
      trustedWorkspaces: { "D:/test-workspace": true },
    });
    useBackendStore.setState({ status: "connected" });
  });

  afterEach(() => {
    useTeamStore.getState().reset();
  });

  // ── Test 1: Team Store SSE Connection & Event Parsing ─────────────────────────
  it("test_team_store_sse_connection: handles all SSE events and updates state atomically", () => {
    const store = useTeamStore.getState();

    // 1. Snapshot event
    store.handleSSEEvent("team_snapshot", {
      job_id: "job_snap_test",
      status: "running",
      tasks: [
        { id: "t1", title: "Architecture Spec", assigned_agent: "architect", status: "completed", dependencies: [] },
        { id: "t2", title: "Core Modules", assigned_agent: "coder", status: "running", dependencies: ["t1"] },
      ],
      messages: [
        { id: 1, job_id: "job_snap_test", sender_role: "architect", recipient_role: "all", message_type: "chat", content: "Architecture ready", timestamp: 100 },
      ],
      metrics: {
        architect: { total_tokens: 500, input_tokens: 300, output_tokens: 200, total_cost: 0.005, message_count: 1 },
      },
      team_config: { ...DEFAULT_TEAM_CONFIG, architect_model: "gpt-4o-custom" },
    });

    let state = useTeamStore.getState();
    expect(state.jobStatus).toBe("running");
    expect(state.tasks.length).toBe(2);
    expect(state.tasks[0].title).toBe("Architecture Spec");
    expect(state.teamMessages.length).toBe(1);
    expect(state.teamConfig.architect_model).toBe("gpt-4o-custom");
    expect(state.agentMetrics.architect.total_tokens).toBe(500);

    // 2. team_step_update event
    store.handleSSEEvent("team_step_update", {
      task_id: "t2",
      status: "completed",
      role: "coder",
      duration_seconds: 4.2,
    });
    state = useTeamStore.getState();
    const t2 = state.tasks.find((t) => t.id === "t2");
    expect(t2?.status).toBe("completed");
    expect(t2?.duration_seconds).toBe(4.2);

    // 3. team_message event
    store.handleSSEEvent("team_message", {
      id: 2,
      sender_role: "coder",
      recipient_role: "reviewer",
      content: "Code implementation finished, please audit.",
      message_type: "chat",
    });
    state = useTeamStore.getState();
    expect(state.teamMessages.length).toBe(2);
    expect(state.teamMessages[1].content).toContain("Code implementation finished");

    // 4. team_handoff event
    store.handleSSEEvent("team_handoff", {
      type: "diffs",
      from_role: "coder",
      to_role: "reviewer",
      summary: "Transferred auth.py diff",
    });
    state = useTeamStore.getState();
    expect(state.handoffs.length).toBe(1);
    expect(state.handoffs[0].type).toBe("diffs");

    // 5. team_approval event
    store.handleSSEEvent("team_approval", {
      action_id: "act_test_99",
      agent_role: "devops",
      command: "npm run build",
    });
    state = useTeamStore.getState();
    expect(state.approvals.length).toBe(1);
    expect(state.approvals[0].action_id).toBe("act_test_99");

    // 6. team_repair event
    store.handleSSEEvent("team_repair", {
      round: 1,
      max_rounds: 3,
      reason: "Syntax error in token generator",
    });
    state = useTeamStore.getState();
    expect(state.teamMessages.some((m) => m.content.includes("Auto-Repair Round 1/3"))).toBe(true);

    // 7. team_metrics event
    store.handleSSEEvent("team_metrics", {
      role: "coder",
      total_tokens: 1500,
      cost_usd: 0.02,
    });
    state = useTeamStore.getState();
    expect(state.agentMetrics.coder.total_tokens).toBe(1500);
    expect(state.agentMetrics.coder.total_cost).toBe(0.02);

    // 8. team_status event
    store.handleSSEEvent("team_status", { status: "completed" });
    state = useTeamStore.getState();
    expect(state.jobStatus).toBe("completed");
  });

  // ── Test 2: Agent Roster Renders Roles ────────────────────────────────────────
  it("test_agent_roster_renders_roles: renders all 5 role cards with model selector and metrics", () => {
    useTeamStore.setState({
      agentMetrics: {
        architect: { total_tokens: 1200, input_tokens: 800, output_tokens: 400, total_cost: 0.012, message_count: 2 },
        coder: { total_tokens: 4500, input_tokens: 3000, output_tokens: 1500, total_cost: 0.045, message_count: 5 },
        reviewer: { total_tokens: 600, input_tokens: 400, output_tokens: 200, total_cost: 0.006, message_count: 1 },
        tester: { total_tokens: 800, input_tokens: 600, output_tokens: 200, total_cost: 0.008, message_count: 1 },
        devops: { total_tokens: 300, input_tokens: 200, output_tokens: 100, total_cost: 0.003, message_count: 1 },
      },
      tasks: [
        { id: "t_code", job_id: "j1", title: "Writing migrations", assigned_agent: "coder", status: "running", dependencies: [] },
      ],
    });

    render(<AgentRoster />);

    // All 5 primary roles present
    expect(screen.getByTestId("agent-card-architect")).toBeDefined();
    expect(screen.getByTestId("agent-card-coder")).toBeDefined();
    expect(screen.getByTestId("agent-card-reviewer")).toBeDefined();
    expect(screen.getByTestId("agent-card-tester")).toBeDefined();
    expect(screen.getByTestId("agent-card-devops")).toBeDefined();

    // Verify role display names
    expect(screen.getByText("Architect")).toBeDefined();
    expect(screen.getByText("Coder")).toBeDefined();
    expect(screen.getByText("Reviewer")).toBeDefined();
    expect(screen.getByText("Tester")).toBeDefined();
    expect(screen.getByText("DevOps")).toBeDefined();

    // Verify Coder is marked RUNNING and shows active task title
    expect(screen.getByText("Writing migrations")).toBeDefined();

    // Verify tokens & costs rendered
    expect(screen.getByText("4,500")).toBeDefined();
    expect(screen.getByText("$0.0450")).toBeDefined();

    // Verify "Add Agent" button exists
    expect(screen.getByText(/Add Agent/i)).toBeDefined();
  });

  // ── Test 3: DAG Board Renders Nodes and Dependency Flow ───────────────────────
  it("test_dag_board_renders_nodes: renders tasks as DAG nodes and opens detail drawer on click", () => {
    const tasks: TeamTask[] = [
      {
        id: "step_arch",
        job_id: "j1",
        title: "Design Microservices Architecture",
        assigned_agent: "architect",
        status: "completed",
        dependencies: [],
        duration_seconds: 3.5,
      },
      {
        id: "step_coder",
        job_id: "j1",
        title: "Build REST Endpoints",
        assigned_agent: "coder",
        status: "running",
        dependencies: ["step_arch"],
      },
      {
        id: "step_test",
        job_id: "j1",
        title: "Run Integration Tests",
        assigned_agent: "tester",
        status: "pending",
        dependencies: ["step_coder"],
      },
    ];

    useTeamStore.setState({ tasks });

    render(<DAGBoard />);

    // Check that all 3 task nodes are rendered
    expect(screen.getByTestId("dag-node-step_arch")).toBeDefined();
    expect(screen.getByTestId("dag-node-step_coder")).toBeDefined();
    expect(screen.getByTestId("dag-node-step_test")).toBeDefined();

    expect(screen.getByText("Design Microservices Architecture")).toBeDefined();
    expect(screen.getByText("Build REST Endpoints")).toBeDefined();
    expect(screen.getByText("Run Integration Tests")).toBeDefined();

    // Click on step_arch node to open side drawer
    fireEvent.click(screen.getByTestId("dag-node-step_arch"));

    // Verify drawer displays task details
    expect(screen.getByTestId("dag-task-details")).toBeDefined();
    expect(screen.getAllByText("@architect").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("3.50s")).toBeDefined();
  });

  // ── Test 4: Mode Toggle Switches Views ────────────────────────────────────────
  it("test_mode_toggle_switches_views: switches between Standard Workflow and Team Mode in AgentConsole", () => {
    render(<AgentConsole />);

    // Default view: Standard Workflow
    expect(screen.getByText("Agent Instruction")).toBeDefined();
    expect(screen.getByTestId("mode-toggle-standard")).toBeDefined();
    expect(screen.getByTestId("mode-toggle-team")).toBeDefined();

    // Switch to Team Mode
    fireEvent.click(screen.getByTestId("mode-toggle-team"));

    // Team Mode view should be rendered
    expect(screen.getByTestId("team-console")).toBeDefined();
    expect(screen.getByText("Autonomous Team Engine")).toBeDefined();
    expect(screen.getByText("Agent Roster")).toBeDefined();

    // Switch back to Standard Workflow
    fireEvent.click(screen.getByTestId("mode-toggle-standard"));
    expect(screen.getByText("Agent Instruction")).toBeDefined();
    expect(screen.queryByTestId("team-console")).toBeNull();
  });

  // ── Test 5: Submit Team Job with Team Config ──────────────────────────────────
  it("test_submit_team_job: submits workflow to POST /api/team/jobs with full team config", async () => {
    const postSpy = vi.spyOn(api, "post").mockResolvedValue({
      job_id: "team_job_submitted_1",
      status: "queued",
      task_count: 4,
    });

    render(<TeamConsole />);

    const textarea = screen.getByPlaceholderText(/Describe your large project/i);
    fireEvent.change(textarea, {
      target: { value: "Build a real-time messaging system with WebSockets and Redis" },
    });

    const submitBtn = screen.getByText(/Plan & Execute Team Job/i);
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(postSpy).toHaveBeenCalledTimes(1);
    });

    const callArgs = postSpy.mock.calls[0];
    expect(callArgs[0]).toBe("/api/team/jobs");
    const payload = callArgs[1] as any;
    expect(payload.workspace).toBe("D:/test-workspace");
    expect(payload.user_request).toContain("real-time messaging system");
    expect(payload.team_config.architect_model).toBe("gpt-4o");
    expect(payload.team_config.coder_model).toBe("claude-3-5-sonnet-latest");
    expect(payload.team_config.tester_model).toBe("llama-3.3-70b-versatile");

    expect(useTeamStore.getState().activeJobId).toBe("team_job_submitted_1");
  });
});
