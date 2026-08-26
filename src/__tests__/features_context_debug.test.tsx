import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { ContextPanel } from "../features/ai/ContextPanel";
import { DebugToolbar } from "../components/debug/DebugToolbar";
import { DebugPanel } from "../components/debug/DebugPanel";
import { debugClient } from "../components/debug/debugClient";
import { useWorkspaceStore } from "../stores/workspaceStore";
import { useEditorStore } from "../stores/editorStore";
import { api } from "../lib/api";

describe("Frontend Context & Debug Suite", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    useWorkspaceStore.setState({
      currentWorkspace: { path: "D:/ws", name: "ws", is_current: true },
    });
    useEditorStore.setState({
      openFiles: [{ path: "D:/ws/app.ts", name: "app.ts", content: "console.log(1)", language: "typescript", dirty: false }],
      activePath: "D:/ws/app.ts",
    });
  });

  describe("<ContextPanel />", () => {
    it("fetches and renders workspace context and dependencies", async () => {
      vi.spyOn(api, "post").mockResolvedValue({
        workspace: "D:/ws",
        active_file: {
          path: "D:/ws/app.ts",
          name: "app.ts",
          content: "console.log(1)",
          selection: null,
        },
        git_status: {
          branch: "main",
          dirty: false,
          staged: [],
          unstaged: [],
        },
        dependencies: [{ name: "react", version: "^18.2.0" }],
        open_tabs: [{ path: "D:/ws/app.ts", name: "app.ts" }],
        readme: "# CODE OS Workspace",
      });

      render(<ContextPanel />);

      await waitFor(() => {
        expect(screen.getAllByText(/Context/i).length).toBeGreaterThanOrEqual(1);
        expect(screen.getByText(/react/i)).toBeDefined();
        expect(screen.getByText(/\^18.2.0/i)).toBeDefined();
      });
    });
  });

  describe("<DebugToolbar /> & <DebugPanel />", () => {
    it("handles debugger actions and renders state updates", () => {
      const commandSpy = vi.spyOn(debugClient, "command").mockImplementation(() => {});

      render(<DebugToolbar />);
      const continueBtn = screen.getByTitle("Continue");
      fireEvent.click(continueBtn);
      expect(commandSpy).toHaveBeenCalledWith("continue");

      const stepOverBtn = screen.getByTitle("Step Over");
      fireEvent.click(stepOverBtn);
      expect(commandSpy).toHaveBeenCalledWith("step_over");

      const stopBtn = screen.getByTitle("Stop Debugging");
      fireEvent.click(stopBtn);
      expect(commandSpy).toHaveBeenCalledWith("stop");

      render(<DebugPanel />);
      expect(screen.getByText("Variables")).toBeDefined();
      expect(screen.getByText("Call Stack")).toBeDefined();
    });

    it("toggles breakpoints and manages subscribers in debugClient", () => {
      debugClient.toggleBreakpoint("app.ts", 42);
      expect(debugClient.snapshot().breakpoints["app.ts"]).toContain(42);

      debugClient.toggleBreakpoint("app.ts", 42);
      expect(debugClient.snapshot().breakpoints["app.ts"]).not.toContain(42);
    });
  });
});
