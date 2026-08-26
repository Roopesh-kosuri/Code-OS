import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { useAIStore, createSSEStreamHandler } from "../stores/aiStore";
import { useWorkspaceStore } from "../stores/workspaceStore";
import { useEditorStore } from "../stores/editorStore";
import { useRunStore } from "../stores/runStore";
import { api } from "../lib/api";

function resetStores() {
  useAIStore.setState({
    messages: [],
    pendingApprovals: [],
    pendingUserResponse: null,
    streaming: false,
    agentMode: true,
    error: null,
    currentThreadId: "th_d4_test",
    currentTier: null,
    currentTierLabel: null,
    currentTierReason: null,
    agentPlan: null,
    agentToolHistory: [],
  });
  useWorkspaceStore.setState({
    currentWorkspace: { path: "D:/ws_d4", name: "ws_d4", is_current: true },
    restrictedMode: false,
    activeWorkspaces: [{ path: "D:/ws_d4", name: "ws_d4", is_current: true }],
  });
}

describe("D4: aiStore createSSEStreamHandler event matrix", () => {
  beforeEach(resetStores);
  afterEach(() => vi.restoreAllMocks());

  it("tier_routing event sets tier, label, and reason correctly", () => {
    const { handler } = createSSEStreamHandler(useAIStore.setState, useAIStore.getState);
    handler("tier_routing", { tier: 2, label: "Deep think", reason: "complex task" });
    const s = useAIStore.getState();
    expect(s.currentTier).toBe(2);
    expect(s.currentTierLabel).toBe("Deep think");
    expect(s.currentTierReason).toBe("complex task");
  });

  it("tier_routing with missing label defaults to tier-based label", () => {
    const { handler } = createSSEStreamHandler(useAIStore.setState, useAIStore.getState);
    handler("tier_routing", { tier: 1 });
    const s = useAIStore.getState();
    expect(s.currentTier).toBe(1);
    expect(s.currentTierLabel).toBeTruthy();
  });

  it("status event attaches agentStatus to last assistant message", () => {
    useAIStore.setState({
      messages: [
        { role: "user", content: "hello" },
        { role: "assistant", content: "", agentStatus: null },
      ],
    });
    const { handler } = createSSEStreamHandler(useAIStore.setState, useAIStore.getState);
    handler("status", { type: "tool", message: "Reading file", tool: "read_file" });
    const msgs = useAIStore.getState().messages;
    const last = msgs[msgs.length - 1];
    expect(last.agentStatus?.type).toBe("tool");
    expect(last.agentStatus?.message).toBe("Reading file");
    expect(last.agentStatus?.tool).toBe("read_file");
  });

  it("status tool event is added to agentToolHistory", () => {
    useAIStore.setState({
      messages: [{ role: "assistant", content: "" }],
      agentToolHistory: [],
    });
    const { handler } = createSSEStreamHandler(useAIStore.setState, useAIStore.getState);
    handler("status", { type: "tool", detail: "Running pytest", tool: "run_command" });
    const history = useAIStore.getState().agentToolHistory;
    expect(history.length).toBeGreaterThanOrEqual(1);
    const entry = history.find((h) => h.tool === "run_command");
    expect(entry).toBeDefined();
    expect(entry!.detail).toBe("Running pytest");
  });

  it("ask_user event sets pendingUserResponse with question and options", () => {
    const { handler } = createSSEStreamHandler(useAIStore.setState, useAIStore.getState);
    handler("ask_user", {
      action_id: "q_001",
      question: "Which approach do you prefer?",
      options: ["Option A", "Option B", "Option C"],
    });
    const pur = useAIStore.getState().pendingUserResponse;
    expect(pur).not.toBeNull();
    expect(pur!.action_id).toBe("q_001");
    expect(pur!.question).toBe("Which approach do you prefer?");
    expect(pur!.options).toEqual(["Option A", "Option B", "Option C"]);
  });

  it("approval_request event pushes to pendingApprovals list", () => {
    const { handler } = createSSEStreamHandler(useAIStore.setState, useAIStore.getState);
    handler("approval_request", {
      action_id: "ap_001",
      action_type: "command",
      command: "rm -rf dist/",
      reason: "Cleaning build artifacts",
    });
    const approvals = useAIStore.getState().pendingApprovals;
    expect(approvals.length).toBe(1);
    expect(approvals[0].action_id).toBe("ap_001");
    expect(approvals[0].command).toBe("rm -rf dist/");
    expect(approvals[0].reason).toBe("Cleaning build artifacts");
  });

  it("multiple approval_request events accumulate in pendingApprovals", () => {
    const { handler } = createSSEStreamHandler(useAIStore.setState, useAIStore.getState);
    handler("approval_request", { action_id: "ap_a", action_type: "edit", reason: "edit 1" });
    handler("approval_request", { action_id: "ap_b", action_type: "command", command: "ls", reason: "edit 2" });
    const approvals = useAIStore.getState().pendingApprovals;
    expect(approvals.length).toBe(2);
    expect(approvals.map((a) => a.action_id)).toContain("ap_a");
    expect(approvals.map((a) => a.action_id)).toContain("ap_b");
  });

  it("plan event sets agentPlan with steps and current index", () => {
    const { handler } = createSSEStreamHandler(useAIStore.setState, useAIStore.getState);
    handler("plan", {
      steps: ["Step 1: Analyze", "Step 2: Implement", "Step 3: Test"],
      current: 1,
    });
    const plan = useAIStore.getState().agentPlan;
    expect(plan).not.toBeNull();
    expect(plan!.steps.length).toBe(3);
    expect(plan!.current).toBe(1);
  });

  it("done event sets streaming=false and records final status", () => {
    useAIStore.setState({ streaming: true });
    const { handler } = createSSEStreamHandler(useAIStore.setState, useAIStore.getState);
    handler("done", { success: true, message: "Task completed" });
    expect(useAIStore.getState().streaming).toBe(false);
  });

  it("error event sets streaming=false and sets error field", () => {
    useAIStore.setState({ streaming: true, error: null });
    const { handler } = createSSEStreamHandler(useAIStore.setState, useAIStore.getState);
    handler("error", { message: "Provider unreachable", code: 503 });
    const s = useAIStore.getState();
    expect(s.error).toBe("Provider unreachable");
    expect(s.pendingApprovals).toEqual([]);
  });

  it("token batching: multiple token events flush content to last assistant message", async () => {
    useAIStore.setState({
      messages: [{ role: "assistant", content: "", agentStatus: null }],
    });
    const { handler, flushTokens } = createSSEStreamHandler(useAIStore.setState, useAIStore.getState);
    handler("token", { content: "Hello" });
    handler("token", { content: " world" });
    handler("token", { content: "!" });

    // Force flush
    flushTokens();

    const msgs = useAIStore.getState().messages;
    const lastContent = msgs[msgs.length - 1]?.content ?? "";
    expect(lastContent).toBe("Hello world!");
  });
});

describe("D4: workspaceStore state transitions", () => {
  it("setRestrictedMode updates restrictedMode flag", () => {
    useWorkspaceStore.getState().setRestrictedMode(true);
    expect(useWorkspaceStore.getState().restrictedMode).toBe(true);
    useWorkspaceStore.getState().setRestrictedMode(false);
    expect(useWorkspaceStore.getState().restrictedMode).toBe(false);
  });

  it("setOpeningFolder updates isOpeningFolder state", () => {
    useWorkspaceStore.getState().setOpeningFolder(true);
    expect(useWorkspaceStore.getState().isOpeningFolder).toBe(true);
    useWorkspaceStore.getState().setOpeningFolder(false);
    expect(useWorkspaceStore.getState().isOpeningFolder).toBe(false);
  });

  it("closeWorkspace clears currentWorkspace when matching", () => {
    useWorkspaceStore.setState({
      currentWorkspace: { path: "D:/ws_test", name: "ws_test", is_current: true },
      activeWorkspaces: [{ path: "D:/ws_test", name: "ws_test", is_current: true }],
    });
    useWorkspaceStore.getState().closeWorkspace("D:/ws_test");
    expect(useWorkspaceStore.getState().currentWorkspace).toBeNull();
  });
});

describe("D4: editorStore state transitions", () => {
  it("setCursorPosition updates cursor position in state", () => {
    useEditorStore.getState().setCursorPosition({ line: 42, col: 10 });
    expect(useEditorStore.getState().cursorPosition).toEqual({ line: 42, col: 10 });
  });

  it("setMarkerStats updates errors and warnings counts", () => {
    useEditorStore.getState().setMarkerStats({ errors: 3, warnings: 5 });
    expect(useEditorStore.getState().markerStats).toEqual({ errors: 3, warnings: 5 });
  });

  it("toggleSplit sets splitPath", () => {
    useEditorStore.getState().toggleSplit("src/split.py");
    expect(useEditorStore.getState().splitPath).toBe("src/split.py");
    useEditorStore.getState().toggleSplit(null);
    expect(useEditorStore.getState().splitPath).toBeNull();
  });
});

describe("D4: runStore state transitions", () => {
  it("clearLogs empties logs array", () => {
    useRunStore.setState({
      logs: [
        { id: "1", type: "stdout", text: "Compiling...", timestamp: 100 },
        { id: "2", type: "stderr", text: "Warning", timestamp: 101 },
      ],
    });
    useRunStore.getState().clearLogs();
    expect(useRunStore.getState().logs).toHaveLength(0);
  });

  it("fetchToolchains populates toolchains list via API", async () => {
    const mockToolchains = [
      { id: "python", name: "Python", installed: true, version: "3.11" },
      { id: "node", name: "Node.js", installed: true, version: "20.0" },
    ];
    vi.spyOn(api, "get").mockResolvedValue({ toolchains: mockToolchains });

    await useRunStore.getState().fetchToolchains();
    expect(useRunStore.getState().toolchains).toEqual(mockToolchains);
  });
});

