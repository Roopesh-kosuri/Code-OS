import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { AppShell } from "../components/layout/AppShell";
import { GitAutopilotModal } from "../features/git/GitAutopilotModal";
import { useGitAutopilotStore } from "../features/git/gitAutopilotStore";
import { useWorkspaceStore } from "../stores/workspaceStore";
import { useCostStore } from "../stores/costStore";
import { api } from "../lib/api";

// Mock API
vi.mock("../lib/api", () => ({
  api: {
    get: vi.fn(),
    put: vi.fn(),
    post: vi.fn(),
    delete: vi.fn(),
  },
}));

describe("Git Autopilot Frontend Test Suite", () => {
  const mockWorkspace = { path: "D:/PROJECTS/TestRepo", name: "TestRepo" };

  beforeEach(() => {
    vi.clearAllMocks();

    useWorkspaceStore.setState({
      currentWorkspace: mockWorkspace,
      restrictedMode: false,
    });

    useCostStore.setState({
      budget: {
        daily_limit_usd: 5.0,
        session_limit_usd: null,
        auto_downgrade_at_percent: 90,
        hard_stop_at_percent: 100,
        downgrade_model: "groq/llama-3.3-70b",
        today_spend_usd: 0.5,
        usage_percent: 10,
        status: "none",
        ok: true,
      },
      showTopBarPill: true,
    });

    useGitAutopilotStore.setState({
      isOpen: false,
      analysis: null,
      commitMessage: "",
      prTitle: "",
      prBody: "",
      branchName: "main",
      hasGithubToken: true,
      tokenInput: "",
      isTokenPromptOpen: false,
      isAnalyzing: false,
      isGeneratingCommit: false,
      isGeneratingPr: false,
      isCreatingBranch: false,
      isCommitting: false,
      isPushing: false,
      isCreatingPr: false,
      lastCommitHash: null,
      lastPrUrl: null,
      error: null,
      successMessage: null,
    });

    // Default API mock responses
    (api.get as any).mockImplementation((url: string) => {
      if (url.includes("/api/git-autopilot/github-token")) {
        return Promise.resolve({ has_token: true });
      }
      if (url.includes("/api/cost/budget")) {
        return Promise.resolve({
          daily_limit_usd: 5.0,
          today_spend_usd: 0.5,
          usage_percent: 10,
          status: "none",
          ok: true,
        });
      }
      return Promise.resolve({});
    });

    (api.post as any).mockImplementation((url: string) => {
      if (url.includes("/api/git-autopilot/analyze")) {
        return Promise.resolve({
          is_git_repo: true,
          current_branch: "feat/autopilot",
          files: [
            { path: "src/feature.ts", status: "M", category: "feat", additions: 25, deletions: 5 },
            { path: "src/fix.ts", status: "M", category: "fix", additions: 10, deletions: 2 },
            { path: "src/__tests__/test.ts", status: "A", category: "test", additions: 40, deletions: 0 },
            { path: "README.md", status: "M", category: "docs", additions: 5, deletions: 1 },
          ],
          summary: {
            total_files: 4,
            additions: 80,
            deletions: 8,
            by_category: { feat: 1, fix: 1, test: 1, docs: 1 },
          },
          raw_diff_snippet: "mock diff",
        });
      }
      if (url.includes("/api/git-autopilot/generate-commit")) {
        return Promise.resolve({
          commit_message: "feat(core): implement git autopilot workflow",
          fallback_used: false,
        });
      }
      if (url.includes("/api/git-autopilot/generate-pr")) {
        return Promise.resolve({
          title: "feat(core): implement git autopilot workflow",
          body: "## Summary\nAutomated Git Autopilot pipeline.\n\n## Changes\n- Added git autopilot\n\n## Testing\n- Unit tests passing",
        });
      }
      if (url.includes("/api/git-autopilot/commit")) {
        return Promise.resolve({
          success: true,
          commit_hash: "a1b2c3d4e5f6",
          files_committed: 4,
          stdout: "[feat/autopilot a1b2c3d] feat(core): implement git autopilot",
        });
      }
      if (url.includes("/api/git-autopilot/push")) {
        return Promise.resolve({
          success: true,
          remote: "origin",
          branch: "feat/autopilot",
          stdout: "Everything up-to-date",
        });
      }
      if (url.includes("/api/git-autopilot/pr")) {
        return Promise.resolve({
          success: true,
          pr_url: "https://api.github.com/repos/owner/repo/pulls/42",
          html_url: "https://github.com/owner/repo/pull/42",
          pr_number: 42,
        });
      }
      if (url.includes("/api/git-autopilot/github-token")) {
        return Promise.resolve({
          success: true,
          message: "Token saved",
        });
      }
      return Promise.resolve({});
    });
  });

  // ── Test 1: Ship It button opens modal ──────────────────────────────────────
  it("test_ship_it_button_opens_modal: clicking Ship It in sidebar opens GitAutopilotModal and triggers analyze", async () => {
    render(<AppShell />);

    const shipItBtn = screen.getByTestId("ship-it-btn");
    expect(shipItBtn).toBeDefined();

    fireEvent.click(shipItBtn);

    await waitFor(() => {
      expect(screen.getByTestId("git-autopilot-modal")).toBeDefined();
    });

    expect(api.post).toHaveBeenCalledWith(
      "/api/git-autopilot/analyze",
      expect.objectContaining({ workspace: mockWorkspace.path })
    );
  });

  // ── Test 2: Analyzed changes render grouped by category ─────────────────────
  it("test_analyzed_changes_render_grouped: displays category pills and changed files with diff stats", async () => {
    useGitAutopilotStore.setState({
      isOpen: true,
      analysis: {
        is_git_repo: true,
        current_branch: "feat/autopilot",
        files: [
          { path: "src/feature.ts", status: "M", category: "feat", additions: 25, deletions: 5 },
          { path: "src/fix.ts", status: "M", category: "fix", additions: 10, deletions: 2 },
          { path: "src/__tests__/test.ts", status: "A", category: "test", additions: 40, deletions: 0 },
          { path: "README.md", status: "M", category: "docs", additions: 5, deletions: 1 },
        ],
        summary: {
          total_files: 4,
          additions: 80,
          deletions: 8,
          by_category: { feat: 1, fix: 1, test: 1, docs: 1 },
        },
        raw_diff_snippet: "mock diff",
      },
      commitMessage: "feat(core): initial commit",
      prTitle: "feat(core): initial pr",
      prBody: "## Summary\nTest PR",
      branchName: "feat/autopilot",
    });

    render(<GitAutopilotModal isOpen={true} />);

    // Check category pills
    expect(screen.getByTestId("category-pill-feat")).toBeDefined();
    expect(screen.getByTestId("category-pill-fix")).toBeDefined();
    expect(screen.getByTestId("category-pill-test")).toBeDefined();
    expect(screen.getByTestId("category-pill-docs")).toBeDefined();

    // Check additions & deletions
    expect(screen.getByText("+80")).toBeDefined();
    expect(screen.getByText("-8")).toBeDefined();

    // Check file paths rendered
    expect(screen.getByText("src/feature.ts")).toBeDefined();
    expect(screen.getByText("src/fix.ts")).toBeDefined();
    expect(screen.getByText("src/__tests__/test.ts")).toBeDefined();
    expect(screen.getByText("README.md")).toBeDefined();
  });

  // ── Test 3: Commit message is editable and submits ─────────────────────────
  it("test_commit_message_editable_and_submits: textarea is editable, subject char counter updates, and commit sends payload", async () => {
    useGitAutopilotStore.setState({
      isOpen: true,
      analysis: {
        is_git_repo: true,
        current_branch: "main",
        files: [{ path: "file.ts", status: "M", category: "feat", additions: 1, deletions: 0 }],
        summary: { total_files: 1, additions: 1, deletions: 0, by_category: { feat: 1 } },
        raw_diff_snippet: "diff",
      },
      commitMessage: "feat(core): initial message",
    });

    render(<GitAutopilotModal isOpen={true} />);

    const textarea = screen.getByTestId("commit-msg-input");
    expect(textarea).toBeDefined();

    // Verify initial char counter
    const counter = screen.getByTestId("char-counter");
    expect(counter.textContent).toContain("27 / 72 chars");

    // Edit message
    fireEvent.change(textarea, { target: { value: "fix(login): resolve OAuth2 redirect loop\n\nDetailed explanation." } });
    expect(screen.getByTestId("char-counter").textContent).toContain("40 / 72 chars");

    // Click Commit button
    const commitBtn = screen.getByTestId("btn-commit");
    fireEvent.click(commitBtn);

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith(
        "/api/git-autopilot/commit",
        expect.objectContaining({
          workspace: mockWorkspace.path,
          commit_message: "fix(login): resolve OAuth2 redirect loop\n\nDetailed explanation.",
        })
      );
    });

    // Success banner shows commit hash
    await waitFor(() => {
      expect(screen.getByTestId("success-banner")).toBeDefined();
      expect(screen.getByText("a1b2c3d")).toBeDefined();
    });
  });

  // ── Test 4: Action buttons progressive flow ────────────────────────────────
  it("test_action_buttons_progressive_flow: triggers commit+push and ship-it pipeline in sequence", async () => {
    useGitAutopilotStore.setState({
      isOpen: true,
      analysis: {
        is_git_repo: true,
        current_branch: "feat/autopilot",
        files: [{ path: "file.ts", status: "M", category: "feat", additions: 5, deletions: 1 }],
        summary: { total_files: 1, additions: 5, deletions: 1, by_category: { feat: 1 } },
        raw_diff_snippet: "diff",
      },
      commitMessage: "feat(autopilot): add progressive actions",
      prTitle: "feat(autopilot): add progressive actions",
      prBody: "## Summary\nPR body",
      branchName: "feat/autopilot",
      hasGithubToken: true,
    });

    render(<GitAutopilotModal isOpen={true} />);

    // Test Commit + Push
    const commitPushBtn = screen.getByTestId("btn-commit-push");
    fireEvent.click(commitPushBtn);

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith("/api/git-autopilot/commit", expect.anything());
      expect(api.post).toHaveBeenCalledWith(
        "/api/git-autopilot/push",
        expect.objectContaining({
          workspace: mockWorkspace.path,
          branch: "feat/autopilot",
        })
      );
    });

    // Test Ship It (Commit + Push + PR)
    const shipItBtn = screen.getByTestId("btn-ship-it");
    fireEvent.click(shipItBtn);

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith(
        "/api/git-autopilot/pr",
        expect.objectContaining({
          workspace: mockWorkspace.path,
          title: "feat(autopilot): add progressive actions",
          head_branch: "feat/autopilot",
        })
      );
    });
  });

  // ── Test 5: Token prompt when missing ──────────────────────────────────────
  it("test_token_prompt_when_missing: shows inline token prompt, saves token, and updates store state", async () => {
    useGitAutopilotStore.setState({
      isOpen: true,
      hasGithubToken: false,
      analysis: {
        is_git_repo: true,
        current_branch: "feat/autopilot",
        files: [{ path: "file.ts", status: "M", category: "feat", additions: 5, deletions: 1 }],
        summary: { total_files: 1, additions: 5, deletions: 1, by_category: { feat: 1 } },
        raw_diff_snippet: "diff",
      },
      commitMessage: "feat(auth): token prompt test",
      prTitle: "feat(auth): token prompt test",
      branchName: "feat/autopilot",
    });

    render(<GitAutopilotModal isOpen={true} />);

    // GitHub token section should be visible when token is not present
    expect(screen.getByTestId("github-token-section")).toBeDefined();

    const tokenInput = screen.getByTestId("token-prompt-input");
    const saveTokenBtn = screen.getByTestId("btn-save-token");

    fireEvent.change(tokenInput, { target: { value: "ghp_securepersonalaccesstoken12345" } });
    fireEvent.click(saveTokenBtn);

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith(
        "/api/git-autopilot/github-token",
        expect.objectContaining({
          token: "ghp_securepersonalaccesstoken12345",
          workspace: mockWorkspace.path,
        })
      );
    });

    expect(useGitAutopilotStore.getState().hasGithubToken).toBe(true);
  });

  // ── Test 6: Failed to fetch error formatting & retry button ─────────────────
  it("test_error_handling_and_retry: formats Failed to fetch into actionable guidance and allows retry", async () => {
    (api.post as any).mockRejectedValue(new Error("TypeError: Failed to fetch"));

    render(<GitAutopilotModal isOpen={true} />);

    await waitFor(() => {
      const errorBanner = screen.getByTestId("error-banner");
      expect(errorBanner).toBeDefined();
      expect(errorBanner.textContent).toContain("Could not connect to backend server (Failed to fetch)");
    });

    const retryBtn = screen.getByTestId("error-retry-btn");
    expect(retryBtn).toBeDefined();

    (api.post as any).mockResolvedValueOnce({
      is_git_repo: true,
      current_branch: "main",
      files: [],
      summary: { total_files: 0, additions: 0, deletions: 0, by_category: {} },
      raw_diff_snippet: "",
    });

    fireEvent.click(retryBtn);

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith(
        "/api/git-autopilot/analyze",
        expect.objectContaining({ workspace: mockWorkspace.path })
      );
    });
  });
});
