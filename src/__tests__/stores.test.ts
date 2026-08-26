import { describe, it, expect, vi, beforeEach } from "vitest";
import { useWorkspaceStore } from "../stores/workspaceStore";
import { useEditorStore } from "../stores/editorStore";
import { useBackendStore } from "../stores/backendStore";
import { useRunStore } from "../stores/runStore";
import { useSettingsStore } from "../stores/settingsStore";
import { useAIStore } from "../stores/aiStore";
import { useIndexStore } from "../stores/indexStore";
import { api } from "../lib/api";

describe("Frontend Zustand Stores", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  describe("useWorkspaceStore", () => {
    it("manages workspace trust and restricted mode", async () => {
      vi.spyOn(api, "get").mockResolvedValue({ workspace: "D:/trusted", trusted: true });
      vi.spyOn(api, "post").mockResolvedValue({ workspace: "D:/trusted", trusted: true });

      const store = useWorkspaceStore.getState();
      const isTrusted = await store.checkWorkspaceTrust("D:/trusted");
      expect(isTrusted).toBe(true);
      expect(useWorkspaceStore.getState().trustedWorkspaces["D:/trusted"]).toBe(true);

      store.setRestrictedMode(true);
      expect(useWorkspaceStore.getState().restrictedMode).toBe(true);
    });

    it("opens and completes workspace load", async () => {
      const mockWs = { path: "D:/my-project", name: "my-project", is_current: true };
      const mockTree = { name: "my-project", path: "D:/my-project", is_dir: true, children: [] };
      vi.spyOn(api, "post").mockResolvedValue(mockWs);
      vi.spyOn(api, "get").mockResolvedValue(mockTree);

      const store = useWorkspaceStore.getState();
      await store.completeWorkspaceOpen("D:/my-project");

      expect(useWorkspaceStore.getState().currentWorkspace?.path).toBe("D:/my-project");

      store.closeWorkspace("D:/my-project");
      expect(useWorkspaceStore.getState().currentWorkspace).toBeNull();
    });
  });

  describe("useEditorStore", () => {
    it("opens, updates, saves, and closes tabs", async () => {
      useWorkspaceStore.setState({ currentWorkspace: { path: "D:/ws", name: "ws", is_current: true } });
      vi.spyOn(api, "get").mockResolvedValue({ path: "calc.py", content: "def add(): pass", language: "python" });
      vi.spyOn(api, "post").mockResolvedValue({ success: true });
      useEditorStore.setState({ autoSave: false });

      const store = useEditorStore.getState();
      await store.openFile("calc.py");

      expect(useEditorStore.getState().openFiles.length).toBe(1);
      expect(useEditorStore.getState().activePath).toBe("calc.py");

      await store.updateContent("calc.py", "def add(): return 1 + 2");
      expect(useEditorStore.getState().openFiles[0].content).toBe("def add(): return 1 + 2");
      expect(useEditorStore.getState().openFiles[0].dirty).toBe(true);

      store.setCursorPosition({ line: 10, col: 5 });
      expect(useEditorStore.getState().cursorPosition).toEqual({ line: 10, col: 5 });

      store.setMarkerStats({ errors: 1, warnings: 2 });
      expect(useEditorStore.getState().markerStats).toEqual({ errors: 1, warnings: 2 });

      store.closeFile("calc.py");
      expect(useEditorStore.getState().openFiles.length).toBe(0);
      expect(useEditorStore.getState().activePath).toBeNull();
    });

    it("toggles split view", () => {
      const store = useEditorStore.getState();
      store.toggleSplit("test.py");
      expect(useEditorStore.getState().splitPath).toBe("test.py");
      store.toggleSplit(null);
      expect(useEditorStore.getState().splitPath).toBeNull();
    });
  });

  describe("useBackendStore", () => {
    it("handles success and failure status transitions", () => {
      const store = useBackendStore.getState();
      store.recordSuccess();
      expect(useBackendStore.getState().status).toBe("connected");
      expect(useBackendStore.getState().retryCount).toBe(0);
      expect(useBackendStore.getState().errorMessage).toBeNull();

      store.recordFailure(new Error("Connection refused"));
      expect(useBackendStore.getState().status).toBe("disconnected");
      expect(useBackendStore.getState().retryCount).toBeGreaterThanOrEqual(1);
    });
  });

  describe("useRunStore", () => {
    it("clears logs and manages execution lifecycle", () => {
      const store = useRunStore.getState();
      store.clearLogs();
      expect(useRunStore.getState().logs).toEqual([]);
      expect(useRunStore.getState().status).toBe("idle");
    });
  });

  describe("useAIStore", () => {
    it("manages preset selection, model, visionModel, baseUrl, and agent mode", () => {
      const store = useAIStore.getState();
      store.setPreset("ollama");
      expect(useAIStore.getState().preset).toBe("ollama");
      expect(useAIStore.getState().provider).toBe("ollama");

      store.setModel("qwen2.5-coder:7b");
      expect(useAIStore.getState().model).toBe("qwen2.5-coder:7b");

      store.setVisionModel("llama3.2-vision");
      expect(useAIStore.getState().visionModel).toBe("llama3.2-vision");

      store.setBaseUrl("http://127.0.0.1:11434");
      expect(useAIStore.getState().baseUrl).toBe("http://127.0.0.1:11434");

      store.setAgentMode(true);
      expect(useAIStore.getState().agentMode).toBe(true);

      store.clearAgentState();
      expect(useAIStore.getState().agentStatus).toBeNull();
      expect(useAIStore.getState().pendingApproval).toBeNull();
    });
  });

  describe("useSettingsStore & useIndexStore", () => {
    it("updates settings and indexing state", async () => {
      vi.spyOn(api, "post").mockResolvedValue({ success: true });
      vi.spyOn(api, "get").mockResolvedValue([{ key: "theme", value: "dark" }]);

      const settings = useSettingsStore.getState();
      await settings.save("theme", "dark");
      expect(useSettingsStore.getState().settings["theme"]).toBe("dark");

      useBackendStore.setState({ status: "connected" });
      useWorkspaceStore.setState({ currentWorkspace: { path: "D:/ws", name: "ws", is_current: true } });
      vi.spyOn(api, "get").mockResolvedValue({ status: "ready", total_files: 42 });

      const idx = useIndexStore.getState();
      await idx.refresh();
      expect(useIndexStore.getState().status?.total_files).toBe(42);
    });
  });
});
