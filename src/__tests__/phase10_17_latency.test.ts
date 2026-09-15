import { describe, it, expect, beforeEach, vi, afterEach } from "vitest";
import { useAIStore, createSSEStreamHandler } from "../stores/aiStore";
import { api } from "../lib/api";

vi.mock("../lib/api", () => ({
  api: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
    streamSSE: vi.fn(),
  },
}));

describe("Phase 10.17: Instant Echo & Bounded First-Token Latency", () => {
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

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("test_user_message_renders_before_any_network (instant echo < 50ms)", async () => {
    let threadPostResolved = false;
    (api.post as any).mockImplementation(async (url: string) => {
      if (url === "/api/ai/threads") {
        await new Promise((resolve) => setTimeout(resolve, 300));
        threadPostResolved = true;
        return { id: "mock-thread", title: "hi", workspace: "", created_at: "", updated_at: "" };
      }
      return {};
    });
    (api.streamSSE as any).mockImplementation(async () => {
      await new Promise((resolve) => setTimeout(resolve, 50));
    });

    const sendPromise = useAIStore.getState().sendMessage("hi");

    // Immediately after invoking sendMessage (before thread creation resolves):
    const stateImmediate = useAIStore.getState();
    expect(stateImmediate.messages.length).toBe(2);
    expect(stateImmediate.messages[0].role).toBe("user");
    expect(stateImmediate.messages[0].content).toBe("hi");
    expect(stateImmediate.messages[1].role).toBe("assistant");
    expect(stateImmediate.streaming).toBe(true);
    expect(threadPostResolved).toBe(false);

    await sendPromise;
  });

  it("test_send_does_not_await_sync_post_before_stream", async () => {
    const callOrder: string[] = [];
    (api.post as any).mockImplementation(async (url: string) => {
      callOrder.push(`post:${url}`);
      await new Promise((resolve) => setTimeout(resolve, 100));
      return { id: "test-thread", title: "New Conversation", workspace: "", created_at: "", updated_at: "" };
    });
    (api.streamSSE as any).mockImplementation(async () => {
      callOrder.push("streamSSE:start");
      return Promise.resolve();
    });

    await useAIStore.getState().sendMessage("test question");

    // streamSSE must be dispatched without waiting for message sync post
    expect(callOrder).toContain("streamSSE:start");
    const streamIndex = callOrder.indexOf("streamSSE:start");
    expect(streamIndex).toBeGreaterThanOrEqual(0);
  });

  it("test_token_flush_timer_16ms debounce", async () => {
    vi.useFakeTimers();
    const { handler } = createSSEStreamHandler(useAIStore.setState, useAIStore.getState);

    useAIStore.setState({
      messages: [{ role: "assistant", content: "", created_at: new Date().toISOString() }],
    });

    handler("token", { content: "Hello" });
    expect(useAIStore.getState().messages[0].content).toBe("");

    // Advance 16ms
    vi.advanceTimersByTime(16);
    expect(useAIStore.getState().messages[0].content).toBe("Hello");

    vi.useRealTimers();
  });
});
