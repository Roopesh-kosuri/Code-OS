import { describe, it, expect, vi, beforeEach } from "vitest";
import { useAIStore, type ExtendedChatMessage } from "../stores/aiStore";
import { useWorkspaceStore } from "../stores/workspaceStore";
import { api } from "../lib/api";

describe("useAIStore Extended Behavioral Suite", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    useAIStore.getState().clearAgentState();
    useWorkspaceStore.setState({
      currentWorkspace: { path: "D:/ws", name: "ws", is_current: true },
      restrictedMode: false,
    });
    useAIStore.setState({
      messages: [],
      pendingApprovals: [],
      pendingUserResponse: null,
      streaming: false,
      agentMode: true,
      error: null,
      currentThreadId: "th_main",
    });
  });

  it("handles agent mode toggling and state clearing", () => {
    const store = useAIStore.getState();
    expect(store.agentMode).toBe(true);

    store.toggleAgentMode();
    expect(useAIStore.getState().agentMode).toBe(false);

    store.setAgentMode(true);
    expect(useAIStore.getState().agentMode).toBe(true);

    store.clearAgentState();
    expect(useAIStore.getState().pendingApprovals).toEqual([]);
    expect(useAIStore.getState().pendingUserResponse).toBeNull();
  });

  it("fetches models, token usage, and provider health", async () => {
    vi.spyOn(api, "get").mockImplementation((url) => {
      if (String(url).includes("/api/ai/models")) {
        return Promise.resolve([{ name: "qwen2.5-coder:7b", provider: "ollama" }]);
      }
      if (String(url).includes("/api/ai/token-usage")) {
        return Promise.resolve({ ollama: { input_tokens: 1000, output_tokens: 500, total_tokens: 1500, estimated_cost_usd: 0 } });
      }
      if (String(url).includes("/api/ai/provider-health")) {
        return Promise.resolve({ ollama: { status: "healthy", consecutive_failures: 0 } });
      }
      return Promise.resolve([]);
    });

    await useAIStore.getState().refreshModels();
    expect(useAIStore.getState().models.length).toBe(1);

    await useAIStore.getState().fetchTokenUsage();
    expect(useAIStore.getState().tokenUsage?.ollama.total_tokens).toBe(1500);

    await useAIStore.getState().fetchProviderHealth();
    expect(useAIStore.getState().providerHealth?.ollama.status).toBe("healthy");
  });

  it("approves and rejects pending agent actions via API", async () => {
    vi.spyOn(api, "post").mockResolvedValue({ status: "ok" });

    useAIStore.setState({
      pendingApprovals: [
        { action_id: "act_101", action_type: "command", command: "pytest", reason: "testing" },
      ],
    });

    await useAIStore.getState().approveAction("act_101", true);
    expect(api.post).toHaveBeenCalledWith("/api/ai/chat-agent/approve/act_101", { always_allow: true, trust_pattern: undefined });
    expect(useAIStore.getState().pendingApprovals?.length).toBe(0);

    useAIStore.setState({
      pendingApprovals: [
        { action_id: "act_102", action_type: "edit", reason: "modify config" },
      ],
    });

    await useAIStore.getState().rejectAction("act_102");
    expect(api.post).toHaveBeenCalledWith("/api/ai/chat-agent/reject/act_102");
    expect(useAIStore.getState().pendingApprovals?.length).toBe(0);
  });

  it("responds to interactive agent user questions", async () => {
    vi.spyOn(api, "post").mockResolvedValue({ status: "ok" });

    useAIStore.setState({
      pendingUserResponse: {
        action_id: "ask_99",
        question: "Proceed?",
        options: ["Yes", "No"],
      },
    });

    await useAIStore.getState().respondToUserQuestion("ask_99", "Yes");
    expect(api.post).toHaveBeenCalledWith("/api/ai/chat-agent/respond/ask_99", { answer: "Yes" });
    expect(useAIStore.getState().pendingUserResponse).toBeNull();
  });

  it("handles stop generation and resets streaming flags", () => {
    vi.spyOn(api, "post").mockResolvedValue({});
    useAIStore.setState({ streaming: true });

    useAIStore.getState().stopGeneration();
    expect(useAIStore.getState().streaming).toBe(false);
  });

  it("loads and switches chat threads", async () => {
    vi.spyOn(api, "get").mockImplementation((url) => {
      if (String(url).includes("/api/ai/threads/th_1/messages")) {
        return Promise.resolve([
          { role: "user", content: "Hello" },
          { role: "assistant", content: "Hi there" },
        ]);
      }
      if (String(url).includes("/api/ai/threads")) {
        return Promise.resolve([
          { id: "th_1", title: "Thread 1", created_at: "2026-08-26", message_count: 2 },
        ]);
      }
      return Promise.resolve([]);
    });

    await useAIStore.getState().loadThreads("D:/ws");
    expect(useAIStore.getState().threads.length).toBe(1);

    await useAIStore.getState().switchThread("th_1");
    expect(useAIStore.getState().currentThreadId).toBe("th_1");
    expect(useAIStore.getState().messages.length).toBe(2);
  });
});
