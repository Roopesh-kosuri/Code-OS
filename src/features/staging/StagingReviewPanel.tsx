/**
 * StagingReviewPanel.tsx — GitHub-PR-style multi-file diff review screen.
 *
 * Provides:
 * - 280px left column file list with checkboxes, status badges, and diff line counts
 * - Bulk actions: "Approve Selected", "Reject Selected", "Apply All Approved"
 * - Monaco-compatible diff viewer with red/green lines and line numbers
 * - Per-chunk granular approve/reject buttons
 * - Top summary and progress stats bar
 */

import React, { useEffect, useMemo } from "react";
import {
  GitPullRequest,
  Check,
  X,
  CheckCheck,
  FileCode,
  FilePlus,
  FileX,
  FileText,
  Loader2,
  CheckCircle2,
  XCircle,
  Clock,
  Sparkles,
  ArrowRight,
} from "lucide-react";
import { useStagingStore, type StagedFile, type DiffChunk } from "./stagingStore";

export interface StagingReviewPanelProps {
  onClose?: () => void;
  className?: string;
}

export function StagingReviewPanel({ onClose, className = "" }: StagingReviewPanelProps) {
  const {
    files,
    selectedFile,
    activeDiff,
    selectedFilePaths,
    jobId,
    isOpen,
    isLoading,
    isApplying,
    error,
    setSelectedFile,
    toggleFileSelection,
    selectAll,
    deselectAll,
    approveFiles,
    rejectFiles,
    approveChunk,
    rejectChunk,
    applyChanges,
    approveSelected,
    rejectSelected,
    approveAll,
    rejectAll,
    closeReview,
  } = useStagingStore();

  const approvedCount = useStagingStore((s) => s.approvedCount());
  const rejectedCount = useStagingStore((s) => s.rejectedCount());
  const totalCount = useStagingStore((s) => s.totalCount());
  const pendingCount = useStagingStore((s) => s.pendingCount());
  const totalLinesAdded = useStagingStore((s) => s.totalLinesAdded());
  const totalLinesRemoved = useStagingStore((s) => s.totalLinesRemoved());

  // Currently viewed file object
  const currentFileObj = useMemo(() => {
    return files.find((f) => f.path === selectedFile) || files[0] || null;
  }, [files, selectedFile]);

  // Handle close
  const handleClose = () => {
    closeReview();
    if (onClose) onClose();
  };

  // Group diff lines by chunk for chunk-level rendering
  const groupedLines = useMemo(() => {
    if (!activeDiff?.lines) return [];
    const map = new Map<number, typeof activeDiff.lines>();
    for (const line of activeDiff.lines) {
      const cIdx = line.chunk_index;
      if (!map.has(cIdx)) {
        map.set(cIdx, []);
      }
      map.get(cIdx)!.push(line);
    }
    return Array.from(map.entries()).map(([chunkIndex, lines]) => {
      const chunkMeta = activeDiff.chunks?.find((c) => c.index === chunkIndex);
      return {
        chunkIndex,
        chunkMeta,
        lines,
      };
    });
  }, [activeDiff]);

  const allSelected = files.length > 0 && selectedFilePaths.length === files.length;
  const someSelected = selectedFilePaths.length > 0 && !allSelected;

  const handleApplyApproved = async () => {
    if (!jobId || approvedCount === 0 || isApplying) return;
    await applyChanges(jobId);
    if (onClose) onClose();
  };

  if (!isOpen) {
    return null;
  }

  return (
    <div
      data-testid="staging-review-panel"
      className={`fixed inset-0 z-50 flex flex-col bg-[#0b0d13]/95 backdrop-blur-2xl text-on-surface select-none antialiased border border-white/10 shadow-2xl animate-fade-in ${className}`}
    >
      {/* ── Top Bar: PR Summary & Bulk Actions ────────────────────────────── */}
      <header className="h-14 border-b border-white/10 bg-[#12151e]/90 px-5 flex items-center justify-between shrink-0">
        <div className="flex items-center gap-3 min-w-0">
          <div className="p-2 rounded-lg bg-primary/20 text-primary ring-1 ring-primary/30 flex items-center justify-center">
            <GitPullRequest size={18} />
          </div>
          <div className="flex flex-col min-w-0">
            <div className="flex items-center gap-2">
              <span className="font-bold text-sm text-white tracking-tight">Smart Staging Review</span>
              <span className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-primary/15 text-primary border border-primary/25">
                PR View
              </span>
              {jobId && (
                <span className="text-[11px] font-mono text-on-surface-variant truncate max-w-[140px]">
                  #{jobId}
                </span>
              )}
            </div>
            {/* Summary statistics string */}
            <div
              data-testid="staging-summary-stats"
              className="text-[11px] text-on-surface-variant flex items-center gap-2 font-medium"
            >
              <span>
                {totalCount} {totalCount === 1 ? "file" : "files"} changed, {totalLinesAdded} insertions(+),{" "}
                {totalLinesRemoved} deletions(-)
              </span>
              <span className="text-white/20">•</span>
              {/* Progress string */}
              <span data-testid="staging-progress-stats" className="flex items-center gap-1.5">
                <span className="text-emerald-400 font-semibold">{approvedCount} approved</span>,{" "}
                <span className="text-rose-400 font-semibold">{rejectedCount} rejected</span>,{" "}
                <span className="text-amber-300 font-semibold">{pendingCount} pending</span>
              </span>
            </div>
          </div>
        </div>

        {/* Top Right Bulk Actions */}
        <div className="flex items-center gap-2">
          <button
            type="button"
            data-testid="approve-all-btn"
            onClick={approveAll}
            disabled={totalCount === 0}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-emerald-500/15 hover:bg-emerald-500/25 text-emerald-300 border border-emerald-500/30 text-xs font-semibold interactive-scale cursor-pointer transition-all disabled:opacity-40"
          >
            <CheckCheck size={14} />
            <span>Approve All</span>
          </button>
          <button
            type="button"
            data-testid="reject-all-btn"
            onClick={rejectAll}
            disabled={totalCount === 0}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-rose-500/15 hover:bg-rose-500/25 text-rose-300 border border-rose-500/30 text-xs font-semibold interactive-scale cursor-pointer transition-all disabled:opacity-40"
          >
            <X size={14} />
            <span>Reject All</span>
          </button>
          <div className="w-[1px] h-6 bg-white/10 mx-1" />
          <button
            type="button"
            data-testid="close-staging-review-btn"
            onClick={handleClose}
            className="p-1.5 rounded-lg text-on-surface-variant hover:text-white hover:bg-white/10 transition-colors cursor-pointer"
            title="Close Review"
          >
            <X size={18} />
          </button>
        </div>
      </header>

      {/* ── Main Two-Column Layout ────────────────────────────────────────── */}
      <div className="flex flex-1 min-h-0 overflow-hidden">
        {/* ── Left Column: 280px File List & Staging Controls ────────────── */}
        <aside
          data-testid="staging-file-list"
          style={{ width: "280px" }}
          className="w-[280px] shrink-0 border-r border-white/10 bg-[#0e1118]/90 flex flex-col min-h-0 overflow-hidden shadow-lg"
        >
          {/* File list header with Select All */}
          <div className="h-10 px-3 border-b border-white/10 flex items-center justify-between bg-black/20 text-xs">
            <label className="flex items-center gap-2 cursor-pointer font-medium text-on-surface-variant hover:text-white">
              <input
                type="checkbox"
                data-testid="select-all-files-checkbox"
                checked={allSelected}
                ref={(input) => {
                  if (input) input.indeterminate = someSelected;
                }}
                onChange={(e) => {
                  if (e.target.checked) selectAll();
                  else deselectAll();
                }}
                className="rounded border-white/20 text-primary focus:ring-primary/40 bg-black/40 cursor-pointer"
              />
              <span>Changed Files ({files.length})</span>
            </label>
            <span className="text-[10.5px] font-mono text-on-surface-variant">
              {selectedFilePaths.length} selected
            </span>
          </div>

          {/* Scrollable File List */}
          <div className="flex-1 overflow-y-auto divide-y divide-white/5 min-h-0">
            {files.length === 0 ? (
              <div className="p-6 text-center text-on-surface-variant text-xs flex flex-col items-center gap-2">
                <FileCode size={24} className="opacity-40" />
                <span>No staged changes to review</span>
              </div>
            ) : (
              files.map((file) => {
                const isSelected = file.path === selectedFile;
                const isChecked = selectedFilePaths.includes(file.path);
                const baseName = file.path.split("/").pop() || file.path;
                const dirName = file.path.substring(0, file.path.lastIndexOf("/"));

                // Status badge configuration
                const statusConfig = {
                  added: {
                    label: "added",
                    icon: FilePlus,
                    cls: "bg-emerald-500/20 text-emerald-300 border-emerald-500/40",
                  },
                  deleted: {
                    label: "deleted",
                    icon: FileX,
                    cls: "bg-rose-500/20 text-rose-300 border-rose-500/40",
                  },
                  modified: {
                    label: "modified",
                    icon: FileText,
                    cls: "bg-cyan-500/20 text-cyan-300 border-cyan-500/40",
                  },
                }[file.status] || {
                  label: file.status,
                  icon: FileCode,
                  cls: "bg-amber-500/20 text-amber-300 border-amber-500/40",
                };

                const StatusIcon = statusConfig.icon;

                return (
                  <div
                    key={file.path}
                    data-testid={`staged-file-item-${file.path}`}
                    onClick={() => setSelectedFile(file.path)}
                    className={`group px-3 py-2.5 flex items-start gap-2.5 cursor-pointer transition-colors ${
                      isSelected
                        ? "bg-primary/15 border-l-2 border-primary"
                        : "hover:bg-white/[0.04] border-l-2 border-transparent"
                    }`}
                  >
                    {/* Checkbox */}
                    <div
                      className="pt-0.5 shrink-0"
                      onClick={(e) => {
                        e.stopPropagation();
                        toggleFileSelection(file.path);
                      }}
                    >
                      <input
                        type="checkbox"
                        data-testid={`file-checkbox-${file.path}`}
                        checked={isChecked}
                        onChange={() => {}} // Controlled by onClick container
                        className="rounded border-white/20 text-primary focus:ring-primary/40 bg-black/40 cursor-pointer"
                      />
                    </div>

                    {/* File Info */}
                    <div className="flex-1 min-w-0 flex flex-col gap-0.5">
                      <div className="flex items-center justify-between gap-1">
                        <span
                          className={`font-mono text-xs font-semibold truncate ${
                            isSelected ? "text-primary" : "text-white group-hover:text-primary"
                          }`}
                          title={file.path}
                        >
                          {baseName}
                        </span>

                        {/* Status Badge */}
                        <span
                          data-testid={`status-badge-${file.path}`}
                          className={`text-[9.5px] uppercase font-bold px-1.5 py-0.5 rounded border shrink-0 ${statusConfig.cls}`}
                        >
                          {statusConfig.label}
                        </span>
                      </div>

                      {dirName && (
                        <span className="text-[10px] font-mono text-on-surface-variant truncate opacity-70">
                          {dirName}
                        </span>
                      )}

                      {/* Diff Line Counts and Approval State */}
                      <div className="flex items-center justify-between mt-1 text-[11px] font-mono">
                        <div className="flex items-center gap-1.5">
                          {file.lines_added > 0 && (
                            <span className="text-emerald-400 font-semibold">+{file.lines_added}</span>
                          )}
                          {file.lines_removed > 0 && (
                            <span className="text-rose-400 font-semibold">-{file.lines_removed}</span>
                          )}
                        </div>

                        {file.approved ? (
                          <span
                            data-testid={`file-approved-badge-${file.path}`}
                            className="flex items-center gap-1 text-[10px] font-bold text-emerald-400 bg-emerald-500/10 px-1.5 py-0.5 rounded border border-emerald-500/20"
                          >
                            <Check size={10} strokeWidth={3} /> Approved
                          </span>
                        ) : file.chunks.some((c) => c.approved === false) ? (
                          <span
                            data-testid={`file-rejected-badge-${file.path}`}
                            className="flex items-center gap-1 text-[10px] font-bold text-rose-400 bg-rose-500/10 px-1.5 py-0.5 rounded border border-rose-500/20"
                          >
                            <X size={10} strokeWidth={3} /> Rejected
                          </span>
                        ) : (
                          <span className="text-[10px] text-on-surface-variant/60 flex items-center gap-1">
                            <Clock size={10} /> Pending
                          </span>
                        )}
                      </div>
                    </div>
                  </div>
                );
              })
            )}
          </div>

          {/* Left Column Bottom Action Bar */}
          <div className="p-3 border-t border-white/10 bg-black/30 flex flex-col gap-2 shrink-0">
            {/* Bulk Actions for Selected */}
            <div className="grid grid-cols-2 gap-2">
              <button
                type="button"
                data-testid="approve-selected-btn"
                onClick={approveSelected}
                disabled={selectedFilePaths.length === 0}
                className="flex items-center justify-center gap-1 px-2.5 py-1.5 rounded-lg bg-emerald-500/20 hover:bg-emerald-500/30 text-emerald-300 border border-emerald-500/35 text-[11px] font-semibold interactive-scale cursor-pointer transition-all disabled:opacity-40"
              >
                <Check size={12} />
                <span>Approve ({selectedFilePaths.length})</span>
              </button>
              <button
                type="button"
                data-testid="reject-selected-btn"
                onClick={rejectSelected}
                disabled={selectedFilePaths.length === 0}
                className="flex items-center justify-center gap-1 px-2.5 py-1.5 rounded-lg bg-rose-500/20 hover:bg-rose-500/30 text-rose-300 border border-rose-500/35 text-[11px] font-semibold interactive-scale cursor-pointer transition-all disabled:opacity-40"
              >
                <X size={12} />
                <span>Reject ({selectedFilePaths.length})</span>
              </button>
            </div>

            {/* Apply All Approved button */}
            <button
              type="button"
              data-testid="apply-approved-btn"
              onClick={handleApplyApproved}
              disabled={approvedCount === 0 || isApplying}
              className={`w-full flex items-center justify-center gap-2 py-2.5 rounded-lg text-black font-bold text-xs shadow-lg transition-all cursor-pointer ${
                approvedCount > 0 && !isApplying
                  ? "bg-emerald-400 hover:bg-emerald-300 hover:shadow-emerald-500/30 active:scale-[0.98]"
                  : "bg-white/10 text-white/40 cursor-not-allowed border border-white/5"
              }`}
            >
              {isApplying ? (
                <>
                  <Loader2 size={14} className="animate-spin text-black" />
                  <span>Writing to Disk...</span>
                </>
              ) : (
                <>
                  <CheckCircle2 size={15} />
                  <span>
                    Apply All Approved ({approvedCount}/{totalCount})
                  </span>
                </>
              )}
            </button>
          </div>
        </aside>

        {/* ── Right Column: Monaco-Compatible Diff Viewer ────────────────── */}
        <main
          data-testid="diff-viewer"
          className="flex-1 min-w-0 bg-[#090b10] flex flex-col min-h-0 overflow-hidden relative"
        >
          {/* Diff View Header */}
          {selectedFile ? (
            <div className="h-10 px-4 border-b border-white/10 bg-[#10131c] flex items-center justify-between shrink-0">
              <div className="flex items-center gap-2 min-w-0">
                <FileCode size={15} className="text-primary shrink-0" />
                <span className="font-mono text-xs font-semibold text-white truncate">
                  {selectedFile}
                </span>
                {activeDiff?.status && (
                  <span className="text-[10px] uppercase font-bold px-2 py-0.5 rounded bg-white/5 text-on-surface-variant border border-white/10">
                    {activeDiff.status}
                  </span>
                )}
              </div>

              {/* Individual File Quick Approve/Reject */}
              <div className="flex items-center gap-1.5">
                <button
                  type="button"
                  data-testid="file-quick-approve-btn"
                  onClick={() => jobId && approveFiles(jobId, [selectedFile])}
                  className="flex items-center gap-1 px-2.5 py-1 rounded bg-emerald-500/15 hover:bg-emerald-500/25 text-emerald-300 border border-emerald-500/30 text-[11px] font-semibold cursor-pointer transition-colors"
                >
                  <Check size={12} />
                  <span>Approve File</span>
                </button>
                <button
                  type="button"
                  data-testid="file-quick-reject-btn"
                  onClick={() => jobId && rejectFiles(jobId, [selectedFile])}
                  className="flex items-center gap-1 px-2.5 py-1 rounded bg-rose-500/15 hover:bg-rose-500/25 text-rose-300 border border-rose-500/30 text-[11px] font-semibold cursor-pointer transition-colors"
                >
                  <X size={12} />
                  <span>Reject File</span>
                </button>
              </div>
            </div>
          ) : (
            <div className="h-10 px-4 border-b border-white/10 bg-[#10131c] flex items-center text-xs text-on-surface-variant">
              Select a file to inspect diff
            </div>
          )}

          {/* Monaco Diff Viewer Area */}
          <div
            data-testid="monaco-diff-viewer"
            className="flex-1 overflow-y-auto font-mono text-[11.5px] leading-relaxed select-text min-h-0 divide-y divide-white/5"
          >
            {isLoading ? (
              <div className="p-12 flex flex-col items-center justify-center gap-3 text-on-surface-variant">
                <Loader2 size={24} className="animate-spin text-primary" />
                <span>Loading diff representation...</span>
              </div>
            ) : !selectedFile || !activeDiff ? (
              <div className="p-12 text-center text-on-surface-variant text-xs">
                No file selected or no diff data available
              </div>
            ) : groupedLines.length === 0 ? (
              <div className="p-12 text-center text-on-surface-variant text-xs">
                File contents are identical or empty
              </div>
            ) : (
              groupedLines.map(({ chunkIndex, chunkMeta, lines }) => {
                const isChunkApproved = chunkMeta?.approved === true;
                const isChunkRejected = chunkMeta?.approved === false;
                const isDiffBlock = chunkMeta?.type === "insert" || chunkMeta?.type === "delete";

                return (
                  <div
                    key={`chunk-${chunkIndex}`}
                    data-testid={`diff-chunk-${chunkIndex}`}
                    className="group/chunk relative py-1 hover:bg-white/[0.01] transition-colors"
                  >
                    {/* Per-chunk Header & Floating Action Bar */}
                    {isDiffBlock && (
                      <div className="sticky top-0 z-20 px-3 py-1 bg-[#141824]/95 border-y border-white/10 backdrop-blur-md flex items-center justify-between text-[10.5px]">
                        <div className="flex items-center gap-2 font-semibold">
                          <span className="text-cyan-400">
                            @@ Chunk #{chunkIndex + 1} ({chunkMeta.type}) @@
                          </span>
                          {isChunkApproved ? (
                            <span
                              data-testid={`chunk-status-approved-${chunkIndex}`}
                              className="text-emerald-400 bg-emerald-500/20 px-1.5 py-0.2 rounded border border-emerald-500/30 flex items-center gap-1 font-bold"
                            >
                              <Check size={10} strokeWidth={3} /> Chunk Approved
                            </span>
                          ) : isChunkRejected ? (
                            <span
                              data-testid={`chunk-status-rejected-${chunkIndex}`}
                              className="text-rose-400 bg-rose-500/20 px-1.5 py-0.2 rounded border border-rose-500/30 flex items-center gap-1 font-bold"
                            >
                              <X size={10} strokeWidth={3} /> Chunk Rejected
                            </span>
                          ) : (
                            <span className="text-on-surface-variant/80">Pending Decision</span>
                          )}
                        </div>

                        {/* Per-chunk Approve / Reject buttons */}
                        <div className="flex items-center gap-1.5">
                          <button
                            type="button"
                            data-testid={`approve-chunk-${chunkIndex}`}
                            onClick={() =>
                              jobId && selectedFile && approveChunk(jobId, selectedFile, chunkIndex)
                            }
                            className={`flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-bold cursor-pointer transition-all ${
                              isChunkApproved
                                ? "bg-emerald-500 text-black shadow-sm"
                                : "bg-emerald-500/20 text-emerald-300 hover:bg-emerald-500/35 border border-emerald-500/40"
                            }`}
                          >
                            <Check size={11} strokeWidth={2.5} />
                            <span>Approve Chunk</span>
                          </button>
                          <button
                            type="button"
                            data-testid={`reject-chunk-${chunkIndex}`}
                            onClick={() =>
                              jobId && selectedFile && rejectChunk(jobId, selectedFile, chunkIndex)
                            }
                            className={`flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-bold cursor-pointer transition-all ${
                              isChunkRejected
                                ? "bg-rose-500 text-white shadow-sm"
                                : "bg-rose-500/20 text-rose-300 hover:bg-rose-500/35 border border-rose-500/40"
                            }`}
                          >
                            <X size={11} strokeWidth={2.5} />
                            <span>Reject Chunk</span>
                          </button>
                        </div>
                      </div>
                    )}

                    {/* Diff Lines in Chunk */}
                    <div className="divide-y divide-transparent">
                      {lines.map((l, lIdx) => {
                        const isInsert = l.type === "insert";
                        const isDelete = l.type === "delete";

                        return (
                          <div
                            key={lIdx}
                            data-testid={
                              isInsert
                                ? `diff-line-insert-${l.line_number}`
                                : isDelete
                                ? `diff-line-delete-${l.line_number}`
                                : `diff-line-context-${l.line_number}`
                            }
                            className={`flex items-stretch px-2 py-0.5 font-mono ${
                              isInsert
                                ? "bg-emerald-950/30 text-emerald-300 border-l-2 border-emerald-500"
                                : isDelete
                                ? "bg-rose-950/35 text-rose-300 border-l-2 border-rose-500"
                                : "text-[#c9d1d9] border-l-2 border-transparent hover:bg-white/[0.02]"
                            }`}
                          >
                            {/* Line Numbers Gutter */}
                            <div className="w-12 shrink-0 select-none text-right pr-2 text-on-surface-variant/40 font-mono text-[10.5px]">
                              {l.orig_line_number ?? ""}
                            </div>
                            <div className="w-12 shrink-0 select-none text-right pr-3 text-on-surface-variant/40 font-mono text-[10.5px]">
                              {l.new_line_number ?? ""}
                            </div>

                            {/* Sign Symbol */}
                            <div className="w-4 shrink-0 select-none font-bold text-center">
                              {isInsert ? "+" : isDelete ? "-" : " "}
                            </div>

                            {/* Content */}
                            <div className="flex-1 min-w-0 whitespace-pre overflow-x-auto select-text font-mono pl-1">
                              {l.content}
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </main>
      </div>
    </div>
  );
}
