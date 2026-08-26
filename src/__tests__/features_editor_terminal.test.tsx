import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { OpenFolderModal } from "../components/workspace/OpenFolderModal";
import { EditorWorkspace } from "../features/editor/EditorWorkspace";
import { TerminalPanel } from "../features/terminal/TerminalPanel";
import { useWorkspaceStore } from "../stores/workspaceStore";
import { useEditorStore } from "../stores/editorStore";
import { useRunStore } from "../stores/runStore";
import { api } from "../lib/api";

describe("Frontend Editor, Workspace & Terminal Panels", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.spyOn(api, "get").mockImplementation((url) => {
      if (String(url).includes("/api/workspaces/recent")) {
        return Promise.resolve([{ path: "D:/recent", name: "recent", is_current: false }]);
      }
      return Promise.resolve([]);
    });

    useWorkspaceStore.setState({
      currentWorkspace: { path: "D:/ws", name: "ws", is_current: true },
      recentWorkspaces: [{ path: "D:/recent", name: "recent", is_current: false }],
      loading: false,
    });
    useEditorStore.setState({
      openFiles: [
        { path: "D:/ws/calc.py", name: "calc.py", content: "def add(a, b): return a + b", language: "python", dirty: false },
        { path: "D:/ws/app.ts", name: "app.ts", content: "console.log('hi');", language: "typescript", dirty: true },
      ],
      activePath: "D:/ws/calc.py",
      splitPath: null,
    });
    useRunStore.setState({
      status: "idle",
      logs: [],
    });
  });

  describe("<OpenFolderModal />", () => {
    it("renders folder selection path input and recent workspaces", () => {
      const handleClose = vi.fn();
      render(<OpenFolderModal onClose={handleClose} />);

      expect(screen.getAllByText(/Open Folder/i).length).toBeGreaterThanOrEqual(1);
      expect(screen.getByText("recent")).toBeDefined();
    });
  });

  describe("<EditorWorkspace />", () => {
    it("renders open file tabs and active editor content", () => {
      render(<EditorWorkspace />);
      expect(screen.getAllByText("calc.py").length).toBeGreaterThanOrEqual(1);
      expect(screen.getAllByText("app.ts").length).toBeGreaterThanOrEqual(1);
    });
  });

  describe("<TerminalPanel />", () => {
    it("renders terminal panel container and controls", () => {
      render(<TerminalPanel />);
      expect(screen.getByText("TERMINAL")).toBeDefined();
      expect(screen.getByText("#1")).toBeDefined();
    });
  });
});
