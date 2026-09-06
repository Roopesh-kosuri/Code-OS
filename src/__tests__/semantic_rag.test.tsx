import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import { SemanticSearchPanel } from "../features/rag/SemanticSearchPanel";
import { useRAGStore } from "../features/rag/ragStore";
import { useWorkspaceStore } from "../stores/workspaceStore";
import { useEditorStore } from "../stores/editorStore";
import { useTeamStore } from "../features/ai/console/teamStore";
import { TeamChatPanel } from "../features/ai/console/TeamChatPanel";
import { api } from "../lib/api";

vi.mock("../lib/api", () => ({
  api: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
  },
}));

describe("Semantic RAG Frontend Test Suite", () => {
  const mockWorkspace = {
    id: "ws-1",
    path: "D:/PROJECTS/MyProject",
    name: "MyProject",
  };

  beforeEach(() => {
    vi.clearAllMocks();

    act(() => {
      useWorkspaceStore.setState({
        currentWorkspace: mockWorkspace,
        restrictedMode: false,
      });

      useRAGStore.setState({
        indexStatus: {
          indexed_files: 12,
          total_chunks: 48,
          last_indexed_at: "2026-09-06T12:00:00Z",
        },
        searchResults: [],
        searchQuery: "",
        isIndexing: false,
        isSearching: false,
        useRagInChat: true,
        error: null,
      });

      useTeamStore.getState().reset();
      useTeamStore.setState({
        activeJobId: "job-rag-test",
        jobStatus: "running",
      });
    });

    vi.mocked(api.get).mockImplementation(async (url: string) => {
      if (url === "/api/rag/status") {
        return {
          ok: true,
          indexed_files: 12,
          total_chunks: 48,
          last_indexed_at: "2026-09-06T12:00:00Z",
        };
      }
      return {};
    });
  });

  // ── Test 1: Search panel renders ──────────────────────────────────────────
  it("test_search_panel_renders: verifies search input, status badge, and index button render", async () => {
    await act(async () => {
      render(<SemanticSearchPanel />);
    });

    expect(screen.getByTestId("semantic-search-panel")).toBeDefined();
    expect(screen.getByTestId("rag-search-input")).toBeDefined();
    expect(screen.getByTestId("rag-search-btn")).toBeDefined();
    expect(screen.getByTestId("rag-index-btn")).toBeDefined();

    const statusBadge = screen.getByTestId("rag-status-badge");
    expect(statusBadge.textContent).toContain("12 files indexed");
    expect(statusBadge.textContent).toContain("48 chunks");
  });

  // ── Test 2: Search returns results ────────────────────────────────────────
  it("test_search_returns_results: mocks /api/rag/search, submits query, asserts result items, file paths, and score badges", async () => {
    const mockResults = [
      {
        file_path: "src/auth/middleware.py",
        chunk_text: "def auth_middleware(request):\n    verify_jwt_token(request)\n    return next()",
        score: 0.89,
        line_range: "1-45",
        language: "python",
      },
      {
        file_path: "src/security/tokens.py",
        chunk_text: "def verify_jwt_token(token):\n    # decode and validate signature\n    pass",
        score: 0.74,
        line_range: "50-95",
        language: "python",
      },
    ];

    vi.mocked(api.post).mockImplementation(async (url: string) => {
      if (url === "/api/rag/search") {
        return { ok: true, results: mockResults };
      }
      return { ok: true };
    });

    render(<SemanticSearchPanel />);

    const input = screen.getByTestId("rag-search-input");
    fireEvent.change(input, { target: { value: "Where is the auth middleware?" } });

    const searchBtn = screen.getByTestId("rag-search-btn");
    fireEvent.click(searchBtn);

    await waitFor(() => {
      const items = screen.getAllByTestId("rag-result-item");
      expect(items).toHaveLength(2);
    });

    const filePaths = screen.getAllByTestId("rag-file-path");
    expect(filePaths[0].textContent).toBe("src/auth/middleware.py");
    expect(filePaths[1].textContent).toBe("src/security/tokens.py");

    const scoreBadges = screen.getAllByTestId("rag-score-badge");
    expect(scoreBadges[0].textContent).toBe("89%");
    expect(scoreBadges[1].textContent).toBe("74%");

    const lineRanges = screen.getAllByTestId("rag-line-range");
    expect(lineRanges[0].textContent).toBe("L1-45");
  });

  // ── Test 3: Index workspace button works ───────────────────────────────────
  it("test_index_workspace_button_works: clicks Index Workspace, calls /api/rag/index-workspace, updates status badge", async () => {
    vi.mocked(api.post).mockImplementation(async (url: string) => {
      if (url === "/api/rag/index-workspace") {
        return {
          ok: true,
          indexed_files: 55,
          total_chunks: 210,
          last_indexed_at: "2026-09-06T14:30:00Z",
        };
      }
      return { ok: true };
    });

    render(<SemanticSearchPanel />);

    const indexBtn = screen.getByTestId("rag-index-btn");
    fireEvent.click(indexBtn);

    await waitFor(() => {
      const statusBadge = screen.getByTestId("rag-status-badge");
      expect(statusBadge.textContent).toContain("55 files indexed");
      expect(statusBadge.textContent).toContain("210 chunks");
    });

    expect(api.post).toHaveBeenCalledWith("/api/rag/index-workspace", {
      workspace: "D:/PROJECTS/MyProject",
    });
  });

  // ── Test 4: RAG toggle in chat input ──────────────────────────────────────
  it("test_rag_toggle_in_chat_input: tests the Use RAG toggle and badge in TeamChatPanel", async () => {
    render(<TeamChatPanel />);

    // By default for Agent mode, RAG is ON
    const toggle = screen.getByTestId("rag-chat-toggle");
    expect(toggle).toBeDefined();
    expect(toggle.textContent).toContain("RAG: ON");

    // Context badge is visible
    const badge = screen.getByTestId("rag-context-badge");
    expect(badge).toBeDefined();
    expect(badge.textContent).toContain("relevant files from codebase");

    // Clicking toggle turns it OFF
    fireEvent.click(toggle);

    await waitFor(() => {
      expect(screen.getByTestId("rag-chat-toggle").textContent).toContain("RAG: OFF");
      expect(screen.queryByTestId("rag-context-badge")).toBeNull();
    });

    // Clicking toggle turns it back ON
    fireEvent.click(screen.getByTestId("rag-chat-toggle"));
    await waitFor(() => {
      expect(screen.getByTestId("rag-chat-toggle").textContent).toContain("RAG: ON");
      expect(screen.getByTestId("rag-context-badge")).toBeDefined();
    });
  });

  // ── Test 5: Click result opens file in editor ──────────────────────────────
  it("test_click_result_opens_file_in_editor: clicking a result invokes useEditorStore.openFile", async () => {
    const openFileSpy = vi.fn().mockResolvedValue(undefined);
    useEditorStore.setState({ openFile: openFileSpy });

    act(() => {
      useRAGStore.setState({
        searchResults: [
          {
            file_path: "src/auth/middleware.py",
            chunk_text: "def auth_middleware(): pass",
            score: 0.95,
            line_range: "1-50",
            language: "python",
          },
        ],
      });
    });

    render(<SemanticSearchPanel />);

    const resultItem = screen.getByTestId("rag-result-item");
    fireEvent.click(resultItem);

    await waitFor(() => {
      expect(openFileSpy).toHaveBeenCalledWith("src/auth/middleware.py");
    });
  });
});
