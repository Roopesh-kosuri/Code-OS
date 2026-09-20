import React, { useState, useMemo } from "react";
import {
  FileCode,
  ShieldAlert,
  Check,
  X,
  Clock,
  ExternalLink,
  Loader2,
  RotateCcw,
} from "lucide-react";
import { useAIStore, type PendingApprovalState } from "../../stores/aiStore";
import { MonacoDiffViewer, parseUnifiedDiff, getLanguageFromPath } from "../editor/MonacoDiffModal";

export interface InlineConsoleApprovalCardProps {
  pendingApproval: PendingApprovalState;
  onApprove: (actionId: string) => void | Promise<void>;
  onReject: (actionId: string) => void | Promise<void>;
  onReread?: (actionId: string) => void | Promise<void>;
}

export function InlineConsoleApprovalCard({
  pendingApproval,
  onApprove,
  onReject,
  onReread,
}: InlineConsoleApprovalCardProps) {
  const [isApproving, setIsApproving] = useState(false);
  const [isRejecting, setIsRejecting] = useState(false);
  const [isRereading, setIsRereading] = useState(false);
  const [integrityConfirmed, setIntegrityConfirmed] = useState(false);

  const isEdit = pendingApproval.action_type === "edit";
  const filePath = pendingApproval.path || pendingApproval.detail || "";
  const startLine = pendingApproval.start_line ?? pendingApproval.metadata?.start_line;
  const endLine = pendingApproval.end_line ?? pendingApproval.metadata?.end_line;
  const isRangeEdit = isEdit && typeof startLine === "number" && typeof endLine === "number";
  const hasIntegrityWarning = isEdit && Boolean(
    pendingApproval.integrity_warning ||
    (pendingApproval.integrity_status && pendingApproval.integrity_status !== "valid")
  );
  const canApprove = !hasIntegrityWarning || integrityConfirmed;

  const rawCmd = pendingApproval.command || pendingApproval.detail || "";
  const cleanCmd = rawCmd.replace(/^\(command:\s*/, "").replace(/\s*\)$/, "").trim();

  // Relocation event and anchor state (Phase 12.5.1 G2)
  const relocationEvent = pendingApproval.relocation_event ?? pendingApproval.metadata?.relocation_event;
  const isRelocated = Boolean(relocationEvent?.relocated);
  const oldRange = relocationEvent?.old_range;
  const newRange = relocationEvent?.new_range;

  const anchorState: "anchored" | "line-only" | undefined = (
    pendingApproval.anchor_state as any) ||
    (pendingApproval.edit_type as any) ||
    (pendingApproval.metadata?.anchor_state as any) ||
    (pendingApproval.metadata?.edit_type as any) ||
    (isRangeEdit ? "line-only" : undefined);

  const diffData = useMemo(() => {
    if (!isEdit) return { original: "", updated: "" };
    if ((pendingApproval as any).original !== undefined && (pendingApproval as any).updated !== undefined) {
      return {
        original: String((pendingApproval as any).original || ""),
        updated: String((pendingApproval as any).updated || ""),
      };
    }
    const diffText = pendingApproval.diff || pendingApproval.diff_summary || "";
    return parseUnifiedDiff(diffText);
  }, [pendingApproval, isEdit]);

  const handleApprove = async () => {
    if (!canApprove) return;
    setIsApproving(true);
    try {
      await onApprove(pendingApproval.action_id);
    } finally {
      setIsApproving(false);
    }
  };

  const handleReject = async () => {
    setIsRejecting(true);
    try {
      await onReject(pendingApproval.action_id);
    } finally {
      setIsRejecting(false);
    }
  };

  const handleReread = async () => {
    setIsRereading(true);
    try {
      if (onReread) {
        await onReread(pendingApproval.action_id);
      } else {
        await useAIStore.getState().rereadApproval(pendingApproval.action_id);
      }
    } finally {
      setIsRereading(false);
    }
  };

  const handleOpenProposalsTab = () => {
    window.dispatchEvent(
      new CustomEvent("code-os:switch-top-view", { detail: "proposals" })
    );
  };

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

  return (
    <div
      data-testid="inline-approval-card"
      className={`rounded-xl border p-3.5 my-2.5 shadow-xl transition-all duration-200 ${
        isEdit
          ? "bg-[#14161b] border-primary/50 shadow-[0_0_20px_rgba(0,218,243,0.15)]"
          : "bg-[#181512] border-amber-500/50 shadow-[0_0_20px_rgba(245,158,11,0.15)]"
      }`}
    >
      <div className="flex items-center justify-between gap-2 pb-2.5 border-b border-white/10">
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
            <span className={`font-bold text-xs ${isEdit ? "text-primary" : "text-amber-300"}`}>
              {isEdit ? (isRangeEdit ? "Range Edit Approval Required" : "Proposal Approval Required") : "Command Execution Required"}
            </span>
            {isEdit && filePath && (
              <span className="text-[10.5px] px-2 py-0.5 rounded bg-primary/15 text-primary font-mono truncate border border-primary/25 max-w-[280px]">
                {isRangeEdit ? `lines ${startLine}-${endLine} of ${filePath}` : filePath}
              </span>
            )}
            {isEdit && anchorState && (
              <span
                data-testid="anchor-state-badge"
                className={`text-[9.5px] px-1.5 py-0.5 rounded font-mono font-bold uppercase tracking-wider border ${
                  anchorState === "anchored"
                    ? "bg-cyan-500/20 text-cyan-300 border-cyan-500/40"
                    : "bg-zinc-500/20 text-zinc-300 border-zinc-500/40"
                }`}
              >
                {anchorState}
              </span>
            )}
          </div>
        </div>

        <div className="flex items-center gap-1.5 shrink-0">
          {roleBadge && (
            <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full border ${roleBadge.className}`}>
              {roleBadge.label}
            </span>
          )}
          <span className="flex items-center gap-1 text-[10px] font-semibold px-2 py-0.5 rounded-full bg-amber-500/20 text-amber-300 border border-amber-500/30 animate-pulse">
            <Clock size={10} /> Pending
          </span>
        </div>
      </div>

      {/* Amber Relocation Banner (Phase 12.5.1 G2) */}
      {isRelocated && (
        <div
          data-testid="inline-relocation-banner"
          className="mt-2.5 p-2.5 rounded-lg bg-amber-500/15 border border-amber-500/40 text-amber-200 text-xs flex items-center justify-between gap-3 shadow-inner"
        >
          <div className="flex items-center gap-2 min-w-0">
            <span className="text-amber-400 font-bold text-sm shrink-0">⚠</span>
            <div className="flex flex-col min-w-0">
              <span className="font-bold text-amber-300 text-xs leading-tight">
                File drifted — edit relocated
              </span>
              <span className="text-[10.5px] text-amber-200/90 font-mono truncate">
                from lines {oldRange?.[0] ?? "?"}-{oldRange?.[1] ?? "?"} to lines {newRange?.[0] ?? "?"}-{newRange?.[1] ?? "?"}
              </span>
            </div>
          </div>
          <button
            type="button"
            data-testid="inline-reread-btn"
            onClick={handleReread}
            disabled={isRereading || isApproving || isRejecting}
            className="shrink-0 flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-amber-500/20 hover:bg-amber-500/30 text-amber-200 text-[11px] font-semibold border border-amber-500/40 transition-all cursor-pointer disabled:opacity-50"
          >
            {isRereading ? <Loader2 size={12} className="animate-spin text-amber-300" /> : <RotateCcw size={12} className="text-amber-300" />}
            <span>Re-read and re-confirm</span>
          </button>
        </div>
      )}

      {hasIntegrityWarning && (
        <div
          data-testid="inline-integrity-warning"
          className="mt-2.5 p-2 rounded-lg bg-rose-500/15 border border-rose-500/40 text-rose-200 text-xs flex flex-col gap-1"
        >
          <div className="flex items-center gap-1.5 font-bold text-rose-300">
            <ShieldAlert size={13} className="shrink-0 text-rose-400" />
            <span>Integrity Warning: {pendingApproval.integrity_status || "incomplete"}</span>
          </div>
          <p className="text-[10.5px] text-rose-200/90 leading-tight">
            {pendingApproval.integrity_warning || "This code edit contains discrepancies or may be incomplete."}
          </p>
          <label className="flex items-center gap-1.5 mt-0.5 cursor-pointer text-[10.5px] font-semibold text-rose-100 select-none">
            <input
              type="checkbox"
              checked={integrityConfirmed}
              onChange={(e) => setIntegrityConfirmed(e.target.checked)}
              className="rounded border-rose-500/50 text-rose-500 focus:ring-rose-500/40 bg-black/40 cursor-pointer"
            />
            <span>I understand and wish to approve anyway</span>
          </label>
        </div>
      )}

      <div className="my-2.5">
        {isEdit ? (
          <div
            data-testid="inline-diff-viewer"
            className="rounded-lg overflow-hidden border border-white/10 bg-[#0d0e11]"
          >
            <div className="grid grid-cols-2 bg-[#141519] border-b border-white/5 text-[10px] font-mono px-3 py-1 text-on-surface-variant">
              <div className="text-rose-400 font-medium">
                {isRangeEdit ? `Original (Lines ${startLine}-${endLine})` : "Original (Disk)"}
              </div>
              <div className="text-emerald-400 font-medium pl-3 border-l border-white/5">
                {isRangeEdit ? `Proposed (Lines ${startLine}-${endLine})` : "Proposed (Updated)"}
              </div>
            </div>
            <div className="h-[140px] w-full">
              <MonacoDiffViewer
                original={diffData.original}
                modified={diffData.updated}
                language={getLanguageFromPath(filePath)}
                height="140px"
                readOnly={true}
              />
            </div>
          </div>
        ) : (
          <div className="p-2.5 rounded-lg bg-black/70 border border-amber-500/35 font-mono text-[11px] text-amber-200 select-all break-all shadow-inner">
            <span className="text-amber-400 font-bold mr-1.5 select-none">$</span>
            {cleanCmd}
          </div>
        )}
      </div>

      <div className="flex items-center justify-between gap-2 pt-2 border-t border-white/10">
        <div>
          {isEdit && (
            <button
              type="button"
              data-testid="inline-open-proposals-btn"
              onClick={handleOpenProposalsTab}
              className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-surface-variant hover:bg-surface-variant/80 text-on-surface text-[11px] font-medium transition-colors cursor-pointer border border-white/5"
            >
              <ExternalLink size={12} className="text-primary" />
              <span>Full Proposals View</span>
            </button>
          )}
        </div>

        <div className="flex items-center gap-2 ml-auto">
          <button
            type="button"
            data-testid="inline-approval-reject-btn"
            onClick={handleReject}
            disabled={isRejecting || isApproving}
            className="flex items-center gap-1 px-3 py-1.5 rounded-lg bg-white/5 hover:bg-rose-500/15 text-rose-300 hover:text-rose-200 text-xs font-semibold border border-white/10 hover:border-rose-500/40 transition-all cursor-pointer disabled:opacity-40"
          >
            {isRejecting ? <Loader2 size={12} className="animate-spin text-rose-400" /> : <X size={12} className="text-rose-400" />}
            <span>{isRejecting ? "Rejecting..." : "Reject"}</span>
          </button>
          <button
            type="button"
            data-testid="inline-approval-approve-btn"
            onClick={handleApprove}
            disabled={isApproving || isRejecting || !canApprove}
            className={`flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg text-black font-bold text-xs shadow-lg transition-all cursor-pointer ${
              !canApprove
                ? "opacity-50 cursor-not-allowed bg-zinc-600 text-zinc-300 shadow-none"
                : isEdit
                ? "bg-emerald-400 hover:bg-emerald-300 hover:shadow-emerald-500/30"
                : "bg-amber-400 hover:bg-amber-300 hover:shadow-amber-500/30"
            }`}
          >
            {isApproving ? <Loader2 size={13} className="animate-spin" /> : <Check size={13} strokeWidth={2.5} />}
            <span>{isApproving ? "Applying..." : isEdit ? "Approve and Apply" : "Approve and Run"}</span>
          </button>
        </div>
      </div>
    </div>
  );
}
