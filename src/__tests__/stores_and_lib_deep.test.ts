import { describe, it, expect, vi, beforeEach } from "vitest";
import { useRunStore } from "../stores/runStore";
import { useEditorStore } from "../stores/editorStore";
import { useWorkspaceStore } from "../stores/workspaceStore";
import { getUserCustomModels, PRESET_MODELS, isReasoningModel, getDefaultVisionModel } from "../lib/models";
import { api } from "../lib/api";

describe("Frontend Deep Stores & Lib Suite", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    useWorkspaceStore.setState({
      currentWorkspace: { path: "D:/ws", name: "ws", is_current: true },
    });
    useEditorStore.setState({
      openFiles: [],
      activePath: null,
      splitPath: null,
      fontSize: 13,
      tabSize: 2,
    });
    useRunStore.setState({
      status: "idle",
      logs: [],
      toolchains: [],
      activeFilePath: null,
    });
  });

  describe("useRunStore behavioral tests", () => {
    it("fetches available toolchains and manages run status", async () => {
      vi.spyOn(api.terminal, "getToolchains").mockResolvedValue({
        toolchains: [
          { language: "python", name: "Python 3.11", executable_path: "python.exe", available: true },
        ],
      });

      await useRunStore.getState().fetchToolchains();
      expect(useRunStore.getState().toolchains.length).toBe(1);
      expect(useRunStore.getState().toolchains[0].language).toBe("python");

      useRunStore.setState({ logs: [{ id: "l1", text: "Compiling...", type: "stdout", timestamp: Date.now() }] });
      expect(useRunStore.getState().logs.length).toBe(1);

      useRunStore.getState().clearLogs();
      expect(useRunStore.getState().logs.length).toBe(0);
    });

    it("executes runFile and streams logs", async () => {
      vi.spyOn(api, "streamSSE").mockImplementation(async (url, body, onEvent) => {
        onEvent("status", { status: "running", command: "python main.py" });
        onEvent("log", { text: "Hello World\n", type: "stdout" });
        onEvent("exit", { exit_code: 0, duration_ms: 120 });
        return Promise.resolve();
      });

      await useRunStore.getState().runFile("D:/ws", "main.py");
      expect(useRunStore.getState().status).toBe("completed");
      expect(useRunStore.getState().logs.length).toBeGreaterThanOrEqual(1);
    });
  });

  describe("useEditorStore extended actions", () => {
    it("handles font size, tab size, split path, and batch close", async () => {
      vi.spyOn(api, "post").mockResolvedValue({});
      const editor = useEditorStore.getState();

      await editor.setEditorSetting({ fontSize: 16, tabSize: 4 });
      expect(useEditorStore.getState().fontSize).toBe(16);
      expect(useEditorStore.getState().tabSize).toBe(4);

      editor.toggleSplit("D:/ws/secondary.ts");
      expect(useEditorStore.getState().splitPath).toBe("D:/ws/secondary.ts");

      editor.toggleSplit(null);
      expect(useEditorStore.getState().splitPath).toBeNull();
    });
  });

  describe("models.ts utility functions", () => {
    it("classifies reasoning and vision models correctly", () => {
      expect(isReasoningModel("deepseek-r1:14b")).toBe(true);
      expect(isReasoningModel("o1-preview")).toBe(true);
      expect(isReasoningModel("gpt-4o")).toBe(false);

      expect(getDefaultVisionModel("ollama")).toBe("llama3.2-vision");
      expect(getDefaultVisionModel("groq")).toBe("llama-3.2-11b-vision-preview");
      expect(getDefaultVisionModel("openai")).toBe("gpt-4o-mini");
    });

    it("loads and persists user custom models via localStorage", () => {
      localStorage.setItem(
        "code_os_user_custom_models",
        JSON.stringify({ ollama: ["my-custom-qwen:14b"] })
      );

      const customModels = getUserCustomModels("ollama");
      expect(customModels).toContain("my-custom-qwen:14b");
    });
  });
});
