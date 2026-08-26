import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { SearchPanel } from "../features/search/SearchPanel";
import { GitPanel } from "../features/git/GitPanel";
import { FileExplorer } from "../features/explorer/FileExplorer";
import { useInlineCompletionStore } from "../features/editor/inlineCompletionProvider";
import { useWorkspaceStore } from "../stores/workspaceStore";
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

describe("Frontend Advanced Panels (Search, Git, Explorer, Completion)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    const mockTree = {
      name: "ws",
      path: "D:/ws",
      type: "directory" as const,
      is_dir: true,
      children: [
        { name: "src", path: "D:/ws/src", type: "directory" as const, is_dir: true, children: [] },
        { name: "index.ts", path: "D:/ws/index.ts", type: "file" as const, is_dir: false },
      ],
    };

    useWorkspaceStore.setState({
      currentWorkspace: { path: "D:/ws", name: "ws", is_current: true },
      activeWorkspaces: [{ path: "D:/ws", name: "ws", is_current: true }],
      fileTree: mockTree,
      fileTrees: { "D:/ws": mockTree },
    });
    useBackendStore.setState({ status: "connected" });
  });

  describe("<SearchPanel />", () => {
    it("renders search input and triggers search query", async () => {
      vi.mocked(api.get).mockResolvedValue([
        { path: "D:/ws/index.ts", line: 10, column: 1, preview: "const app = express();" },
      ]);

      render(<SearchPanel />);
      const searchInput = screen.getByTestId("search-query-input");
      fireEvent.change(searchInput, { target: { value: "express" } });
      fireEvent.click(screen.getByTestId("search-submit-btn"));

      await waitFor(() => {
        expect(api.get).toHaveBeenCalledWith("/api/search/text", expect.objectContaining({ query: "express" }));
      });
      expect(await screen.findByText("index.ts")).toBeTruthy();
    });
  });

  describe("<GitPanel />", () => {
    it("renders git panel controls and status", async () => {
      vi.spyOn(api, "get").mockImplementation((url) => {
        if (String(url).includes("/api/git/status")) {
          return Promise.resolve({
            branch: "main",
            clean: false,
            staged: ["src/app.ts"],
            unstaged: ["README.md"],
            untracked: [],
          });
        }
        if (String(url).includes("/api/git/history")) {
          return Promise.resolve([
            { sha: "abc1234", message: "Initial commit", author: "Dev", committed_at: "2026-08-26" },
          ]);
        }
        return Promise.resolve({});
      });

      render(<GitPanel />);

      await waitFor(() => {
        expect(screen.getByText(/SOURCE CONTROL/i)).toBeDefined();
      });
    });
  });

  describe("<FileExplorer />", () => {
    it("renders workspace file tree hierarchy", () => {
      render(<FileExplorer />);
      expect(screen.getAllByText("ws").length).toBeGreaterThanOrEqual(1);
      expect(screen.getByText("index.ts")).toBeDefined();
    });
  });

  describe("useInlineCompletionStore", () => {
    it("updates fetching state and latency measurement", () => {
      const store = useInlineCompletionStore.getState();
      store.setFetching(true);
      expect(useInlineCompletionStore.getState().isFetching).toBe(true);

      store.setLastLatencyMs(142);
      expect(useInlineCompletionStore.getState().lastLatencyMs).toBe(142);

      store.setFetching(false);
      expect(useInlineCompletionStore.getState().isFetching).toBe(false);
    });
  });
});
