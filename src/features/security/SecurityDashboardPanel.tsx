import React, { useState } from "react";
import { Shield, ShieldAlert, ShieldCheck, RefreshCw, Wrench, CheckCircle2, AlertTriangle, FileCode, ExternalLink, Package } from "lucide-react";
import { useSecurityStore, type Vulnerability } from "./securityStore";
import { useWorkspaceStore } from "../../stores/workspaceStore";
import { useEditorStore } from "../../stores/editorStore";

export function SecurityDashboardPanel() {
  const currentWorkspace = useWorkspaceStore((state) => state.currentWorkspace);
  const {
    vulnerabilities,
    dependencyIssues,
    isScanning,
    isFixing,
    scanSummary,
    scanWorkspace,
    generateFix,
    applyFix,
    fixAll,
  } = useSecurityStore();

  const [activeTab, setActiveTab] = useState<"vulns" | "deps">("vulns");
  const [selectedVulnId, setSelectedVulnId] = useState<string | null>(null);

  const handleScan = () => {
    if (currentWorkspace?.path) {
      void scanWorkspace(currentWorkspace.path);
    }
  };

  const handleOpenFile = (file: string) => {
    const editorStore = useEditorStore.getState();
    if (editorStore?.openFile) {
      void editorStore.openFile(file);
    }
  };

  const getSeverityBadge = (severity: string) => {
    const s = severity.toLowerCase();
    if (s === "critical") {
      return (
        <span className="px-2 py-0.5 text-[10px] font-bold uppercase rounded-md bg-red-500/20 text-red-400 border border-red-500/40 tracking-wider">
          Critical
        </span>
      );
    }
    if (s === "high") {
      return (
        <span className="px-2 py-0.5 text-[10px] font-bold uppercase rounded-md bg-orange-500/20 text-orange-400 border border-orange-500/40 tracking-wider">
          High
        </span>
      );
    }
    if (s === "medium") {
      return (
        <span className="px-2 py-0.5 text-[10px] font-bold uppercase rounded-md bg-amber-500/20 text-amber-400 border border-amber-500/40 tracking-wider">
          Medium
        </span>
      );
    }
    return (
      <span className="px-2 py-0.5 text-[10px] font-bold uppercase rounded-md bg-yellow-500/20 text-yellow-400 border border-yellow-500/40 tracking-wider">
        Low
      </span>
    );
  };

  const totalOpen = vulnerabilities.filter((v) => v.status === "open").length;

  return (
    <div className="flex flex-col h-full w-full bg-[#0d0e15] text-white select-none overflow-hidden" data-testid="security-dashboard-panel">
      {/* ── Top Header ──────────────────────────────────────────────────────── */}
      <div className="p-3.5 border-b border-white/10 flex items-center justify-between bg-white/[0.02]">
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-lg bg-red-500/20 border border-red-500/30 flex items-center justify-center text-red-400 shadow-[0_0_12px_rgba(239,68,68,0.2)]">
            <Shield size={18} />
          </div>
          <div>
            <h2 className="text-xs font-bold tracking-wide uppercase text-white/90">Security Scanner</h2>
            <p className="text-[10px] text-white/50">Auto-detect vulnerabilities & AI Auto-Fix</p>
          </div>
        </div>

        <button
          onClick={handleScan}
          disabled={isScanning}
          data-testid="scan-workspace-btn"
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-primary/20 hover:bg-primary/30 border border-primary/40 text-primary hover:text-white text-xs font-semibold transition-all duration-200 cursor-pointer disabled:opacity-50"
        >
          <RefreshCw size={13} className={isScanning ? "animate-spin" : ""} />
          {isScanning ? "Auditing..." : "Scan Workspace"}
        </button>
      </div>

      {/* ── Summary Banner ─────────────────────────────────────────────────── */}
      <div className="p-3 border-b border-white/5 bg-gradient-to-r from-white/[0.03] to-transparent">
        <div className="text-xs font-medium text-white/80" data-testid="security-summary-banner">
          {totalOpen > 0 ? (
            <span>
              Found{" "}
              <strong className="text-red-400 font-bold">{scanSummary.critical} Critical</strong>,{" "}
              <strong className="text-orange-400 font-bold">{scanSummary.high} High</strong>,{" "}
              <strong className="text-yellow-400 font-bold">{scanSummary.low} Low</strong> vulnerabilities
            </span>
          ) : (
            <span className="text-emerald-400 flex items-center gap-1.5">
              <ShieldCheck size={14} /> Workspace is secure. No active vulnerabilities detected.
            </span>
          )}
        </div>

        {/* Quick Bulk Action */}
        {scanSummary.critical > 0 && (
          <div className="mt-2.5 flex items-center justify-between">
            <button
              onClick={() => currentWorkspace?.path && void fixAll(currentWorkspace.path)}
              disabled={isFixing}
              data-testid="fix-all-critical-btn"
              className="px-2.5 py-1 text-[11px] font-bold rounded-md bg-red-600/30 hover:bg-red-600/50 border border-red-500/50 text-red-200 flex items-center gap-1.5 transition-colors cursor-pointer"
            >
              <Wrench size={12} />
              Fix All Critical ({scanSummary.critical})
            </button>
          </div>
        )}
      </div>

      {/* ── Tabs ───────────────────────────────────────────────────────────── */}
      <div className="flex border-b border-white/10 px-3 bg-black/20 text-xs font-medium">
        <button
          onClick={() => setActiveTab("vulns")}
          data-testid="tab-vulnerabilities"
          className={`py-2 px-3 border-b-2 transition-colors cursor-pointer flex items-center gap-1.5 ${
            activeTab === "vulns"
              ? "border-primary text-primary font-bold"
              : "border-transparent text-white/50 hover:text-white/80"
          }`}
        >
          <ShieldAlert size={13} />
          Vulnerabilities ({vulnerabilities.length})
        </button>
        <button
          onClick={() => setActiveTab("deps")}
          data-testid="tab-dependencies"
          className={`py-2 px-3 border-b-2 transition-colors cursor-pointer flex items-center gap-1.5 ${
            activeTab === "deps"
              ? "border-primary text-primary font-bold"
              : "border-transparent text-white/50 hover:text-white/80"
          }`}
        >
          <Package size={13} />
          Dependencies ({dependencyIssues.length})
        </button>
      </div>

      {/* ── Tab Content ────────────────────────────────────────────────────── */}
      <div className="flex-1 min-h-0 overflow-y-auto p-3 space-y-2.5">
        {activeTab === "vulns" ? (
          vulnerabilities.length === 0 ? (
            <div className="h-full flex flex-col items-center justify-center text-center p-6 text-white/40">
              <ShieldCheck size={36} className="text-emerald-500/40 mb-2" />
              <p className="text-xs">No vulnerabilities found.</p>
              <p className="text-[10px] text-white/30 mt-1">Click "Scan Workspace" to inspect your codebase.</p>
            </div>
          ) : (
            vulnerabilities.map((vuln) => {
              const isResolved = vuln.status === "resolved";
              const isSelected = selectedVulnId === vuln.id;

              return (
                <div
                  key={vuln.id}
                  data-testid={`vuln-card-${vuln.id}`}
                  className={`rounded-xl border p-3 transition-all duration-200 ${
                    isResolved
                      ? "bg-emerald-950/10 border-emerald-500/20 opacity-70"
                      : "bg-[#141622] border-white/10 hover:border-white/20"
                  }`}
                >
                  {/* Top line: file + severity */}
                  <div className="flex items-center justify-between gap-2">
                    <button
                      onClick={() => handleOpenFile(vuln.file)}
                      data-testid={`file-link-${vuln.id}`}
                      className="text-xs font-mono text-cyan-400 hover:underline flex items-center gap-1 text-left truncate cursor-pointer"
                      title="Open in Editor"
                    >
                      <FileCode size={12} className="shrink-0" />
                      <span className="truncate">{vuln.file}:{vuln.line}</span>
                    </button>
                    <div className="flex items-center gap-1.5 shrink-0">
                      {isResolved ? (
                        <span className="px-2 py-0.5 text-[10px] font-bold uppercase rounded-md bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 flex items-center gap-1">
                          <CheckCircle2 size={10} /> Resolved
                        </span>
                      ) : (
                        getSeverityBadge(vuln.severity)
                      )}
                    </div>
                  </div>

                  {/* Description */}
                  <p className="text-xs text-white/90 mt-1.5 leading-snug">{vuln.description}</p>

                  {/* Code snippet */}
                  {vuln.code_snippet && (
                    <div className="mt-2 p-2 rounded-md bg-black/50 border border-white/5 font-mono text-[10px] text-white/70 overflow-x-auto">
                      <code>{vuln.code_snippet}</code>
                    </div>
                  )}

                  {/* Patch diff preview */}
                  {vuln.patch_diff && (
                    <div className="mt-2 p-2 rounded-md bg-black/60 border border-cyan-500/30 font-mono text-[10px] overflow-x-auto text-white/80" data-testid={`diff-preview-${vuln.id}`}>
                      <div className="text-[9px] uppercase font-bold text-cyan-400 mb-1 flex items-center gap-1">
                        <Wrench size={10} /> Suggested AI Patch
                      </div>
                      <pre className="whitespace-pre-wrap leading-tight text-white/70">
                        {vuln.patch_diff.split("\n").map((line, idx) => {
                          if (line.startsWith("+")) {
                            return <span key={idx} className="text-emerald-400 block">{line}</span>;
                          }
                          if (line.startsWith("-")) {
                            return <span key={idx} className="text-rose-400 block">{line}</span>;
                          }
                          return <span key={idx} className="block">{line}</span>;
                        })}
                      </pre>
                      {vuln.explanation && (
                        <p className="text-[10px] text-cyan-300/80 mt-1.5 font-sans italic">
                          💡 {vuln.explanation}
                        </p>
                      )}
                    </div>
                  )}

                  {/* Action buttons */}
                  {!isResolved && (
                    <div className="mt-2.5 pt-2 border-t border-white/5 flex items-center justify-end gap-2">
                      {!vuln.patch_diff ? (
                        <button
                          onClick={() => currentWorkspace?.path && void generateFix(vuln.id, currentWorkspace.path)}
                          data-testid={`generate-fix-btn-${vuln.id}`}
                          className="px-2.5 py-1 text-[11px] font-semibold rounded-md bg-cyan-500/20 hover:bg-cyan-500/30 text-cyan-300 border border-cyan-500/40 flex items-center gap-1 transition-colors cursor-pointer"
                        >
                          <Wrench size={11} /> Generate Fix
                        </button>
                      ) : (
                        <button
                          onClick={() => currentWorkspace?.path && void applyFix(vuln.id, vuln.patch_diff, currentWorkspace.path)}
                          disabled={isFixing}
                          data-testid={`apply-fix-btn-${vuln.id}`}
                          className="px-2.5 py-1 text-[11px] font-semibold rounded-md bg-emerald-600/30 hover:bg-emerald-600/50 text-emerald-200 border border-emerald-500/50 flex items-center gap-1 transition-colors cursor-pointer"
                        >
                          <CheckCircle2 size={11} /> Apply Fix
                        </button>
                      )}
                    </div>
                  )}
                </div>
              );
            })
          )
        ) : (
          /* Dependencies Tab */
          dependencyIssues.length === 0 ? (
            <div className="h-full flex flex-col items-center justify-center text-center p-6 text-white/40">
              <Package size={36} className="text-emerald-500/40 mb-2" />
              <p className="text-xs">All dependencies up to date.</p>
              <p className="text-[10px] text-white/30 mt-1">No vulnerable packages flagged by npm audit or safety.</p>
            </div>
          ) : (
            dependencyIssues.map((dep, idx) => (
              <div
                key={idx}
                data-testid={`dep-card-${dep.package}`}
                className="rounded-xl border border-white/10 bg-[#141622] p-3 hover:border-white/20 transition-all"
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-1.5 font-bold text-xs text-white">
                    <Package size={13} className="text-cyan-400" />
                    <span>{dep.package}</span>
                  </div>
                  {getSeverityBadge(dep.severity || "Medium")}
                </div>

                <div className="mt-1.5 text-[11px] text-white/70">
                  <span>Current: <strong className="text-rose-300 font-mono">{dep.current_version}</strong></span>
                  <span className="mx-2 text-white/20">|</span>
                  <span>Safe: <strong className="text-emerald-300 font-mono">{dep.safe_version}</strong></span>
                </div>

                {dep.cve && dep.cve !== "N/A" && (
                  <div className="mt-1 text-[10px] font-mono text-cyan-400/90">
                    CVE: {dep.cve}
                  </div>
                )}

                {dep.description && (
                  <p className="mt-1 text-[11px] text-white/60 leading-snug">{dep.description}</p>
                )}

                <div className="mt-2 pt-2 border-t border-white/5 flex justify-end">
                  <button
                    onClick={() => alert(`To update ${dep.package}, run your package manager update to ${dep.safe_version}`)}
                    className="px-2.5 py-1 text-[10px] font-semibold rounded bg-white/5 hover:bg-white/10 text-white/80 border border-white/10 flex items-center gap-1 transition-colors cursor-pointer"
                  >
                    <ExternalLink size={10} /> Update to {dep.safe_version}
                  </button>
                </div>
              </div>
            ))
          )
        )}
      </div>
    </div>
  );
}
