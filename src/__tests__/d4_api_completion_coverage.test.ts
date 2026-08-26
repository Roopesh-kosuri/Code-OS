import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { api } from "../lib/api";
import {
  registerInlineCompletionProvider,
  useInlineCompletionStore,
} from "../features/editor/inlineCompletionProvider";
import { useSettingsStore } from "../stores/settingsStore";
import { useWorkspaceStore } from "../stores/workspaceStore";

describe("D4 API and Inline Completion Coverage Suite", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    useWorkspaceStore.setState({
      currentWorkspace: { path: "D:/ws_test", name: "test_ws", is_current: true },
    });
    useSettingsStore.setState({
      settings: { "editor.inlineCompletionEnabled": "true" },
    });
    localStorage.removeItem("code-os:editor.inlineCompletion");
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  describe("lib/api.ts SSE streaming and HTTP methods", () => {
    it("parses multi-event SSE streams via api.streamSSE", async () => {
      const ssePayload =
        'event: token\ndata: {"text":"Hello"}\n\nevent: status\ndata: {"status":"thinking"}\n\nevent: done\ndata: {"finish_reason":"stop"}\n\n';

      const mockBody = new ReadableStream({
        start(controller) {
          controller.enqueue(new TextEncoder().encode(ssePayload));
          controller.close();
        },
      });

      const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
        ok: true,
        status: 200,
        body: mockBody,
        text: async () => "",
      } as any);

      const events: Array<{ type: string; data: any }> = [];
      await api.streamSSE("/api/ai/chat/stream", { prompt: "hi" }, (type, data) => {
        events.push({ type, data });
      });

      expect(fetchSpy).toHaveBeenCalled();
      expect(events).toHaveLength(3);
      expect(events[0]).toEqual({ type: "token", data: { text: "Hello" } });
      expect(events[1]).toEqual({ type: "status", data: { status: "thinking" } });
      expect(events[2]).toEqual({ type: "done", data: { finish_reason: "stop" } });
    });

    it("parses raw text SSE data gracefully when non-JSON", async () => {
      const ssePayload = "event: raw_event\ndata: simple-string-payload\n\n";
      const mockBody = new ReadableStream({
        start(controller) {
          controller.enqueue(new TextEncoder().encode(ssePayload));
          controller.close();
        },
      });

      vi.spyOn(globalThis, "fetch").mockResolvedValue({
        ok: true,
        status: 200,
        body: mockBody,
        text: async () => "",
      } as any);

      const events: Array<{ type: string; data: any }> = [];
      await api.streamSSE("/api/test/stream", {}, (type, data) => {
        events.push({ type, data });
      });

      expect(events).toHaveLength(1);
      expect(events[0]).toEqual({ type: "raw_event", data: "simple-string-payload" });
    });

    it("throws error when api.streamSSE receives non-ok response", async () => {
      vi.spyOn(globalThis, "fetch").mockResolvedValue({
        ok: false,
        status: 500,
        text: async () => "Internal Server Crash",
      } as any);

      await expect(api.streamSSE("/api/fail", {}, () => {})).rejects.toThrow("Internal Server Crash");
    });

    it("handles raw token streaming via api.stream", async () => {
      const chunks = ["chunk-1 ", "chunk-2 ", "chunk-3"];
      const mockBody = new ReadableStream({
        start(controller) {
          for (const c of chunks) {
            controller.enqueue(new TextEncoder().encode(c));
          }
          controller.close();
        },
      });

      vi.spyOn(globalThis, "fetch").mockResolvedValue({
        ok: true,
        status: 200,
        body: mockBody,
        text: async () => "",
      } as any);

      const received: string[] = [];
      await api.stream("/api/ai/raw", { prompt: "hello" }, (token) => {
        received.push(token);
      });

      expect(received.join("")).toBe("chunk-1 chunk-2 chunk-3");
    });

    it("executes terminal runFileStream, killRun, and getToolchains", async () => {
      const sseSpy = vi.spyOn(api, "streamSSE").mockResolvedValue();
      const postSpy = vi.spyOn(api, "post").mockResolvedValue({ success: true, message: "Killed", run_id: "r1" });
      const getSpy = vi.spyOn(api, "get").mockResolvedValue({ toolchains: [{ id: "py", name: "Python", available: true }] });

      const onEvent = vi.fn();
      await api.terminal.runFileStream("D:/ws", "main.py", ["--arg1"], onEvent);
      expect(sseSpy).toHaveBeenCalledWith("/api/terminal/run", {
        workspace: "D:/ws",
        file_path: "main.py",
        args: ["--arg1"],
      }, onEvent, undefined);

      const killRes = await api.terminal.killRun("run-123");
      expect(postSpy).toHaveBeenCalledWith("/api/terminal/run/kill", { run_id: "run-123" });
      expect(killRes.success).toBe(true);

      const toolchains = await api.terminal.getToolchains();
      expect(getSpy).toHaveBeenCalledWith("/api/terminal/toolchains");
      expect(toolchains.toolchains[0].id).toBe("py");
    });

    it("executes HTTP PUT and DELETE methods via api wrapper", async () => {
      vi.spyOn(globalThis, "fetch").mockImplementation(async (input: any, init: any) => {
        const urlStr = String(input);
        if (urlStr.includes("/api/auth/token")) {
          return { ok: true, status: 200, headers: new Headers({ "content-type": "application/json" }), json: async () => ({ token: "mock-tok" }) } as any;
        }
        if (init?.method === "PUT") {
          return { ok: true, status: 200, headers: new Headers({ "content-type": "application/json" }), json: async () => ({ updated: true }) } as any;
        }
        if (init?.method === "DELETE") {
          return { ok: true, status: 200, headers: new Headers({ "content-type": "application/json" }), json: async () => ({ deleted: true }) } as any;
        }
        return { ok: true, status: 200, headers: new Headers({ "content-type": "application/json" }), json: async () => ({}) } as any;
      });

      const putRes = await api.put<{ updated: boolean }>("/api/settings/update", { key: "theme", value: "dark" });
      expect(putRes.updated).toBe(true);

      const delRes = await api.delete<{ deleted: boolean }>("/api/items/123");
      expect(delRes.deleted).toBe(true);
    });
  });

  describe("features/editor/inlineCompletionProvider.ts", () => {
    it("registers inline completion provider and updates store latency", async () => {
      let registeredHandler: any = null;
      const mockMonaco: any = {
        languages: {
          registerInlineCompletionsProvider: vi.fn((_selector, provider) => {
            registeredHandler = provider;
            return { dispose: vi.fn() };
          }),
        },
        Range: vi.fn().mockImplementation((sL, sC, eL, eC) => ({
          startLineNumber: sL,
          startColumn: sC,
          endLineNumber: eL,
          endColumn: eC,
        })),
      };

      const disposable = registerInlineCompletionProvider(mockMonaco);
      expect(mockMonaco.languages.registerInlineCompletionsProvider).toHaveBeenCalled();
      expect(disposable).toBeDefined();

      // Test store state manipulation
      const store = useInlineCompletionStore.getState();
      store.setFetching(true);
      expect(useInlineCompletionStore.getState().isFetching).toBe(true);
      store.setLastLatencyMs(142);
      expect(useInlineCompletionStore.getState().lastLatencyMs).toBe(142);

      // Verify disabled case
      useSettingsStore.setState({
        settings: { "editor.inlineCompletionEnabled": "false" },
      });
      const disabledRes = await registeredHandler.provideInlineCompletions({}, {}, {}, {});
      expect(disabledRes).toEqual({ items: [] });
    });
  });
});

