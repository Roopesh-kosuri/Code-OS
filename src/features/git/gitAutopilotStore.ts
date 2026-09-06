import { create } from "zustand";
import { api } from "../../lib/api";

export interface GitFileChange {
  path: string;
  status: string;
  category: "feat" | "fix" | "test" | "docs" | "style" | "refactor" | string;
  additions: number;
  deletions: number;
}

export interface GitAnalysisResult {
  is_git_repo: boolean;
  current_branch: string;
  files: GitFileChange[];
  summary: {
    total_files: number;
    additions: number;
    deletions: number;
    by_category: Record<string, number>;
  };
  raw_diff_snippet: string;
}

export interface GitAutopilotState {
  isOpen: boolean;
  analysis: GitAnalysisResult | null;
  commitMessage: string;
  prTitle: string;
  prBody: string;
  branchName: string;
  hasGithubToken: boolean;
  tokenInput: string;
  isTokenPromptOpen: boolean;

  // Busy / loading flags
  isAnalyzing: boolean;
  isGeneratingCommit: boolean;
  isGeneratingPr: boolean;
  isCreatingBranch: boolean;
  isCommitting: boolean;
  isPushing: boolean;
  isCreatingPr: boolean;

  // Results & status
  lastCommitHash: string | null;
  lastPrUrl: string | null;
  error: string | null;
  successMessage: string | null;

  // Actions
  setOpen: (open: boolean) => void;
  setCommitMessage: (msg: string) => void;
  setPrTitle: (title: string) => void;
  setPrBody: (body: string) => void;
  setBranchName: (branch: string) => void;
  setTokenInput: (token: string) => void;
  setIsTokenPromptOpen: (open: boolean) => void;
  clearError: () => void;
  clearSuccess: () => void;

  checkToken: (workspace?: string) => Promise<boolean>;
  saveToken: (token: string, workspace?: string) => Promise<boolean>;
  analyze: (workspace: string) => Promise<void>;
  generateCommit: (workspace: string) => Promise<void>;
  generatePr: (workspace: string) => Promise<void>;
  createBranch: (workspace: string, branchName: string) => Promise<boolean>;
  commit: (workspace: string, message?: string) => Promise<boolean>;
  push: (workspace: string, branch?: string) => Promise<boolean>;
  createPr: (workspace: string, title?: string, body?: string) => Promise<boolean>;
  commitAndPush: (workspace: string) => Promise<boolean>;
  shipItAll: (workspace: string) => Promise<boolean>;
  reset: () => void;
}

function formatError(err: any, fallback: string): string {
  if (!err) return fallback;
  const msg = err.message || (typeof err === "string" ? err : fallback);
  if (typeof msg === "string" && msg.toLowerCase().includes("failed to fetch")) {
    return "Could not connect to backend server (Failed to fetch). Please make sure the backend is running on http://127.0.0.1:8000.";
  }
  return msg || fallback;
}

export const useGitAutopilotStore = create<GitAutopilotState>((set, get) => ({
  isOpen: false,
  analysis: null,
  commitMessage: "",
  prTitle: "",
  prBody: "",
  branchName: "",
  hasGithubToken: false,
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

  setOpen: (open: boolean) => {
    set({ isOpen: open });
    if (open) {
      void get().checkToken();
    }
  },
  setCommitMessage: (commitMessage: string) => set({ commitMessage }),
  setPrTitle: (prTitle: string) => set({ prTitle }),
  setPrBody: (prBody: string) => set({ prBody }),
  setBranchName: (branchName: string) => set({ branchName }),
  setTokenInput: (tokenInput: string) => set({ tokenInput }),
  setIsTokenPromptOpen: (isTokenPromptOpen: boolean) => set({ isTokenPromptOpen }),
  clearError: () => set({ error: null }),
  clearSuccess: () => set({ successMessage: null }),

  checkToken: async (workspace?: string) => {
    try {
      const res = await api.get<{ has_token: boolean }>("/api/git-autopilot/github-token", {
        workspace,
      });
      set({ hasGithubToken: !!res.has_token });
      return !!res.has_token;
    } catch {
      set({ hasGithubToken: false });
      return false;
    }
  },

  saveToken: async (token: string, workspace?: string) => {
    try {
      await api.post("/api/git-autopilot/github-token", { token, workspace });
      set({ hasGithubToken: true, isTokenPromptOpen: false, tokenInput: "", error: null });
      return true;
    } catch (err: any) {
      set({ error: formatError(err, "Failed to save GitHub token") });
      return false;
    }
  },

  analyze: async (workspace: string) => {
    if (!workspace) return;
    set({ isAnalyzing: true, error: null });
    try {
      const result = await api.post<GitAnalysisResult>("/api/git-autopilot/analyze", { workspace });
      set({
        analysis: result,
        branchName: result.current_branch || "main",
        isAnalyzing: false,
      });

      if (result.is_git_repo && result.files.length > 0) {
        // Automatically trigger commit & PR suggestions if not already populated
        if (!get().commitMessage) {
          void get().generateCommit(workspace);
        }
        if (!get().prTitle) {
          void get().generatePr(workspace);
        }
      }
    } catch (err: any) {
      set({ isAnalyzing: false, error: formatError(err, "Failed to analyze workspace git status") });
    }
  },

  generateCommit: async (workspace: string) => {
    if (!workspace) return;
    set({ isGeneratingCommit: true, error: null });
    try {
      const res = await api.post<{ commit_message: string; fallback_used: boolean }>(
        "/api/git-autopilot/generate-commit",
        { workspace }
      );
      set({ commitMessage: res.commit_message || "", isGeneratingCommit: false });
    } catch (err: any) {
      set({ isGeneratingCommit: false, error: formatError(err, "Failed to generate commit message") });
    }
  },

  generatePr: async (workspace: string) => {
    if (!workspace) return;
    set({ isGeneratingPr: true, error: null });
    try {
      const { branchName } = get();
      const res = await api.post<{ title: string; body: string }>("/api/git-autopilot/generate-pr", {
        workspace,
        branch: branchName,
      });
      set({ prTitle: res.title || "", prBody: res.body || "", isGeneratingPr: false });
    } catch (err: any) {
      set({ isGeneratingPr: false, error: formatError(err, "Failed to generate PR description") });
    }
  },

  createBranch: async (workspace: string, branchName: string) => {
    if (!workspace || !branchName) return false;
    set({ isCreatingBranch: true, error: null });
    try {
      await api.post("/api/git-autopilot/branch", { workspace, branch_name: branchName });
      set({ isCreatingBranch: false, branchName });
      return true;
    } catch (err: any) {
      set({ isCreatingBranch: false, error: formatError(err, "Failed to create branch") });
      return false;
    }
  },

  commit: async (workspace: string, message?: string) => {
    const finalMsg = message || get().commitMessage;
    if (!workspace || !finalMsg.trim()) {
      set({ error: "Commit message cannot be empty." });
      return false;
    }
    set({ isCommitting: true, error: null });
    try {
      const res = await api.post<{ success: boolean; commit_hash: string; files_committed: number }>(
        "/api/git-autopilot/commit",
        {
          workspace,
          commit_message: finalMsg,
        }
      );
      set({
        isCommitting: false,
        lastCommitHash: res.commit_hash,
        successMessage: `Committed ${res.files_committed} files (${res.commit_hash})`,
      });
      // Refresh analysis
      void get().analyze(workspace);
      return true;
    } catch (err: any) {
      set({ isCommitting: false, error: formatError(err, "Failed to commit changes") });
      return false;
    }
  },

  push: async (workspace: string, branch?: string) => {
    const targetBranch = branch || get().branchName;
    if (!workspace) return false;
    set({ isPushing: true, error: null });
    try {
      const res = await api.post<{ success: boolean; remote: string; branch: string }>(
        "/api/git-autopilot/push",
        {
          workspace,
          branch: targetBranch,
        }
      );
      set({
        isPushing: false,
        successMessage: `Pushed ${res.branch} to ${res.remote}`,
      });
      return true;
    } catch (err: any) {
      set({ isPushing: false, error: formatError(err, "Failed to push to remote") });
      return false;
    }
  },

  createPr: async (workspace: string, title?: string, body?: string) => {
    const prTitle = title || get().prTitle;
    const prBody = body || get().prBody;
    const headBranch = get().branchName;

    if (!workspace || !prTitle.trim()) {
      set({ error: "PR title cannot be empty." });
      return false;
    }
    set({ isCreatingPr: true, error: null });
    try {
      const res = await api.post<{ success: boolean; pr_url: string; html_url: string; pr_number: number }>(
        "/api/git-autopilot/pr",
        {
          workspace,
          title: prTitle,
          body: prBody,
          head_branch: headBranch,
        }
      );
      set({
        isCreatingPr: false,
        lastPrUrl: res.html_url || res.pr_url,
        successMessage: `PR #${res.pr_number} created successfully!`,
      });
      return true;
    } catch (err: any) {
      const msg = formatError(err, "Failed to create PR");
      if (msg.includes("GitHub Personal Access Token") || msg.includes("token")) {
        set({ isTokenPromptOpen: true });
      }
      set({ isCreatingPr: false, error: msg });
      return false;
    }
  },

  commitAndPush: async (workspace: string) => {
    const committed = await get().commit(workspace);
    if (!committed) return false;
    return await get().push(workspace);
  },

  shipItAll: async (workspace: string) => {
    const prTitle = get().prTitle;
    const prBody = get().prBody;
    const targetBranch = get().branchName;
    const committed = await get().commit(workspace);
    if (!committed) return false;
    const pushed = await get().push(workspace, targetBranch);
    if (!pushed) return false;
    return await get().createPr(workspace, prTitle, prBody);
  },

  reset: () => {
    set({
      analysis: null,
      commitMessage: "",
      prTitle: "",
      prBody: "",
      branchName: "",
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
  },
}));
