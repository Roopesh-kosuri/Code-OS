import { describe, it, expect, beforeEach, vi } from "vitest";
import { useAIStore, createSSEStreamHandler } from "../stores/aiStore";
import { api } from "../lib/api";
import type { ChatThread } from "../stores/aiStore";

vi.mock("../lib/api", () => ({
  api: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
    streamSSE: vi.fn(),
  },
}));

describe("Final Bounded Push: AI Store Full Event Matrix & Thread CRUD", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useAIStore.setState({
      messages: [],
      streaming: false,
      error: null,
      pendingApproval: null,
      pendingApprovals: [],
      pendingUserResponse: null,
      agentPlan: null,
      threads: [],
      currentThreadId: null,
      currentTokensUsed: 0,
      agentToolHistory: [],
    });
  });

  describe("createSSEStreamHandler Full Event Matrix", () => {
    it("handles tier_routing event", () => {
      const { handler } = createSSEStreamHandler(useAIStore.setState, useAIStore.getState);
      handler("tier_routing", { tier: 2, label: "Deep Reasoning", reason: "Complex multi-step task" });

      const state = useAIStore.getState();
      expect(state.currentTier).toBe(2);
      expect(state.currentTierLabel).toBe("Deep Reasoning");
      expect(state.currentTierReason).toBe("Complex multi-step task");
    });

    it("handles status event", () => {
      const { handler } = createSSEStreamHandler(useAIStore.setState, useAIStore.getState);
      handler("status", { type: "planning", message: "Analyzing codebase architecture", tool: "read_file" });

      const state = useAIStore.getState();
      expect(state.agentStatus?.type).toBe("planning");
      expect(state.agentStatus?.message).toBe("Analyzing codebase architecture");
      expect(state.agentStatus?.tool).toBe("read_file");
    });

    it("handles plan event with steps", () => {
      const { handler } = createSSEStreamHandler(useAIStore.setState, useAIStore.getState);
      handler("plan", {
        steps: [
          { id: "step_1", title: "Read auth config", status: "done" },
          { id: "step_2", title: "Apply patch", status: "running" },
          { id: "step_3", title: "Run tests", status: "pending" },
        ],
        current: 1,
      });

      const state = useAIStore.getState();
      expect(state.agentPlan).not.toBeNull();
      expect(state.agentPlan?.steps.length).toBe(3);
      expect(state.agentPlan?.current).toBe(1);
    });

    it("handles ask_user event", () => {
      const { handler } = createSSEStreamHandler(useAIStore.setState, useAIStore.getState);
      handler("ask_user", {
        action_id: "ask_99",
        question: "Should we run integration tests?",
        options: ["Yes", "No", "Skip"],
      });

      const state = useAIStore.getState();
      expect(state.pendingUserResponse).not.toBeNull();
      expect(state.pendingUserResponse?.question).toBe("Should we run integration tests?");
      expect(state.pendingUserResponse?.options).toEqual(["Yes", "No", "Skip"]);
    });

    it("handles approval_request event and deduplicates", () => {
      const { handler } = createSSEStreamHandler(useAIStore.setState, useAIStore.getState);
      handler("approval_request", {
        action_id: "act_101",
        action_type: "run_command",
        command: "npm test",
        reason: "Run test suite",
      });

      let state = useAIStore.getState();
      expect(state.pendingApprovals.length).toBe(1);
      expect(state.pendingApproval?.action_id).toBe("act_101");
      expect(state.agentStatus?.type).toBe("approval_required");

      // Duplicate action_id replaces item rather than doubling
      handler("approval_request", {
        action_id: "act_101",
        action_type: "run_command",
        command: "npm test --verbose",
        reason: "Updated reason",
      });

      state = useAIStore.getState();
      expect(state.pendingApprovals.length).toBe(1);
      expect(state.pendingApproval?.command).toBe("npm test --verbose");
    });

    it("handles checkpoint event and binds to last assistant message", () => {
      useAIStore.setState({
        messages: [{ role: "assistant", content: "Working..." }],
      });

      const { handler } = createSSEStreamHandler(useAIStore.setState, useAIStore.getState);
      handler("checkpoint", {
        turn_number: 3,
        commit_hash: "a1b2c3d",
        touched_files: ["src/app.py", "tests/test.py"],
      });

      const lastMsg = useAIStore.getState().messages[0];
      expect(lastMsg.checkpoint).toBeDefined();
      expect(lastMsg.checkpoint?.turn_number).toBe(3);
      expect(lastMsg.checkpoint?.commit_hash).toBe("a1b2c3d");
      expect(lastMsg.checkpoint?.touched_files).toEqual(["src/app.py", "tests/test.py"]);
    });

    it("handles metrics event and error event", () => {
      useAIStore.setState({
        messages: [{ role: "assistant", content: "" }],
        streaming: true,
      });

      const { handler } = createSSEStreamHandler(useAIStore.setState, useAIStore.getState);
      handler("metrics", { tokens_used: 1250 });
      expect(useAIStore.getState().currentTokensUsed).toBe(1250);

      handler("error", { message: "Quota exceeded" });
      const state = useAIStore.getState();
      expect(state.error).toBe("Quota exceeded");
      expect(state.messages[0].content).toContain("Quota exceeded");
      expect(state.pendingApproval).toBeNull();
    });

    it("handles done event", () => {
      useAIStore.setState({
        messages: [{ role: "assistant", content: "Finished tasks." }],
        streaming: true,
      });

      const { handler } = createSSEStreamHandler(useAIStore.setState, useAIStore.getState);
      handler("done", { success: true, message: "Task completed successfully" });

      const state = useAIStore.getState();
      expect(state.streaming).toBe(false);
      expect(state.agentStatus?.type).toBe("done");
      expect(state.pendingApproval).toBeNull();
    });

    it("batches tokens and flushes on demand", () => {
      useAIStore.setState({
        messages: [{ role: "assistant", content: "Start: " }],
      });

      const { handler, flushTokens } = createSSEStreamHandler(useAIStore.setState, useAIStore.getState);
      handler("token", "token1 ");
      handler("token", "token2 ");
      handler("token", "token3");

      flushTokens();

      const lastMsg = useAIStore.getState().messages[0];
      expect(lastMsg.content).toBe("Start: token1 token2 token3");
    });
  });

  describe("Thread CRUD and Approval Actions", () => {
    it("loadThreads fetches threads and switches to first active thread", async () => {
      const mockThreads: ChatThread[] = [
        { id: "t1", title: "Thread One", workspace: "/test/workspace", created_at: "2026-08-26T00:00:00Z", updated_at: "2026-08-26T00:00:00Z" },
        { id: "t2", title: "Thread Two", workspace: "/test/workspace", created_at: "2026-08-26T01:00:00Z", updated_at: "2026-08-26T01:00:00Z" },
      ];
      vi.mocked(api.get).mockResolvedValueOnce(mockThreads);
      vi.mocked(api.get).mockResolvedValueOnce([
        { role: "user", content: "Hello" },
        { role: "assistant", content: "Hi" },
      ]);

      await useAIStore.getState().loadThreads("/test/workspace");

      const state = useAIStore.getState();
      expect(state.threads.length).toBe(2);
      expect(state.currentThreadId).toBe("t1");
      expect(state.messages.length).toBe(2);
    });

    it("switchThread, renameThread, and newThread operate correctly", async () => {
      const initialThread: ChatThread = { id: "t1", title: "Old Title", workspace: "/ws", created_at: "", updated_at: "" };
      useAIStore.setState({
        threads: [initialThread],
        currentThreadId: "t1",
      });

      // Rename
      const updatedThread: ChatThread = { id: "t1", title: "New Title", workspace: "/ws", created_at: "", updated_at: "" };
      vi.mocked(api.put).mockResolvedValueOnce(updatedThread);
      await useAIStore.getState().renameThread("t1", "New Title");
      expect(useAIStore.getState().threads[0].title).toBe("New Title");

      // New thread
      await useAIStore.getState().newThread();
      const state = useAIStore.getState();
      expect(state.currentThreadId).toBeNull();
      expect(state.messages).toEqual([]);
      expect(state.error).toBeNull();
    });

    it("deleteThread removes thread and switches to remaining thread", async () => {
      const threads: ChatThread[] = [
        { id: "t1", title: "Thread 1", workspace: "/ws", created_at: "", updated_at: "" },
        { id: "t2", title: "Thread 2", workspace: "/ws", created_at: "", updated_at: "" },
      ];
      useAIStore.setState({
        threads,
        currentThreadId: "t1",
      });

      vi.mocked(api.delete).mockResolvedValueOnce({ success: true });
      vi.mocked(api.get).mockResolvedValueOnce([{ role: "user", content: "From T2" }]);

      await useAIStore.getState().deleteThread("t1");

      const state = useAIStore.getState();
      expect(state.threads.length).toBe(1);
      expect(state.threads[0].id).toBe("t2");
      expect(state.currentThreadId).toBe("t2");
    });

    it("approveAction and rejectAction update pendingApprovals queue", async () => {
      useAIStore.setState({
        pendingApprovals: [
          { action_id: "a1", action_type: "cmd", command: "ls", reason: "list" },
          { action_id: "a2", action_type: "cmd", command: "pwd", reason: "print dir" },
        ],
        pendingApproval: { action_id: "a1", action_type: "cmd", command: "ls", reason: "list" },
      });

      vi.mocked(api.post).mockResolvedValue({ success: true });

      // Approve a1
      await useAIStore.getState().approveAction("a1");
      let state = useAIStore.getState();
      expect(state.pendingApprovals.length).toBe(1);
      expect(state.pendingApproval?.action_id).toBe("a2");

      // Reject a2
      await useAIStore.getState().rejectAction("a2");
      state = useAIStore.getState();
      expect(state.pendingApprovals.length).toBe(0);
      expect(state.pendingApproval).toBeNull();
    });
  });
});
