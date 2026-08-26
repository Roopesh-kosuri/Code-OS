import { describe, it, expect, beforeEach, vi } from "vitest";
import React from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { FileExplorer } from "../features/explorer/FileExplorer";
import { useWorkspaceStore } from "../stores/workspaceStore";
import { useEditorStore } from "../stores/editorStore";
import { useBackendStore } from "../stores/backendStore";
import { api } from "../lib/api";

vi.mock("../lib/api", () => ({
  api: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
  },
}));

describe("Phase 1: FileExplorer New File and New Folder In-App", () => {
  const mockWorkspace = {
    path: "/test/workspace",
    name: "test-workspace",
    last_opened_at: "2026-08-26T00:00:00Z",
  };

  const mockTree = {
    name: "test-workspace",
    path: "/test/workspace",
    type: "directory" as const,
    children: [
      {
        name: "src",
        path: "/test/workspace/src",
        type: "directory" as const,
        children: [],
      },
    ],
  };

  beforeEach(() => {
    vi.clearAllMocks();
    useBackendStore.setState({ status: "connected" });
    useWorkspaceStore.setState({
      currentWorkspace: mockWorkspace,
      activeWorkspaces: [mockWorkspace],
      fileTrees: { [mockWorkspace.path]: mockTree },
      fileTree: mockTree,
    });
    useEditorStore.setState({ openFiles: [], activePath: null });
  });

  it("creates file inside folder via in-app dialog and opens editor", async () => {
    vi.mocked(api.post).mockResolvedValueOnce({ status: "created", path: "/test/workspace/src/app.ts" });
    vi.mocked(api.get).mockImplementation(async (url: string) => {
      if (url === "/api/files/read") {
        return { path: "/test/workspace/src/app.ts", content: "", language: "typescript" };
      }
      if (url === "/api/files/tree") {
        return { root: mockTree };
      }
      return {};
    });

    render(<FileExplorer />);

    // Right-click on "src" folder item
    const srcFolder = screen.getByText("src");
    fireEvent.contextMenu(srcFolder, { clientX: 100, clientY: 100 });

    // Click "New File" in context menu
    const newFileMenuItem = screen.getByText("New File");
    fireEvent.click(newFileMenuItem);

    // In-app creation dialog should appear
    expect(screen.getByText("Create New File")).toBeTruthy();
    expect(screen.getByPlaceholderText(/main\.cpp, app\.py/i)).toBeTruthy();

    // Type filename and submit
    const input = screen.getByPlaceholderText(/main\.cpp, app\.py/i);
    fireEvent.change(input, { target: { value: "app.ts" } });
    fireEvent.keyDown(input, { key: "Enter", code: "Enter" });

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith("/api/files/create", expect.objectContaining({
        workspace: "/test/workspace",
        path: expect.stringContaining("app.ts"),
        type: "file",
      }));
    });
  });

  it("blocks creation and displays toast when in Restricted Mode (403)", async () => {
    vi.mocked(api.post).mockRejectedValueOnce({
      status: 403,
      message: "Workspace is in Restricted Mode.",
    });

    render(<FileExplorer />);

    const newFileBtn = screen.getByTitle("New File");
    fireEvent.click(newFileBtn);

    const input = screen.getByPlaceholderText(/main\.cpp, app\.py/i);
    fireEvent.change(input, { target: { value: "restricted_test.ts" } });
    fireEvent.keyDown(input, { key: "Enter", code: "Enter" });

    await waitFor(() => {
      expect(screen.getByText(/Action blocked: Workspace is in Restricted Mode/i)).toBeTruthy();
    });
  });

  it("validates filename and rejects invalid characters client-side", async () => {
    render(<FileExplorer />);

    const newFileBtn = screen.getByTitle("New File");
    fireEvent.click(newFileBtn);

    const input = screen.getByPlaceholderText(/main\.cpp, app\.py/i);
    fireEvent.change(input, { target: { value: "bad*file.ts" } });
    fireEvent.keyDown(input, { key: "Enter", code: "Enter" });

    expect(await screen.findByText(/Filename contains invalid characters/i)).toBeTruthy();
    expect(api.post).not.toHaveBeenCalledWith("/api/files/create", expect.anything());
  });
});
