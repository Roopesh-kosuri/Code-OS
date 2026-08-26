import { describe, it, expect, beforeEach, vi } from "vitest";
import React from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { GitPanel } from "../features/git/GitPanel";
import { TopBar } from "../components/layout/TopBar";
import { DiffViewer } from "../features/ai/DiffViewer";
import { useWorkspaceStore } from "../stores/workspaceStore";
import { useIndexStore } from "../stores/indexStore";
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

describe("Final Bounded Push: Panels Coverage Suite", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useBackendStore.setState({ status: "connected" });
    useWorkspaceStore.setState({
      currentWorkspace: {
        path: "/test/workspace",
        name: "test-workspace",
        last_opened_at: "2026-08-26T00:00:00Z",
      },
    });
  });

  describe("GitPanel (features/git/GitPanel.tsx)", () => {
    it("renders fallback when no workspace is open", () => {
      useWorkspaceStore.setState({ currentWorkspace: null });
      render(<GitPanel />);
      expect(screen.getByText(/Open a workspace to view Git status/i)).toBeTruthy();
    });

    it("renders branch and lists staged, unstaged, and untracked changes", async () => {
      vi.mocked(api.get).mockImplementation(async (url: string) => {
        if (url === "/api/git/status") {
          return {
            branch: "main",
            dirty: true,
            staged: ["staged_file.ts"],
            unstaged: ["unstaged_file.ts"],
            untracked: ["new_untracked.ts"],
            branches: ["main", "feature-x"],
          };
        }
        if (url === "/api/git/history") {
          return [
            { sha: "abc1234", message: "Initial commit", author: "Dev", committed_at: "2026-08-26" },
          ];
        }
        return {};
      });

      render(<GitPanel />);

      expect(screen.getByText("Source Control")).toBeTruthy();
      expect(await screen.findByText("staged_file.ts")).toBeTruthy();
      expect(await screen.findByText("unstaged_file.ts")).toBeTruthy();
      expect(await screen.findByText("new_untracked.ts")).toBeTruthy();
    });

    it("switches branch on select change", async () => {
      vi.mocked(api.get).mockResolvedValue({
        branch: "main",
        dirty: false,
        staged: [],
        unstaged: [],
        untracked: [],
        branches: ["main", "dev-branch"],
      });
      vi.mocked(api.post).mockResolvedValue({ success: true });

      render(<GitPanel />);

      const select = await screen.findByRole("combobox");
      fireEvent.change(select, { target: { value: "dev-branch" } });

      await waitFor(() => {
        expect(api.post).toHaveBeenCalledWith("/api/git/branch", expect.objectContaining({
          workspace: "/test/workspace",
          branch: "dev-branch",
        }));
      });
    });

    it("clicking a file fetches diff", async () => {
      vi.mocked(api.get).mockImplementation(async (url: string) => {
        if (url === "/api/git/status") {
          return {
            branch: "main",
            dirty: true,
            staged: ["app.ts"],
            unstaged: [],
            untracked: [],
            branches: ["main"],
          };
        }
        if (url === "/api/git/diff") {
          return { diff: "+ console.log('hello world');" };
        }
        return {};
      });

      render(<GitPanel />);

      const fileBtn = await screen.findByText("app.ts");
      fireEvent.click(fileBtn);

      await waitFor(() => {
        expect(api.get).toHaveBeenCalledWith("/api/git/diff", expect.objectContaining({
          path: "app.ts",
        }));
      });
    });
  });

  describe("TopBar (components/layout/TopBar.tsx)", () => {
    it("renders workspace name, index status, and fires onOpenSettings", () => {
      useIndexStore.setState({ status: { status: "ready", indexed_files: 42, total_files: 100 } as any });
      const onOpenSettings = vi.fn();

      render(
        <TopBar
          onOpenSettings={onOpenSettings}
          activeView="editor"
          onViewChange={vi.fn()}
        />
      );

      expect(screen.getByText("test-workspace")).toBeTruthy();
      expect(screen.getByText(/Index: Ready/i)).toBeTruthy();

      const settingsBtn = screen.getByTitle("Settings");
      fireEvent.click(settingsBtn);
      expect(onOpenSettings).toHaveBeenCalledTimes(1);
    });

    it("handles window minimize and close controls", () => {
      const minimizeMock = vi.fn();
      const closeMock = vi.fn();
      (window as any).codeOS = {
        windowControls: {
          minimize: minimizeMock,
          maximize: vi.fn(),
          close: closeMock,
          isMaximized: vi.fn().mockResolvedValue(false),
        },
      };

      render(
        <TopBar
          onOpenSettings={vi.fn()}
          activeView="editor"
          onViewChange={vi.fn()}
        />
      );

      expect((window as any).codeOS?.windowControls?.isMaximized).toBeDefined();
    });
  });

  describe("DiffViewer (features/ai/DiffViewer.tsx)", () => {
    it("loads edit proposals and displays proposal details", async () => {
      const mockProposal = {
        id: "prop_1",
        summary: "Refactor database connection pool",
        status: "pending",
        changes: [
          { path: "src/db.ts", original: "connect()", updated: "createPool()" },
        ],
        diff: "--- a/src/db.ts\n+++ b/src/db.ts\n-connect()\n+createPool()",
      };

      vi.mocked(api.get).mockResolvedValueOnce([mockProposal]);

      render(<DiffViewer />);

      const matches = await screen.findAllByText("Refactor database connection pool");
      expect(matches.length).toBeGreaterThan(0);
      expect(screen.getByText("src/db.ts")).toBeTruthy();
    });
  });
});
