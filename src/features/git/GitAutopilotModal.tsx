import React, { useEffect, useState } from "react";
import {
  Rocket,
  GitBranch,
  GitCommit,
  GitPullRequest,
  CheckCircle2,
  AlertCircle,
  AlertTriangle,
  RefreshCw,
  Sparkles,
  X,
  ExternalLink,
  Key,
  FileText,
  ChevronDown,
  ChevronUp,
  Eye,
  Edit3,
  Loader2,
  FolderGit2,
} from "lucide-react";
import Markdown from "react-markdown";
import { useGitAutopilotStore, GitFileChange } from "./gitAutopilotStore";
import { useWorkspaceStore } from "../../stores/workspaceStore";

const CATEGORY_COLORS: Record<string, { bg: string; text: string; border: string }> = {
  feat: { bg: "bg-emerald-500/15", text: "text-emerald-400", border: "border-emerald-500/30" },
  fix: { bg: "bg-rose-500/15", text: "text-rose-400", border: "border-rose-500/30" },
  test: { bg: "bg-amber-500/15", text: "text-amber-400", border: "border-amber-500/30" },
  docs: { bg: "bg-sky-500/15", text: "text-sky-400", border: "border-sky-500/30" },
  style: { bg: "bg-purple-500/15", text: "text-purple-400", border: "border-purple-500/30" },
  refactor: { bg: "bg-indigo-500/15", text: "text-indigo-400", border: "border-indigo-500/30" },
};

export function GitAutopilotModal({
  isOpen,
  onClose,
}: {
  isOpen?: boolean;
  onClose?: () => void;
}) {
  const storeIsOpen = useGitAutopilotStore((s) => s.isOpen);
  const storeSetOpen = useGitAutopilotStore((s) => s.setOpen);
  const analysis = useGitAutopilotStore((s) => s.analysis);
  const commitMessage = useGitAutopilotStore((s) => s.commitMessage);
  const setCommitMessage = useGitAutopilotStore((s) => s.setCommitMessage);
  const prTitle = useGitAutopilotStore((s) => s.prTitle);
  const setPrTitle = useGitAutopilotStore((s) => s.setPrTitle);
  const prBody = useGitAutopilotStore((s) => s.prBody);
  const setPrBody = useGitAutopilotStore((s) => s.setPrBody);
  const branchName = useGitAutopilotStore((s) => s.branchName);
  const setBranchName = useGitAutopilotStore((s) => s.setBranchName);
  const hasGithubToken = useGitAutopilotStore((s) => s.hasGithubToken);
  const tokenInput = useGitAutopilotStore((s) => s.tokenInput);
  const setTokenInput = useGitAutopilotStore((s) => s.setTokenInput);
  const isTokenPromptOpen = useGitAutopilotStore((s) => s.isTokenPromptOpen);
  const setIsTokenPromptOpen = useGitAutopilotStore((s) => s.setIsTokenPromptOpen);

  const isAnalyzing = useGitAutopilotStore((s) => s.isAnalyzing);
  const isGeneratingCommit = useGitAutopilotStore((s) => s.isGeneratingCommit);
  const isGeneratingPr = useGitAutopilotStore((s) => s.isGeneratingPr);
  const isCreatingBranch = useGitAutopilotStore((s) => s.isCreatingBranch);
  const isCommitting = useGitAutopilotStore((s) => s.isCommitting);
  const isPushing = useGitAutopilotStore((s) => s.isPushing);
  const isCreatingPr = useGitAutopilotStore((s) => s.isCreatingPr);

  const lastCommitHash = useGitAutopilotStore((s) => s.lastCommitHash);
  const lastPrUrl = useGitAutopilotStore((s) => s.lastPrUrl);
  const error = useGitAutopilotStore((s) => s.error);
  const successMessage = useGitAutopilotStore((s) => s.successMessage);
  const clearError = useGitAutopilotStore((s) => s.clearError);
  const clearSuccess = useGitAutopilotStore((s) => s.clearSuccess);

  const analyze = useGitAutopilotStore((s) => s.analyze);
  const generateCommit = useGitAutopilotStore((s) => s.generateCommit);
  const generatePr = useGitAutopilotStore((s) => s.generatePr);
  const createBranch = useGitAutopilotStore((s) => s.createBranch);
  const commit = useGitAutopilotStore((s) => s.commit);
  const push = useGitAutopilotStore((s) => s.push);
  const createPr = useGitAutopilotStore((s) => s.createPr);
  const commitAndPush = useGitAutopilotStore((s) => s.commitAndPush);
  const shipItAll = useGitAutopilotStore((s) => s.shipItAll);
  const saveToken = useGitAutopilotStore((s) => s.saveToken);
  const checkToken = useGitAutopilotStore((s) => s.checkToken);

  const currentWorkspace = useWorkspaceStore((s) => s.currentWorkspace);

  const [showFileList, setShowFileList] = useState(true);
  const [prTab, setPrTab] = useState<"write" | "preview">("write");
  const [isSavingToken, setIsSavingToken] = useState(false);

  const show = isOpen !== undefined ? isOpen : storeIsOpen;
  const handleClose = () => {
    if (onClose) onClose();
    else storeSetOpen(false);
  };

  const wsPath = currentWorkspace?.path || "";

  useEffect(() => {
    if (show && wsPath) {
      void checkToken(wsPath);
      if (!analysis) {
        void analyze(wsPath);
      }
    }
  }, [show, wsPath]);

  if (!show) return null;

  // Character counter for subject line
  const subjectLine = commitMessage.split("\n")[0] || "";
  const isSubjectOverLimit = subjectLine.length > 72;

  const totalChanges = analysis?.files.length || 0;
  const isWorkingTreeClean = analysis?.is_git_repo && totalChanges === 0;
  const isActionBusy = isCommitting || isPushing || isCreatingPr;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Git Autopilot Ship It Modal"
      data-testid="git-autopilot-modal"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-md p-4 sm:p-6 select-none animate-in fade-in duration-200"
    >
      <div className="relative w-full max-w-5xl max-h-[90vh] bg-[#0d0f17] border border-white/10 rounded-2xl shadow-2xl flex flex-col overflow-hidden text-slate-100">
        {/* ── Top Header ──────────────────────────────────────────────────────── */}
        <header className="flex items-center justify-between px-6 py-4 border-b border-white/10 bg-[#141724]/90 shrink-0">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-primary/15 border border-primary/30 flex items-center justify-center text-primary shadow-[0_0_15px_rgba(0,218,243,0.2)]">
              <Rocket size={22} className="animate-pulse" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h1 className="text-base font-bold text-white tracking-wide">
                  Ship It — Git Autopilot
                </h1>
                <span className="text-[10px] uppercase font-bold tracking-wider px-2 py-0.5 rounded-full bg-primary/20 text-primary border border-primary/30">
                  Automated Conventional Workflow
                </span>
              </div>
              <p className="text-xs text-slate-400 flex items-center gap-1.5 mt-0.5">
                <span>Workspace:</span>
                <span className="font-mono text-slate-300 bg-white/5 px-2 py-0.5 rounded border border-white/5">
                  {currentWorkspace?.name || wsPath || "No Workspace Selected"}
                </span>
                {analysis?.current_branch && (
                  <span className="flex items-center gap-1 text-slate-400 ml-1">
                    <GitBranch size={11} className="text-primary" />
                    <span className="text-slate-300 font-mono text-xs">{analysis.current_branch}</span>
                  </span>
                )}
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={() => void analyze(wsPath)}
              disabled={isAnalyzing}
              className="px-3 py-1.5 rounded-lg border border-white/10 bg-white/5 hover:bg-white/10 text-xs font-medium text-slate-300 flex items-center gap-1.5 transition-colors cursor-pointer disabled:opacity-50"
              title="Refresh and re-analyze changes"
            >
              <RefreshCw size={13} className={isAnalyzing ? "animate-spin text-primary" : ""} />
              <span>{isAnalyzing ? "Analyzing..." : "Re-analyze"}</span>
            </button>
            <button
              onClick={handleClose}
              className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-white/10 transition-colors cursor-pointer"
              title="Close modal"
              data-testid="modal-close-btn"
            >
              <X size={18} />
            </button>
          </div>
        </header>

        {/* ── Feedback Banners ─────────────────────────────────────────────────── */}
        {error && (
          <div
            data-testid="error-banner"
            className="px-6 py-2.5 bg-rose-500/15 border-b border-rose-500/30 text-rose-300 text-xs flex items-center justify-between shrink-0"
          >
            <div className="flex items-center gap-2">
              <AlertCircle size={15} className="shrink-0 text-rose-400" />
              <span>{error}</span>
            </div>
            <div className="flex items-center gap-2">
              {wsPath && (
                <button
                  onClick={() => {
                    clearError();
                    void analyze(wsPath);
                  }}
                  className="px-2 py-0.5 rounded bg-rose-500/20 hover:bg-rose-500/30 text-rose-200 text-[11px] font-medium border border-rose-500/40 transition-colors cursor-pointer"
                  data-testid="error-retry-btn"
                  title="Retry analyzing workspace"
                >
                  Retry
                </button>
              )}
              <button
                onClick={clearError}
                className="text-rose-400 hover:text-rose-200 p-0.5 transition-colors cursor-pointer"
              >
                <X size={14} />
              </button>
            </div>
          </div>
        )}

        {successMessage && (
          <div
            data-testid="success-banner"
            className="px-6 py-2.5 bg-emerald-500/15 border-b border-emerald-500/30 text-emerald-300 text-xs flex items-center justify-between shrink-0"
          >
            <div className="flex items-center gap-2">
              <CheckCircle2 size={15} className="shrink-0 text-emerald-400" />
              <span>{successMessage}</span>
              {lastCommitHash && (
                <span className="font-mono bg-emerald-500/20 px-1.5 py-0.5 rounded text-[11px] text-emerald-200 border border-emerald-500/30">
                  {lastCommitHash.slice(0, 7)}
                </span>
              )}
              {lastPrUrl && (
                <a
                  href={lastPrUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1 font-semibold text-primary hover:underline ml-2"
                  data-testid="pr-link"
                >
                  <span>View PR</span>
                  <ExternalLink size={12} />
                </a>
              )}
            </div>
            <button
              onClick={clearSuccess}
              className="text-emerald-400 hover:text-emerald-200 p-0.5 transition-colors cursor-pointer"
            >
              <X size={14} />
            </button>
          </div>
        )}

        {/* ── Scrollable Body ─────────────────────────────────────────────────── */}
        <div className="flex-1 overflow-y-auto px-6 py-5 space-y-6">
          {/* Not a git repo warning */}
          {analysis && !analysis.is_git_repo && (
            <div className="p-4 rounded-xl border border-amber-500/30 bg-amber-500/10 text-amber-200 text-sm flex items-start gap-3">
              <FolderGit2 size={20} className="shrink-0 text-amber-400 mt-0.5" />
              <div>
                <div className="font-semibold text-amber-300">Not a Git Repository</div>
                <div className="text-xs text-amber-200/80 mt-1">
                  The active workspace does not have a git repository initialized. Initialize git in this directory to use Git Autopilot.
                </div>
              </div>
            </div>
          )}

          {/* Working tree clean note */}
          {isWorkingTreeClean && (
            <div className="p-4 rounded-xl border border-white/10 bg-white/5 text-slate-300 text-sm flex items-center justify-between">
              <div className="flex items-center gap-2.5">
                <CheckCircle2 size={18} className="text-emerald-400 shrink-0" />
                <span>Working tree is clean. No uncommitted changes detected.</span>
              </div>
              <button
                onClick={() => void analyze(wsPath)}
                className="px-3 py-1 bg-white/10 hover:bg-white/15 text-xs rounded-lg text-slate-200 transition-colors cursor-pointer"
              >
                Refresh
              </button>
            </div>
          )}

          {/* 1. Analyzed Changes Section */}
          {analysis && analysis.is_git_repo && (
            <section className="space-y-3">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="text-xs uppercase font-bold tracking-wider text-slate-400">
                    Analyzed Changes
                  </span>
                  <span className="text-xs px-2 py-0.5 rounded-full bg-white/5 border border-white/10 text-slate-300 font-medium">
                    {totalChanges} {totalChanges === 1 ? "file" : "files"}
                  </span>
                  {analysis.summary && (
                    <div className="flex items-center gap-1.5 text-xs font-mono ml-2">
                      <span className="text-emerald-400">+{analysis.summary.additions}</span>
                      <span className="text-rose-400">-{analysis.summary.deletions}</span>
                    </div>
                  )}
                </div>

                {totalChanges > 0 && (
                  <button
                    onClick={() => setShowFileList((v) => !v)}
                    className="text-xs text-slate-400 hover:text-slate-200 flex items-center gap-1 transition-colors cursor-pointer"
                  >
                    <span>{showFileList ? "Collapse Files" : "View Files"}</span>
                    {showFileList ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                  </button>
                )}
              </div>

              {/* Category Pills Breakdown */}
              {analysis.summary?.by_category && (
                <div className="flex flex-wrap items-center gap-2" data-testid="category-pills-container">
                  {Object.entries(analysis.summary.by_category).map(([cat, count]) => {
                    if (count === 0) return null;
                    const style = CATEGORY_COLORS[cat] || {
                      bg: "bg-slate-500/15",
                      text: "text-slate-300",
                      border: "border-slate-500/30",
                    };
                    return (
                      <span
                        key={cat}
                        data-testid={`category-pill-${cat}`}
                        className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium border ${style.bg} ${style.text} ${style.border}`}
                      >
                        <span className="font-semibold uppercase tracking-wider text-[10px]">{cat}</span>
                        <span className="bg-black/30 px-1.5 py-0.2 rounded-full text-[11px] font-mono">
                          {count}
                        </span>
                      </span>
                    );
                  })}
                </div>
              )}

              {/* File List */}
              {showFileList && totalChanges > 0 && (
                <div className="rounded-xl border border-white/10 bg-[#07090e]/80 max-h-48 overflow-y-auto divide-y divide-white/5 font-mono text-xs">
                  {analysis.files.map((file: GitFileChange) => {
                    const catStyle = CATEGORY_COLORS[file.category] || {
                      bg: "bg-slate-500/15",
                      text: "text-slate-300",
                      border: "border-slate-500/30",
                    };
                    return (
                      <div
                        key={file.path}
                        className="px-3.5 py-2 flex items-center justify-between hover:bg-white/[0.03] transition-colors"
                      >
                        <div className="flex items-center gap-2.5 min-w-0 flex-1">
                          <span
                            className={`px-1.5 py-0.5 rounded text-[10px] font-bold shrink-0 ${
                              file.status === "M"
                                ? "bg-amber-500/20 text-amber-300"
                                : file.status === "A"
                                ? "bg-emerald-500/20 text-emerald-300"
                                : file.status === "D"
                                ? "bg-rose-500/20 text-rose-300"
                                : "bg-sky-500/20 text-sky-300"
                            }`}
                          >
                            {file.status}
                          </span>
                          <span className="truncate text-slate-300" title={file.path}>
                            {file.path}
                          </span>
                        </div>
                        <div className="flex items-center gap-2.5 shrink-0 ml-3">
                          <span
                            className={`px-2 py-0.5 rounded text-[10px] uppercase font-semibold border ${catStyle.bg} ${catStyle.text} ${catStyle.border}`}
                          >
                            {file.category}
                          </span>
                          {(file.additions > 0 || file.deletions > 0) && (
                            <span className="text-[11px] space-x-1">
                              <span className="text-emerald-400">+{file.additions}</span>
                              <span className="text-rose-400">-{file.deletions}</span>
                            </span>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </section>
          )}

          {/* 2. Conventional Commit Section */}
          <section className="space-y-2">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <GitCommit size={15} className="text-primary" />
                <label
                  htmlFor="commit-msg-input"
                  className="text-xs uppercase font-bold tracking-wider text-slate-400 cursor-pointer"
                >
                  Conventional Commit Message
                </label>
              </div>

              <div className="flex items-center gap-3">
                <span
                  data-testid="char-counter"
                  className={`text-xs font-mono transition-colors ${
                    isSubjectOverLimit ? "text-amber-400 font-semibold" : "text-slate-500"
                  }`}
                  title="Conventional commits recommend <= 72 characters on the subject line"
                >
                  {subjectLine.length} / 72 chars
                  {isSubjectOverLimit && " (Subject exceeds limit)"}
                </span>

                <button
                  type="button"
                  onClick={() => void generateCommit(wsPath)}
                  disabled={isGeneratingCommit || !analysis?.is_git_repo}
                  className="px-2.5 py-1 rounded bg-white/5 hover:bg-white/10 border border-white/10 text-xs font-medium text-slate-300 flex items-center gap-1.5 transition-colors cursor-pointer disabled:opacity-50"
                  title="Regenerate commit message with LLM"
                >
                  <Sparkles size={12} className={isGeneratingCommit ? "animate-spin text-primary" : "text-primary"} />
                  <span>{isGeneratingCommit ? "Generating..." : "Regenerate"}</span>
                </button>
              </div>
            </div>

            <textarea
              id="commit-msg-input"
              data-testid="commit-msg-input"
              value={commitMessage}
              onChange={(e) => setCommitMessage(e.target.value)}
              rows={3}
              placeholder="e.g., feat(auth): add OAuth2 token refresh support"
              className="w-full rounded-xl border border-white/10 bg-[#07090e] px-3.5 py-2.5 text-xs font-mono text-slate-200 placeholder-slate-600 outline-none focus:border-primary/50 focus:ring-1 focus:ring-primary/50 transition-all resize-y"
            />
          </section>

          {/* 3. Branch Section */}
          <section className="space-y-2">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <GitBranch size={15} className="text-primary" />
                <label
                  htmlFor="branch-input"
                  className="text-xs uppercase font-bold tracking-wider text-slate-400 cursor-pointer"
                >
                  Target Branch
                </label>
              </div>
              {branchName && branchName !== analysis?.current_branch && (
                <button
                  type="button"
                  onClick={() => void createBranch(wsPath, branchName)}
                  disabled={isCreatingBranch}
                  className="px-2.5 py-1 rounded bg-primary/15 hover:bg-primary/25 border border-primary/30 text-xs font-medium text-primary flex items-center gap-1 transition-colors cursor-pointer disabled:opacity-50"
                >
                  {isCreatingBranch ? <Loader2 size={12} className="animate-spin" /> : null}
                  <span>Create/Switch Branch</span>
                </button>
              )}
            </div>

            <div className="flex items-center gap-2">
              <input
                id="branch-input"
                data-testid="branch-input"
                type="text"
                value={branchName}
                onChange={(e) => setBranchName(e.target.value)}
                placeholder="branch-name"
                className="flex-1 rounded-xl border border-white/10 bg-[#07090e] px-3.5 py-2 text-xs font-mono text-slate-200 placeholder-slate-600 outline-none focus:border-primary/50 focus:ring-1 focus:ring-primary/50 transition-all"
              />
            </div>
          </section>

          {/* 4. Pull Request Details Section */}
          <section className="space-y-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <GitPullRequest size={15} className="text-primary" />
                <span className="text-xs uppercase font-bold tracking-wider text-slate-400">
                  Pull Request Details
                </span>
              </div>

              <div className="flex items-center gap-2">
                {/* Write / Preview Tab toggle */}
                <div className="flex items-center rounded-lg bg-white/5 p-0.5 border border-white/10">
                  <button
                    type="button"
                    onClick={() => setPrTab("write")}
                    className={`px-2.5 py-1 rounded text-xs font-medium flex items-center gap-1 cursor-pointer transition-colors ${
                      prTab === "write" ? "bg-primary/20 text-primary font-semibold" : "text-slate-400 hover:text-slate-200"
                    }`}
                  >
                    <Edit3 size={11} />
                    <span>Edit</span>
                  </button>
                  <button
                    type="button"
                    onClick={() => setPrTab("preview")}
                    className={`px-2.5 py-1 rounded text-xs font-medium flex items-center gap-1 cursor-pointer transition-colors ${
                      prTab === "preview" ? "bg-primary/20 text-primary font-semibold" : "text-slate-400 hover:text-slate-200"
                    }`}
                  >
                    <Eye size={11} />
                    <span>Preview</span>
                  </button>
                </div>

                <button
                  type="button"
                  onClick={() => void generatePr(wsPath)}
                  disabled={isGeneratingPr || !analysis?.is_git_repo}
                  className="px-2.5 py-1 rounded bg-white/5 hover:bg-white/10 border border-white/10 text-xs font-medium text-slate-300 flex items-center gap-1.5 transition-colors cursor-pointer disabled:opacity-50"
                  title="Regenerate PR title and markdown description"
                >
                  <Sparkles size={12} className={isGeneratingPr ? "animate-spin text-primary" : "text-primary"} />
                  <span>{isGeneratingPr ? "Generating..." : "Regenerate PR"}</span>
                </button>
              </div>
            </div>

            {/* PR Title Input */}
            <div>
              <input
                id="pr-title-input"
                data-testid="pr-title-input"
                type="text"
                value={prTitle}
                onChange={(e) => setPrTitle(e.target.value)}
                placeholder="Pull Request Title"
                className="w-full rounded-xl border border-white/10 bg-[#07090e] px-3.5 py-2 text-xs font-medium text-slate-200 placeholder-slate-600 outline-none focus:border-primary/50 focus:ring-1 focus:ring-primary/50 transition-all"
              />
            </div>

            {/* PR Body Input / Markdown Preview */}
            {prTab === "write" ? (
              <textarea
                id="pr-body-input"
                data-testid="pr-body-input"
                value={prBody}
                onChange={(e) => setPrBody(e.target.value)}
                rows={7}
                placeholder="Pull Request Description (Markdown)..."
                className="w-full rounded-xl border border-white/10 bg-[#07090e] px-3.5 py-2.5 text-xs font-mono text-slate-200 placeholder-slate-600 outline-none focus:border-primary/50 focus:ring-1 focus:ring-primary/50 transition-all resize-y"
              />
            ) : (
              <div
                data-testid="pr-body-preview"
                className="w-full rounded-xl border border-white/10 bg-[#07090e] px-4 py-3 min-h-[160px] max-h-72 overflow-y-auto text-xs text-slate-300 prose prose-invert prose-sm max-w-none"
              >
                {prBody ? (
                  <Markdown>{prBody}</Markdown>
                ) : (
                  <span className="text-slate-600 italic">No description provided yet.</span>
                )}
              </div>
            )}
          </section>

          {/* 5. GitHub Token Prompt (Inline) */}
          {(isTokenPromptOpen || !hasGithubToken) && (
            <section
              data-testid="github-token-section"
              className="p-4 rounded-xl border border-primary/30 bg-primary/5 space-y-2.5"
            >
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Key size={16} className="text-primary" />
                  <span className="text-xs font-bold text-slate-200">
                    GitHub Personal Access Token (PAT)
                  </span>
                </div>
                {hasGithubToken && (
                  <span className="text-[10px] text-emerald-400 font-semibold flex items-center gap-1">
                    <CheckCircle2 size={12} /> Configured
                  </span>
                )}
              </div>

              <p className="text-xs text-slate-400">
                To create GitHub Pull Requests directly from CODE OS, enter a Personal Access Token with{" "}
                <code className="bg-white/10 px-1 py-0.5 rounded text-slate-200">repo</code> scope. Stored securely in your local settings database.
              </p>

              <div className="flex items-center gap-2">
                <input
                  type="password"
                  data-testid="token-prompt-input"
                  value={tokenInput}
                  onChange={(e) => setTokenInput(e.target.value)}
                  placeholder="ghp_xxxxxxxxxxxxxxxxxxxx"
                  className="flex-1 rounded-xl border border-white/10 bg-[#07090e] px-3.5 py-2 text-xs font-mono text-slate-200 placeholder-slate-600 outline-none focus:border-primary/50 focus:ring-1 focus:ring-primary/50 transition-all"
                />
                <button
                  type="button"
                  data-testid="btn-save-token"
                  disabled={isSavingToken || !tokenInput.trim()}
                  onClick={async () => {
                    setIsSavingToken(true);
                    await saveToken(tokenInput, wsPath);
                    setIsSavingToken(false);
                  }}
                  className="px-3.5 py-2 rounded-xl bg-primary hover:bg-primary/90 text-slate-950 text-xs font-semibold flex items-center gap-1.5 transition-colors cursor-pointer disabled:opacity-50"
                >
                  {isSavingToken ? <Loader2 size={13} className="animate-spin" /> : null}
                  <span>Save Token</span>
                </button>
              </div>
            </section>
          )}
        </div>

        {/* ── Footer Actions ─────────────────────────────────────────────────── */}
        <footer className="px-6 py-4 border-t border-white/10 bg-[#141724]/90 flex items-center justify-between shrink-0">
          <div className="text-xs text-slate-500">
            {isWorkingTreeClean
              ? "All changes committed."
              : `${totalChanges} changes ready to stage & ship.`}
          </div>

          <div className="flex items-center gap-2.5">
            {/* Step 1: Commit */}
            <button
              type="button"
              data-testid="btn-commit"
              disabled={isActionBusy || isWorkingTreeClean || !commitMessage.trim()}
              onClick={() => void commit(wsPath)}
              className="px-3.5 py-2 rounded-xl border border-white/10 bg-white/5 hover:bg-white/10 text-xs font-semibold text-slate-200 flex items-center gap-1.5 transition-colors cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed"
            >
              {isCommitting ? <Loader2 size={13} className="animate-spin text-primary" /> : <GitCommit size={14} />}
              <span>Commit</span>
            </button>

            {/* Step 2: Commit + Push */}
            <button
              type="button"
              data-testid="btn-commit-push"
              disabled={isActionBusy || isWorkingTreeClean || !commitMessage.trim()}
              onClick={() => void commitAndPush(wsPath)}
              className="px-3.5 py-2 rounded-xl border border-white/15 bg-white/10 hover:bg-white/15 text-xs font-semibold text-slate-200 flex items-center gap-1.5 transition-colors cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed"
            >
              {isPushing ? <Loader2 size={13} className="animate-spin text-primary" /> : <GitBranch size={14} />}
              <span>Commit + Push</span>
            </button>

            {/* Step 3: Commit + Push + Open PR (Ship It All) */}
            <button
              type="button"
              data-testid="btn-ship-it"
              disabled={isActionBusy || isWorkingTreeClean || !commitMessage.trim()}
              onClick={async () => {
                if (!hasGithubToken) {
                  setIsTokenPromptOpen(true);
                  return;
                }
                await shipItAll(wsPath);
              }}
              className="px-4 py-2 rounded-xl bg-gradient-to-r from-cyan-500 to-primary hover:from-cyan-400 hover:to-primary/90 text-slate-950 text-xs font-bold shadow-lg shadow-primary/20 flex items-center gap-2 transition-all cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed"
            >
              {isActionBusy ? (
                <Loader2 size={14} className="animate-spin" />
              ) : (
                <Rocket size={14} className="shrink-0" />
              )}
              <span>Ship It (Commit + Push + PR)</span>
            </button>
          </div>
        </footer>
      </div>
    </div>
  );
}
