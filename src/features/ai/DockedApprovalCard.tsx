import React, { useState } from "react";
import {
  FileCode,
  ShieldAlert,
  ExternalLink,
  Check,
  X,
  Clock,
  Layers,
  ShieldCheck,
} from "lucide-react";
import type { PendingApprovalState } from "../../stores/aiStore";

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

  const isEdit = pendingApproval.action_type === "edit";
  const filePath = pendingApproval.path || pendingApproval.detail || "";
  const queueCount = pendingApprovals.length;
  const cmd = pendingApproval.command || pendingApproval.detail || "";

  const testRunnerMatch = !isEdit ? cmd.match(/^(pytest|python -m pytest|npm test|npm run test|vitest|npx vitest|cargo test)/i) : null;
  const testRunnerPrefix = testRunnerMatch ? testRunnerMatch[0] : null;

  const handleOpenDiffInspector = () => {
    window.dispatchEvent(
      new CustomEvent("code-os:switch-top-view", { detail: "proposals" })
    );
  };

  const handleApprove = () => {
    const isAlways = alwaysAllow || trustWildcard;
    const pattern = trustWildcard && testRunnerPrefix ? `${testRunnerPrefix} *` : (isAlways ? cmd : undefined);
    void onApprove(pendingApproval.action_id, isAlways, pattern);
  };

  return (
    <div
      className={`border-t border-b px-4 py-3 shrink-0 shadow-[0_-8px_30px_rgba(0,0,0,0.5)] z-20 animate-docked-in backdrop-blur-xl transition-all duration-200 ${
        isEdit
          ? "bg-[#14161b]/95 border-primary/40"
          : "bg-[#161411]/95 border-amber-500/40"
      }`}
    >
      {/* Header Row */}
      <div className="flex items-center justify-between gap-2 mb-2">
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
          <div className="flex items-center gap-2 truncate">
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
              <span className="text-[10.5px] px-2 py-0.5 rounded-md bg-primary/15 text-primary font-mono truncate border border-primary/25">
                {filePath}
              </span>
            )}
          </div>
        </div>

        {/* Badges */}
        <div className="flex items-center gap-1.5 shrink-0">
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
      <p className="text-[11px] text-on-surface-variant mb-2 leading-relaxed">
        {pendingApproval.reason ||
          (isEdit
            ? `Rony Agent wants to modify ${filePath}`
            : "Command is not on the safe read-only allowlist.")}
      </p>

      {/* Native Host Isolation Badge */}
      {!isEdit && (
        <div className="mb-2 px-2.5 py-1 rounded-md bg-amber-500/10 border border-amber-500/25 text-amber-300 text-[11px] flex items-center gap-1.5 font-medium">
          <ShieldAlert size={13} className="text-amber-400 shrink-0" />
          <span>⚠️ Running on host (no container isolation)</span>
        </div>
      )}

      {/* Preview Snippet */}
      {isEdit ? (
        pendingApproval.diff_summary && (
          <div className="mb-3 p-2.5 rounded-lg bg-black/60 border border-primary/20 font-mono text-[10.5px] leading-relaxed max-h-36 overflow-y-auto select-text whitespace-pre text-[#c9d1d9] shadow-inner">
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
        <div className="mb-2.5 p-2 rounded-lg bg-black/60 border border-amber-500/30 font-mono text-xs text-amber-200 select-all break-all shadow-inner">
          <span className="text-amber-400 font-bold mr-1.5">$</span>
          {cmd}
        </div>
      )}

      {/* Approval Memory Options (Command approvals) */}
      {!isEdit && (
        <div className="mb-3 flex flex-col gap-1.5 px-1 py-1 text-[11px]">
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

      {/* Actions Footer */}
      <div className="flex items-center justify-between gap-2 pt-0.5">
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

        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => void onReject(pendingApproval.action_id)}
            className="flex items-center gap-1 px-3 py-1.5 rounded-lg bg-surface-variant hover:bg-surface-variant/80 text-on-surface text-xs font-medium interactive-scale cursor-pointer border border-white/5 hover:border-rose-500/30"
          >
            <X size={13} className="text-rose-400" />
            <span>Deny</span>
          </button>
          <button
            type="button"
            onClick={handleApprove}
            className={`flex items-center gap-1.5 px-4 py-1.5 rounded-lg text-black font-bold text-xs shadow-md interactive-scale cursor-pointer ${
              isEdit
                ? "bg-emerald-400 hover:bg-emerald-300 hover:shadow-emerald-500/20"
                : "bg-amber-500 hover:bg-amber-400 hover:shadow-amber-500/20"
            }`}
          >
            <Check size={13} strokeWidth={2.5} />
            <span>{isEdit ? "Approve & Apply" : (alwaysAllow || trustWildcard ? "Always Allow & Run" : "Approve & Run")}</span>
          </button>
        </div>
      </div>
    </div>
  );
}
