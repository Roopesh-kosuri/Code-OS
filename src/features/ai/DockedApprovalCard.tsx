import React, { useState, useEffect } from "react";
import {
  FileCode,
  ShieldAlert,
  ExternalLink,
  Check,
  X,
  Clock,
  Layers,
  ShieldCheck,
  Loader2,
  GitPullRequest,
} from "lucide-react";
import type { PendingApprovalState } from "../../stores/aiStore";
import { useStagingStore } from "../staging/stagingStore";

interface DockedApprovalCardProps {
  pendingApproval: PendingApprovalState;
  pendingApprovals?: PendingApprovalState[];
  onApprove: (actionId: string, alwaysAllow?: boolean, trustPattern?: string) => void | Promise<void>;
  onReject: (actionId: string) => void | Promise<void>;
}

export function DockedApprovalCard({
  pendingApproval,
  pendingApprovals = [],
  onApprove,
  onReject,
}: DockedApprovalCardProps) {
  const [alwaysAllow, setAlwaysAllow] = useState(false);
  const [trustWildcard, setTrustWildcard] = useState(false);
  const [isApproving, setIsApproving] = useState(false);
  const [isRejecting, setIsRejecting] = useState(false);

  const isEdit = pendingApproval.action_type === "edit";
  const filePath = pendingApproval.path || pendingApproval.detail || "";
  const queueCount = pendingApprovals.length;
  
  const rawCmd = pendingApproval.command || pendingApproval.detail || "";
  const cleanCmd = rawCmd.replace(/^\(command:\s*/, "").replace(/\s*\)$/, "").trim();

  const testRunnerMatch = !isEdit ? cleanCmd.match(/^(pytest|python -m pytest|npm test|npm run test|vitest|npx vitest|cargo test)/i) : null;
  const testRunnerPrefix = testRunnerMatch ? testRunnerMatch[0] : null;

  const handleOpenDiffInspector = () => {
    window.dispatchEvent(
      new CustomEvent("code-os:switch-top-view", { detail: "proposals" })
    );
  };

  useEffect(() => {
    if (queueCount > 3) {
      const jobId = (pendingApproval as any).job_id || pendingApproval.metadata?.job_id || "agent_job";
      void useStagingStore.getState().openReview(jobId);
    }
  }, [queueCount, pendingApproval]);

  const handleApprove = () => {
    setIsApproving(true);
    const isAlways = alwaysAllow || trustWildcard;
    const pattern = trustWildcard && testRunnerPrefix ? `${testRunnerPrefix} *` : (isAlways ? cleanCmd : undefined);
    void Promise.resolve(onApprove(pendingApproval.action_id, isAlways, pattern)).finally(() => {
      setIsApproving(false);
    });
  };

  const handleReject = () => {
    setIsRejecting(true);
    void Promise.resolve(onReject(pendingApproval.action_id)).finally(() => {
      setIsRejecting(false);
    });
  };

  // Format reason cleanly to avoid multi-line raw command duplication in the paragraph
  let displayReason = pendingApproval.reason || (
    isEdit
      ? `Rony Agent wants to modify ${filePath}`
      : "Command is not on the safe read-only allowlist."
  );
  if (displayReason.includes("Container runtime unavailable")) {
    displayReason = "Container runtime unavailable. Run on host environment? (No container isolation)";
  } else if (displayReason.includes("Terminal command is not on the safe")) {
    displayReason = "Terminal command requires user authorization to execute in workspace.";
  }

  return (
    <div
      className={`border-t border-b px-4 py-3 shrink-0 shadow-[0_-8px_30px_rgba(0,0,0,0.6)] z-30 animate-docked-in backdrop-blur-xl transition-all duration-200 max-h-[70vh] flex flex-col ${
        isEdit
          ? "bg-[#14161b]/98 border-primary/50"
          : "bg-[#161411]/98 border-amber-500/50"
      }`}
    >
      {/* Scrollable Content Container */}
      <div className="overflow-y-auto pr-1 flex-1 min-h-0 space-y-2.5">
        {/* Header Row */}
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2 min-w-0">
            <div
              className={`p-1.5 rounded-lg shrink-0 ${
                isEdit
                  ? "bg-primary/20 text-primary ring-1 ring-primary/30"
                  : "bg-amber-500/20 text-amber-300 ring-1 ring-amber-500/30"
              }`}
            >
              {isEdit ? <FileCode size={15} /> : <ShieldAlert size={15} />}
            </div>
            <div className="flex items-center gap-2 min-w-0">
              <span
                className={`font-bold text-xs ${
                  isEdit ? "text-primary" : "text-amber-300"
                }`}
              >
                {isEdit
                  ? "File Edit Approval Required"
                  : "Terminal Execution Approval Required"}
              </span>
              {isEdit && filePath && (
                <span className="text-[10.5px] px-2 py-0.5 rounded-md bg-primary/15 text-primary font-mono truncate border border-primary/25 max-w-[200px]">
                  {filePath}
                </span>
              )}
            </div>
          </div>

          {/* Badges */}
          <div className="flex items-center gap-1.5 shrink-0">
            {(() => {
              const rawRole = pendingApproval.agent_role || pendingApproval.metadata?.agent_role || "";
              const role = rawRole.toLowerCase();
              const ROLE_BADGE_MAP: Record<string, { label: string; className: string }> = {
                architect: { label: "Architect", className: "bg-blue-500/20 text-blue-300 border-blue-500/40" },
                coder: { label: "Coder", className: "bg-emerald-500/20 text-emerald-300 border-emerald-500/40" },
                reviewer: { label: "Reviewer", className: "bg-orange-500/20 text-orange-300 border-orange-500/40" },
                tester: { label: "Tester", className: "bg-purple-500/20 text-purple-300 border-purple-500/40" },
                devops: { label: "DevOps", className: "bg-red-500/20 text-red-300 border-red-500/40" },
              };
              const roleBadge = ROLE_BADGE_MAP[role];
              if (!roleBadge && !rawRole) return null;
              const label = roleBadge ? roleBadge.label : rawRole;
              const cls = roleBadge ? roleBadge.className : "bg-indigo-500/20 text-indigo-300 border-indigo-500/40";
              const testId = (pendingApproval.metadata?.handle || role || rawRole).toLowerCase().replace(/^@/, "");
              return (
                <span
                  data-testid={`approval-role-badge-${testId}`}
                  className={`flex items-center gap-1 text-[10px] font-bold px-2 py-0.5 rounded-full border ${cls}`}
                >
                  {label}
                </span>
              );
            })()}
            {queueCount > 1 && (
              <span className="flex items-center gap-1 text-[10px] font-semibold px-2 py-0.5 rounded-full bg-surface-variant text-on-surface-variant border border-white/5">
                <Layers size={11} /> +{queueCount - 1} more
              </span>
            )}
            <span
              className={`flex items-center gap-1 text-[10px] font-semibold px-2 py-0.5 rounded-full animate-pulse ${
                isEdit
                  ? "bg-primary/20 text-primary border border-primary/30"
                  : "bg-amber-500/20 text-amber-300 border border-amber-500/30"
              }`}
            >
              <Clock size={10} /> Awaiting decision
            </span>
          </div>
        </div>

        {/* Reason statement */}
        <p className="text-[11.5px] text-on-surface-variant leading-relaxed font-medium">
          {displayReason}
        </p>

        {/* Multi-file PR Review Banner */}
        {queueCount > 3 && (
          <div
            data-testid="multi-file-staging-banner"
            className="p-2 rounded-lg bg-primary/15 border border-primary/30 flex items-center justify-between gap-2"
          >
            <div className="flex items-center gap-2 min-w-0 text-primary text-xs font-semibold">
              <GitPullRequest size={15} className="shrink-0" />
              <span className="truncate">
                {queueCount} files staged. GitHub-PR view is open for safe multi-file review.
              </span>
            </div>
            <button
              type="button"
              data-testid="switch-to-pr-review-btn"
              onClick={() => {
                const jobId = (pendingApproval as any).job_id || pendingApproval.metadata?.job_id || "agent_job";
                void useStagingStore.getState().openReview(jobId);
              }}
              className="px-2.5 py-1 rounded bg-primary text-black font-bold text-[11px] shrink-0 hover:bg-primary/90 cursor-pointer"
            >
              Open PR Review
            </button>
          </div>
        )}

        {/* Native Host Isolation Badge */}
        {!isEdit && (
          <div className="px-2.5 py-1 rounded-md bg-amber-500/10 border border-amber-500/25 text-amber-300 text-[11px] flex items-center gap-1.5 font-medium">
            <ShieldAlert size={13} className="text-amber-400 shrink-0" />
            <span>⚠️ Running on host (no container isolation)</span>
          </div>
        )}

        {/* Preview Snippet */}
        {isEdit ? (
          pendingApproval.diff_summary && (
            <div className="p-2.5 rounded-lg bg-black/70 border border-primary/25 font-mono text-[10.5px] leading-relaxed max-h-32 overflow-y-auto select-text whitespace-pre text-[#c9d1d9] shadow-inner">
              {pendingApproval.diff_summary.split("\n").map((line, lIdx) => (
                <div
                  key={lIdx}
                  className={
                    line.startsWith("+") && !line.startsWith("+++")
                      ? "text-emerald-400 bg-emerald-500/10 px-1 rounded-sm"
                      : line.startsWith("-") && !line.startsWith("---")
                      ? "text-rose-400 bg-rose-500/10 px-1 rounded-sm"
                      : line.startsWith("@@")
                      ? "text-cyan-400 font-bold opacity-80 py-0.5"
                      : "text-on-surface-variant"
                  }
                >
                  {line}
                </div>
              ))}
            </div>
          )
        ) : (
          <div className="p-2.5 rounded-lg bg-black/70 border border-amber-500/35 font-mono text-[11px] text-amber-200 select-all break-all shadow-inner max-h-28 overflow-y-auto leading-relaxed">
            <span className="text-amber-400 font-bold mr-1.5 select-none">$</span>
            {cleanCmd}
          </div>
        )}

        {/* Approval Memory Options (Command approvals) */}
        {!isEdit && (
          <div className="flex flex-col gap-1.5 px-1 py-0.5 text-[11px]">
            <label className="flex items-center gap-2 text-on-surface-variant hover:text-on-surface cursor-pointer select-none">
              <input
                type="checkbox"
                checked={alwaysAllow}
                onChange={(e) => {
                  setAlwaysAllow(e.target.checked);
                  if (e.target.checked) setTrustWildcard(false);
                }}
                className="rounded border-white/20 text-amber-500 focus:ring-amber-500/40 bg-black/40 cursor-pointer"
              />
              <span className="font-medium text-amber-200/90">
                Always allow this exact command in this workspace
              </span>
            </label>

            {testRunnerPrefix && (
              <label className="flex items-center gap-2 text-on-surface-variant hover:text-on-surface cursor-pointer select-none">
                <input
                  type="checkbox"
                  checked={trustWildcard}
                  onChange={(e) => {
                    setTrustWildcard(e.target.checked);
                    if (e.target.checked) setAlwaysAllow(false);
                  }}
                  className="rounded border-white/20 text-amber-500 focus:ring-amber-500/40 bg-black/40 cursor-pointer"
                />
                <span className="flex items-center gap-1 font-medium text-amber-300">
                  <ShieldCheck size={12} className="text-amber-400" />
                  Trust this test runner with any arguments (<code className="font-mono text-[10.5px] bg-black/50 px-1 rounded text-cyan-300">{testRunnerPrefix} *</code>)
                </span>
              </label>
            )}
          </div>
        )}
      </div>

      {/* Actions Footer - Always Visible & Pinned */}
      <div className="shrink-0 flex items-center justify-between gap-2 pt-2.5 mt-2 border-t border-white/10">
        <div>
          {isEdit && (
            <button
              type="button"
              onClick={handleOpenDiffInspector}
              className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg bg-surface-variant hover:bg-surface-variant/80 text-on-surface text-[11px] font-medium interactive-scale cursor-pointer border border-white/5"
            >
              <ExternalLink size={12} className="text-primary" />
              <span>Open Diff Inspector</span>
            </button>
          )}
        </div>

        <div className="flex items-center gap-2 ml-auto">
          <button
            type="button"
            onClick={handleReject}
            className="flex items-center gap-1 px-3.5 py-1.5 rounded-lg bg-white/5 hover:bg-rose-500/15 text-rose-300 hover:text-rose-200 text-xs font-semibold interactive-scale cursor-pointer border border-white/10 hover:border-rose-500/40 transition-all shadow-sm active:scale-95"
          >
            {isRejecting ? <Loader2 size={13} className="animate-spin text-rose-400" /> : <X size={13} className="text-rose-400" />}
            <span>{isRejecting ? "Denying..." : "Deny"}</span>
          </button>
          <button
            type="button"
            onClick={handleApprove}
            className={`flex items-center gap-1.5 px-4 py-1.5 rounded-lg text-black font-bold text-xs shadow-lg interactive-scale cursor-pointer transition-all active:scale-95 ${
              isEdit
                ? "bg-emerald-400 hover:bg-emerald-300 hover:shadow-emerald-500/30"
                : "bg-amber-400 hover:bg-amber-300 hover:shadow-amber-500/30"
            }`}
          >
            {isApproving ? (
              <Loader2 size={14} className="animate-spin" />
            ) : (
              <Check size={14} strokeWidth={2.5} />
            )}
            <span>
              {isApproving
                ? "Executing..."
                : isEdit
                ? "Approve & Apply"
                : alwaysAllow || trustWildcard
                ? "Always Allow & Run"
                : "Approve & Run"}
            </span>
          </button>
        </div>
      </div>
    </div>
  );
}
