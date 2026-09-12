import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, act, waitFor } from "@testing-library/react";

import { AIChatPanel } from "../features/ai/AIChatPanel";
import { EditorWorkspace } from "../features/editor/EditorWorkspace";
import { useEditorStore } from "../stores/editorStore";
import { useAIStore } from "../stores/aiStore";
import { useWorkspaceStore } from "../stores/workspaceStore";
import { api } from "../lib/api";

// Mock Monaco Editor
vi.mock("@monaco-editor/react", () => ({
  default: ({ value }: any) => (
    <div data-testid="mock-monaco-editor">
      <pre>{value}</pre>
    </div>
  ),
  DiffEditor: ({ original, modified }: any) => (
    <div data-testid="mock-diff-editor">
      <div data-testid="diff-original">{original}</div>
      <div data-testid="diff-modified">{modified}</div>
    </div>
  ),
  loader: {
    config: vi.fn(),
    init: vi.fn(),
  },
}));

describe("Phase 6.5: Editor & Approval UX Polish Regression Tests", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    localStorage.clear();
    useEditorStore.setState({
      openFiles: [],
      activePath: null,
      splitPath: null,
    });
    useAIStore.setState({
      messages: [],
      streaming: false,
    });
    useWorkspaceStore.setState({
      currentWorkspace: {
        path: "D:/test-workspace",
        name: "test-workspace",
        last_opened_at: new Date().toISOString(),
      },
    });
    vi.spyOn(api, "get").mockResolvedValue({ content: "disk content", language: "python", diff: "" });
    vi.spyOn(api, "post").mockResolvedValue({});
  });

  it("test_diff_link_opens_monaco_diff", async () => {
    // Populate AI store with an assistant message containing:
    // 1. An approved edit receipt card
    // 2. A turn checkpoint chip
    const testMessage = {
      role: "assistant" as const,
      content: "I have updated the file.",
      commands: [
        {
          command: "edit src/main.cpp",
          output: "Successfully applied changes",
          exit_code: 0,
          success: true,
          original: "int main() { return 1; }",
          updated: "int main() { return 0; }",
        },
      ],
      checkpoint: {
        turn_number: 1,
        commit_hash: "a1b2c3d4e5f6",
        touched_files: ["src/main.cpp"],
      },
    };

    useAIStore.setState({
      messages: [testMessage as any],
    });

    await act(async () => {
      render(<AIChatPanel />);
    });

    // 1. Verify Diff link exists on the Approved edit card
    const diffLink = screen.getByTestId("diff-link");
    expect(diffLink).toBeDefined();

    // 2. Click Diff on the approval card
    await act(async () => {
      fireEvent.click(diffLink);
    });

    // 3. Verify Monaco Diff modal opens and displays Monaco DiffEditor
    const modal = screen.getByTestId("monaco-diff-modal");
    expect(modal).toBeDefined();
    expect(screen.getByTestId("monaco-diff-editor")).toBeDefined();
    expect(screen.getByTestId("diff-original").textContent).toContain("int main() { return 1; }");
    expect(screen.getByTestId("diff-modified").textContent).toContain("int main() { return 0; }");

    // 4. Close the modal
    const closeBtn = screen.getByTestId("close-diff-modal");
    await act(async () => {
      fireEvent.click(closeBtn);
    });
    expect(screen.queryByTestId("monaco-diff-modal")).toBeNull();

    // 5. Verify Diff button on Checkpoint chip works
    const cpDiffBtn = screen.getByTestId("checkpoint-diff-btn");
    expect(cpDiffBtn).toBeDefined();

    await act(async () => {
      fireEvent.click(cpDiffBtn);
    });

    // Verify modal reopened for checkpoint diff
    expect(screen.getByTestId("monaco-diff-modal")).toBeDefined();
    expect(screen.getByTestId("monaco-diff-editor")).toBeDefined();
  });

  it("test_open_tab_refreshes_on_applied_edit", async () => {
    // Open a file tab with clean state (not dirty)
    useEditorStore.setState({
      openFiles: [
        {
          path: "D:/test-workspace/src/server.py",
          name: "server.py",
          content: "def run(): return 'v1'",
          language: "python",
          dirty: false,
        },
      ],
      activePath: "D:/test-workspace/src/server.py",
    });

    // Dispatch a file-watcher / file-changed event for this file with new content
    await act(async () => {
      window.dispatchEvent(
        new CustomEvent("code-os:file-watcher-event", {
          detail: {
            path: "D:/test-workspace/src/server.py",
            content: "def run(): return 'v2-live'",
          },
        })
      );
    });

    // The open tab's content must have automatically updated to the new content
    const tab = useEditorStore.getState().openFiles.find((f) => f.name === "server.py");
    expect(tab).toBeDefined();
    expect(tab?.content).toBe("def run(): return 'v2-live'");
    expect(tab?.dirty).toBe(false);
    expect(tab?.hasDiskConflict).toBeFalsy();
  });

  it("test_dirty_tab_not_clobbered_shows_indicator", async () => {
    // 1. User has unsaved edits in an open tab (dirty: true)
    useEditorStore.setState({
      openFiles: [
        {
          path: "D:/test-workspace/src/config.py",
          name: "config.py",
          content: "MY_UNSAVED_LOCAL_BUFFER = True",
          language: "python",
          dirty: true,
        },
      ],
      activePath: "D:/test-workspace/src/config.py",
    });

    // 2. An external edit or watcher event reports new content on disk
    await act(async () => {
      window.dispatchEvent(
        new CustomEvent("code-os:file-changed", {
          detail: {
            path: "D:/test-workspace/src/config.py",
            content: "EXTERNAL_DISK_CHANGES = 42",
          },
        })
      );
    });

    // 3. User's buffer must NOT be clobbered!
    const dirtyTab = useEditorStore.getState().openFiles.find((f) => f.name === "config.py");
    expect(dirtyTab).toBeDefined();
    expect(dirtyTab?.content).toBe("MY_UNSAVED_LOCAL_BUFFER = True");
    expect(dirtyTab?.dirty).toBe(true);
    expect(dirtyTab?.hasDiskConflict).toBe(true);
    expect(dirtyTab?.diskContent).toBe("EXTERNAL_DISK_CHANGES = 42");

    // 4. Render EditorWorkspace: the conflict banner and actions must be displayed
    await act(async () => {
      render(<EditorWorkspace />);
    });

    const indicator = screen.getByTestId("disk-conflict-indicator");
    expect(indicator).toBeDefined();
    expect(indicator.textContent).toContain("File changed on disk. You have unsaved changes.");

    const reloadBtn = screen.getByTestId("reload-disk-btn");
    const keepMineBtn = screen.getByTestId("keep-mine-btn");
    expect(reloadBtn).toBeDefined();
    expect(keepMineBtn).toBeDefined();

    // 5. Test "Keep mine" action preserves user buffer and clears banner
    await act(async () => {
      fireEvent.click(keepMineBtn);
    });

    expect(useEditorStore.getState().openFiles[0].content).toBe("MY_UNSAVED_LOCAL_BUFFER = True");
    expect(useEditorStore.getState().openFiles[0].hasDiskConflict).toBeFalsy();

    // 6. Test "Reload" action restores disk content and clears dirty flag
    await act(async () => {
      // Re-trigger conflict
      await useEditorStore.getState().handleDiskFileChange("D:/test-workspace/src/config.py", "DISK_CODE_RELOADED");
    });
    expect(useEditorStore.getState().openFiles[0].hasDiskConflict).toBe(true);

    await act(async () => {
      await useEditorStore.getState().reloadFromDisk("D:/test-workspace/src/config.py");
    });

    const reloadedTab = useEditorStore.getState().openFiles[0];
    expect(reloadedTab.content).toBe("DISK_CODE_RELOADED");
    expect(reloadedTab.dirty).toBe(false);
    expect(reloadedTab.hasDiskConflict).toBe(false);
  });
});
