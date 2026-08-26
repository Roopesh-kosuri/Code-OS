import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { GitPanel } from "../components/git/GitPanel";
import { FileExplorer } from "../features/explorer/FileExplorer";
import { CodeVerifierPanel } from "../features/verifier/CodeVerifierPanel";
import { useWorkspaceStore } from "../stores/workspaceStore";
import { useEditorStore } from "../stores/editorStore";
import { useAIStore } from "../stores/aiStore";
import { api } from "../lib/api";

describe("D4 Component Coverage Suite (GitPanel, FileExplorer, CodeVerifierPanel)", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.spyOn(api, "get").mockResolvedValue({ content: "" });

    const mockTree = {
      name: "test_workspace",
      path: "D:/ws_test",
      type: "directory" as const,
      is_dir: true,
      children: [
        {
          name: "src",
          path: "D:/ws_test/src",
          type: "directory" as const,
          is_dir: true,
          children: [
            { name: "app.ts", path: "D:/ws_test/src/app.ts", type: "file" as const, is_dir: false },
          ],
        },
        { name: "README.md", path: "D:/ws_test/README.md", type: "file" as const, is_dir: false },
      ],
    };

    useWorkspaceStore.setState({
      currentWorkspace: { path: "D:/ws_test", name: "test_workspace", is_current: true },
      activeWorkspaces: [{ path: "D:/ws_test", name: "test_workspace", is_current: true }],
      fileTree: mockTree,
      fileTrees: { "D:/ws_test": mockTree },
      restrictedMode: false,
    });

    useEditorStore.setState({
      activePath: null,
      openPaths: [],
      files: {},
    });

    useAIStore.setState({
      preset: "ollama",
      model: "qwen2.5-coder:7b",
      models: [{ name: "qwen2.5-coder:7b", provider: "ollama" }],
    });
  });

  describe("<GitPanel /> commit and staging interactions", () => {
    it("renders git status and handles commit execution", async () => {
      vi.spyOn(api, "get").mockImplementation((url) => {
        if (String(url).includes("/api/git/status")) {
          return Promise.resolve({
            branch: "feature/d4",
            clean: false,
            staged: ["src/app.ts"],
            unstaged: ["README.md"],
            untracked: [],
          });
        }
        if (String(url).includes("/api/git/history")) {
          return Promise.resolve([
            { sha: "abcdef1", message: "feat: initial commit", author: "Auditor", committed_at: "2026-08-26" },
          ]);
        }
        return Promise.resolve({});
      });

      const commitSpy = vi.spyOn(api, "post").mockResolvedValue({ status: "committed" });

      render(<GitPanel />);

      await waitFor(() => {
        expect(screen.getByText(/Branch: feature\/d4/i)).toBeDefined();
        expect(screen.getByText("src/app.ts")).toBeDefined();
      });

      // Select file via checkbox
      const checkboxes = screen.getAllByRole("checkbox");
      fireEvent.click(checkboxes[0]);

      // Type commit message
      const msgInput = screen.getByPlaceholderText("Commit message");
      fireEvent.change(msgInput, { target: { value: "feat: add D4 test coverage" } });

      // Click Commit button
      const commitBtn = screen.getByRole("button", { name: /commit/i });
      fireEvent.click(commitBtn);

      await waitFor(() => {
        expect(commitSpy).toHaveBeenCalledWith("/api/git/commit", expect.objectContaining({
          workspace: "D:/ws_test",
          message: "feat: add D4 test coverage",
          files: expect.arrayContaining(["src/app.ts"]),
        }));
      });
    });

    it("displays error notice when git repository is unavailable", async () => {
      vi.spyOn(api, "get").mockRejectedValue(new Error("fatal: not a git repository"));

      render(<GitPanel />);

      await waitFor(() => {
        expect(screen.getByText(/fatal: not a git repository/i)).toBeDefined();
      });
    });
  });

  describe("<FileExplorer /> navigation and actions", () => {
    it("renders file hierarchy and opens file on click", async () => {
      const openFileSpy = vi.spyOn(useEditorStore.getState(), "openFile").mockResolvedValue();

      render(<FileExplorer />);

      expect(screen.getByText("README.md")).toBeDefined();

      const fileItem = screen.getByText("README.md");
      fireEvent.click(fileItem);

      await waitFor(() => {
        expect(openFileSpy).toHaveBeenCalledWith("D:/ws_test/README.md");
      });
    });

    it("triggers file creation flow when New File button clicked", async () => {
      vi.spyOn(window, "prompt").mockReturnValue("utils.ts");
      const createSpy = vi.spyOn(api, "post").mockResolvedValue({ status: "created" });

      render(<FileExplorer />);

      const newFileBtn = screen.getByTitle("New File");
      expect(newFileBtn).toBeDefined();
      fireEvent.click(newFileBtn);

      await waitFor(() => {
        expect(createSpy).toHaveBeenCalledWith("/api/files/create", expect.objectContaining({
          workspace: "D:/ws_test",
          path: expect.stringContaining("utils.ts"),
          type: "file",
        }));
      });
    });
  });

  describe("<CodeVerifierPanel /> audit execution and reporting", () => {
    it("runs security audit and displays findings report", async () => {
      const mockReport = {
        id: "audit-001",
        timestamp: "2026-08-26T21:00:00Z",
        score: 85,
        total_files_scanned: 12,
        duration_seconds: 1.4,
        findings: [
          {
            id: "f-1",
            severity: "high",
            file: "src/auth.ts",
            line: 42,
            message: "Missing token validation on websocket upgrade",
            title: "Auth Bypass",
            remediation: "Verify token in query parameters before accepting upgrade",
          },
        ],
        severity_counts: { critical: 0, high: 1, medium: 0, low: 0 },
      };

      const auditSpy = vi.spyOn(api, "post").mockResolvedValue(mockReport);

      render(<CodeVerifierPanel />);

      const scanBtn = screen.getByRole("button", { name: /run security audit now/i });
      fireEvent.click(scanBtn);

      await waitFor(() => {
        expect(auditSpy).toHaveBeenCalledWith("/api/agents/audit", expect.objectContaining({
          workspace: "D:/ws_test",
        }));
        expect(screen.getByText(/Security Score/i)).toBeDefined();
        expect(screen.getByText(/85\/100/)).toBeDefined();
      });
    });

    it("handles audit scan failure gracefully", async () => {
      vi.spyOn(api, "post").mockRejectedValue(new Error("Audit daemon offline"));

      render(<CodeVerifierPanel />);

      const scanBtn = screen.getByRole("button", { name: /run security audit now/i });
      fireEvent.click(scanBtn);

      await waitFor(() => {
        expect(screen.getByText(/Audit daemon offline/i)).toBeDefined();
      });
    });
  });
});



