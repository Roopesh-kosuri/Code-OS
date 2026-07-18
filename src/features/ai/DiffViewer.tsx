import { useEffect, useState, useRef } from "react";
import { Check, X, FileDiff, Eye, ShieldAlert, FileCode, Brain, Gauge, Target, GitBranch, FlaskConical, Shield, ChevronDown, ChevronRight } from "lucide-react";
import { Button } from "../../components/ui/Button";
import { api } from "../../lib/api";
import { useWorkspaceStore } from "../../stores/workspaceStore";

type FileChange = {
  path: string;
  original: string;
  updated: string;
};

type Proposal = {
  id: string;
  summary: string;
  status: string;
  changes: FileChange[];
  diff: string;
  plan?: {
    goal: string;
    hypothesis: string;
    files_to_touch: string[];
    approach: string;
    risks: string[];
    verification: string;
  };
  self_review?: {
    approved: boolean;
    verdict: string;
    issues: string[];
  };
  test_results?: {
    status: string;
    passed: number;
    failed: number;
    total: number;
    summary: string;
  };
};

import { PermissionGate } from "../../components/ui/PermissionGate";

export function DiffViewer() {
  const [proposals, setProposals] = useState<Proposal[]>([]);
  const [selectedProposal, setSelectedProposal] = useState<Proposal | null>(null);
  const [error, setError] = useState<string | null>(null);
  const workspace = useWorkspaceStore((state) => state.currentWorkspace);

  const [isNarrow, setIsNarrow] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!containerRef.current) return;
    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const { width } = entry.contentRect;
        setIsNarrow(width < 450);
      }
    });
    observer.observe(containerRef.current);
    return () => observer.disconnect();
  }, []);

  const fetchProposals = async () => {
    if (!workspace) return;
    try {
      const data = await api.get<Proposal[]>("/api/ai/edit-proposals", { workspace: workspace.path });
      setProposals(data.filter((p) => p.status === "pending"));
      if (data.length > 0 && !selectedProposal) {
        setSelectedProposal(data.filter((p) => p.status === "pending")[0] || null);
      }
    } catch {
      setProposals([]);
    }
  };

  const selectProposal = (p: Proposal) => {
    setSelectedProposal(p);
    setError(null);
  };

  useEffect(() => {
    void fetchProposals();
    const interval = setInterval(() => void fetchProposals(), 4000);
    return () => clearInterval(interval);
  }, [workspace?.path]);

  const handleApply = async (id: string) => {
    setError(null);
    try {
      await api.post(`/api/ai/edit-proposals/${id}/apply`);
      setSelectedProposal(null);
      await fetchProposals();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };
  const handleReject = async (id: string) => {
    setError(null);
    const feedback = prompt("Reason for rejection (optional):");
    if (feedback === null) return; // User cancelled prompt dialog
    try {
      await api.post(`/api/ai/edit-proposals/${id}/reject`, { feedback });
      setSelectedProposal(null);
      await fetchProposals();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };
  const parseProposalSummary = (summaryText: string) => {
    // Expected format: "Task: <task_title> (<agent_role>)"
    const agentMatch = summaryText.match(/\(([^)]+)\)$/);
    const taskMatch = summaryText.match(/^Task:\s*(.*?)(?:\s*\([^)]+\))?$/);
    
    return {
      agent: agentMatch ? agentMatch[1] : "Coding Agent",
      task: taskMatch ? taskMatch[1] : summaryText || "General Code Refactor"
    };
  };

  if (!workspace) {
    return <div className="p-3 text-sm text-slate-500">Open a workspace to inspect proposals.</div>;
  }

  // Parse details for the selected proposal
  const details = selectedProposal ? parseProposalSummary(selectedProposal.summary) : null;

  return (
    <section className="grid h-full min-h-0 w-full min-w-0 grid-cols-1 grid-rows-[38px_1fr] border-b border-surface-700">
      <div className="flex items-center gap-2 border-b border-surface-700 px-3 py-1">
        <FileDiff size={15} className="text-slate-400" />
        <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">Advanced Diff Inspector ({proposals.length})</span>
      </div>
      <div ref={containerRef} className={`flex ${isNarrow ? "flex-col divide-y" : "flex-row divide-x"} divide-surface-700 min-h-0 min-w-0 overflow-x-hidden overflow-y-auto w-full h-full`}>
        {/* Proposal List */}
        <div className={`${isNarrow ? "w-full max-h-[140px] min-h-[70px]" : "w-[170px] shrink-0 h-full"} overflow-auto p-2 space-y-1 bg-surface-950/40`}>
          {proposals.length === 0 ? (
            <div className="text-[10px] text-slate-500 p-2 text-center">No pending AI changes found.</div>
          ) : (
            proposals.map((p) => {
              const { agent, task } = parseProposalSummary(p.summary);
              return (
                <button
                  key={p.id}
                  onClick={() => selectProposal(p)}
                  className={`w-full text-left p-2 rounded text-xs block transition-colors border ${
                    selectedProposal?.id === p.id 
                      ? "bg-surface-800 text-white border-surface-700" 
                      : "text-slate-400 hover:bg-surface-900 border-transparent"
                  }`}
                >
                  <div className="truncate font-semibold text-slate-200">{task}</div>
                  <div className="text-[9px] text-slate-500 truncate font-mono mt-0.5">By: {agent}</div>
                </button>
              );
            })
          )}
        </div>

        {/* Diff Display */}
        <div className="flex-1 overflow-auto p-3 flex flex-col min-h-0">
          {selectedProposal && details ? (
            <div className="flex-1 flex flex-col min-h-0 space-y-3">
              {/* Toolbar */}
              <div className="flex flex-col gap-3 border-b border-surface-800 pb-3">
                <div className="min-w-0 flex-1">
                  <span className="text-xs font-bold text-accent-400 block uppercase font-mono tracking-wider">{details.agent}</span>
                  <div className="flex items-center gap-2 mt-0.5 flex-wrap">
                    <span className="text-[11px] text-slate-350 truncate font-semibold" title={details.task}>{details.task}</span>
                    {selectedProposal.self_review && (
                      <span
                        className={`inline-flex items-center gap-0.5 text-[9px] font-mono font-bold px-1.5 py-0.5 rounded border shrink-0 cursor-help ${
                          selectedProposal.self_review.verdict.includes("regenerated")
                            ? "text-amber-400 bg-amber-400/10 border-amber-500/25"
                            : "text-emerald-400 bg-emerald-400/10 border-emerald-500/25"
                        }`}
                        title={[
                          selectedProposal.self_review.verdict,
                          ...(selectedProposal.self_review.issues?.length ? ["", "Issues:", ...selectedProposal.self_review.issues.map(i => `• ${i}`)] : ["No issues found."])
                        ].join("\n")}
                      >
                        {selectedProposal.self_review.approved ? "✓" : "⚠"} {selectedProposal.self_review.verdict}
                        {selectedProposal.self_review.issues?.length > 0 && (
                          <span className="ml-1 opacity-70">({selectedProposal.self_review.issues.length})</span>
                        )}
                      </span>
                    )}
                  </div>
                </div>
                {error && (
                  <div className="bg-danger/10 border border-danger/20 text-danger text-xs p-3 rounded flex items-start gap-2">
                    <ShieldAlert size={14} className="shrink-0 mt-0.5" />
                    <div className="flex-1">
                      <span className="font-semibold block text-[11px] text-slate-200">Failed to Apply Proposal</span>
                      <span className="font-mono text-[10px] break-all leading-normal text-slate-350">{error}</span>
                    </div>
                  </div>
                )}
                <PermissionGate
                  type="file-write"
                  details={`Apply edits proposed by the AI to workspace files.`}
                  files={selectedProposal.changes.map((c) => c.path)}
                  onApprove={() => handleApply(selectedProposal.id)}
                  onReject={() => handleReject(selectedProposal.id)}
                />
              </div>

              {/* Grouped changes by File */}
              <div className="flex-1 overflow-auto space-y-4 pr-1">
                {/* Collapsible Plan Card */}
                {selectedProposal.plan && (
                  <details open className="bg-gradient-to-br from-violet-950/20 to-surface-900/60 rounded-lg border border-violet-700/30 p-3 text-xs text-slate-350 select-text mb-4">
                    <summary className="font-semibold text-slate-200 cursor-pointer flex items-center gap-1.5 select-none hover:text-white outline-none list-none">
                      <Brain size={13} className="text-violet-400 shrink-0" />
                      <span className="flex-1">Implementation Plan</span>
                      <span className="text-[9px] font-mono text-violet-500 bg-violet-950/50 border border-violet-800/40 px-1.5 py-0.5 rounded">
                        {selectedProposal.plan.files_to_touch.length} file{selectedProposal.plan.files_to_touch.length !== 1 ? "s" : ""}
                      </span>
                    </summary>
                    <div className="mt-3 space-y-3 border-t border-violet-800/30 pt-3 leading-relaxed">
                      {/* Goal */}
                      <div>
                        <div className="flex items-center gap-1.5 mb-1">
                          <Target size={10} className="text-violet-400" />
                          <strong className="text-[9px] uppercase font-bold tracking-wider text-violet-500">Goal</strong>
                        </div>
                        <p className="text-slate-300 text-[11px]">{selectedProposal.plan.goal}</p>
                      </div>
                      {/* Hypothesis */}
                      <div>
                        <div className="flex items-center gap-1.5 mb-1">
                          <Brain size={10} className="text-slate-500" />
                          <strong className="text-[9px] uppercase font-bold tracking-wider text-slate-500">Hypothesis</strong>
                        </div>
                        <p className="text-slate-400 text-[10px] italic">{selectedProposal.plan.hypothesis}</p>
                      </div>
                      {/* Approach */}
                      <div>
                        <div className="flex items-center gap-1.5 mb-1">
                          <GitBranch size={10} className="text-cyan-500" />
                          <strong className="text-[9px] uppercase font-bold tracking-wider text-cyan-600">Approach</strong>
                        </div>
                        <p className="text-slate-300 text-[10px]">{selectedProposal.plan.approach}</p>
                      </div>
                      {/* Files targeted */}
                      {selectedProposal.plan.files_to_touch.length > 0 && (
                        <div>
                          <div className="flex items-center gap-1.5 mb-1.5">
                            <FileCode size={10} className="text-slate-500" />
                            <strong className="text-[9px] uppercase font-bold tracking-wider text-slate-500">Files targeted</strong>
                          </div>
                          <div className="flex flex-wrap gap-1">
                            {selectedProposal.plan.files_to_touch.map((f, i) => (
                              <span
                                key={i}
                                className="text-[9px] font-mono text-slate-300 bg-surface-800 border border-surface-700 px-1.5 py-0.5 rounded truncate max-w-[200px]"
                                title={f}
                              >
                                {f.split(/[/\\]/).pop()}
                              </span>
                            ))}
                          </div>
                        </div>
                      )}
                      {/* Risks */}
                      {selectedProposal.plan.risks && selectedProposal.plan.risks.length > 0 && (
                        <div>
                          <div className="flex items-center gap-1.5 mb-1">
                            <Shield size={10} className="text-amber-500" />
                            <strong className="text-[9px] uppercase font-bold tracking-wider text-amber-600">Risks</strong>
                          </div>
                          <ul className="space-y-0.5">
                            {selectedProposal.plan.risks.map((r, i) => (
                              <li key={i} className="text-[9px] text-amber-200/70 flex items-start gap-1">
                                <span className="text-amber-600 mt-0.5 shrink-0">▸</span>{r}
                              </li>
                            ))}
                          </ul>
                        </div>
                      )}
                      {/* Verification */}
                      <div>
                        <div className="flex items-center gap-1.5 mb-1">
                          <FlaskConical size={10} className="text-emerald-500" />
                          <strong className="text-[9px] uppercase font-bold tracking-wider text-emerald-600">Verification</strong>
                        </div>
                        <p className="text-slate-400 text-[10px]">{selectedProposal.plan.verification}</p>
                      </div>
                    </div>
                  </details>
                )}

                {/* Collapsible Test Results Section */}
                {selectedProposal.test_results && (
                  <details className={`bg-surface-850 rounded border p-3 text-xs select-text mb-4 ${
                    selectedProposal.test_results.status === "pass"
                      ? "border-emerald-500/20"
                      : selectedProposal.test_results.status === "fail"
                        ? "border-rose-500/20"
                        : "border-surface-800"
                  }`}>
                    <summary className="font-semibold cursor-pointer flex items-center justify-between select-none outline-none hover:text-white">
                      <div className="flex items-center gap-1.5">
                        <Gauge size={14} className={
                          selectedProposal.test_results.status === "pass"
                            ? "text-emerald-400"
                            : selectedProposal.test_results.status === "fail"
                              ? "text-rose-400"
                              : "text-slate-500"
                        } />
                        <span className="text-slate-200">Test Execution Results</span>
                      </div>
                      {selectedProposal.test_results.status === "pass" && (
                        <span className="text-[9px] font-bold text-emerald-400 uppercase font-mono bg-emerald-500/10 border border-emerald-500/20 px-1 py-0.5 rounded">Passed ({selectedProposal.test_results.passed}/{selectedProposal.test_results.total})</span>
                      )}
                      {selectedProposal.test_results.status === "fail" && (
                        <span className="text-[9px] font-bold text-rose-400 uppercase font-mono bg-rose-500/10 border border-rose-500/20 px-1 py-0.5 rounded">Failed ({selectedProposal.test_results.failed}/{selectedProposal.test_results.total})</span>
                      )}
                      {selectedProposal.test_results.status === "no_tests" && (
                        <span className="text-[9px] font-bold text-slate-500 uppercase font-mono bg-surface-800 border border-surface-700 px-1 py-0.5 rounded">No Tests cover changes</span>
                      )}
                    </summary>
                    <div className="mt-2.5 border-t border-surface-800 pt-2.5 font-mono text-[10px] text-slate-400 leading-relaxed max-h-32 overflow-y-auto whitespace-pre-wrap">
                      {selectedProposal.test_results.summary}
                    </div>
                  </details>
                )}

                {selectedProposal.changes.map((change, idx) => {
                  const filename = change.path.split(/[/\\]/).pop();
                  const isNewFile = !change.original || !change.original.trim();
                  return (
                    <div key={idx} className="space-y-1">
                      <div className="text-[10px] font-mono text-slate-400 bg-surface-850 border border-surface-800 px-3 py-1 rounded flex items-center gap-2 justify-between" title={change.path}>
                        <div className="flex items-center gap-2">
                          <FileCode size={13} className="text-slate-500" />
                          <span className="text-slate-300 font-semibold">{filename}</span>
                          <span className="text-[9px] text-slate-500 truncate select-all">({change.path})</span>
                        </div>
                        {isNewFile && (
                          <span className="text-[9px] font-bold text-success uppercase font-mono bg-success/10 border border-success/20 px-1.5 py-0.5 rounded shrink-0">
                            New File
                          </span>
                        )}
                      </div>
                      
                      {isNewFile ? (
                        /* Pure creation view */
                        <div className="bg-success/5 border border-success/20 p-3 rounded max-h-56 overflow-auto whitespace-pre text-slate-200 font-mono text-[10px] leading-normal">
                          <div className="text-success border-b border-surface-800 pb-1 mb-1.5 font-bold uppercase text-[9px] tracking-wider flex items-center gap-1.5">
                            <span className="inline-block w-1.5 h-1.5 rounded-full bg-success animate-pulse"></span>
                            Creating new file
                          </div>
                          {change.updated}
                        </div>
                      ) : (
                        /* Edit diff view */
                        <div className={`grid ${isNarrow ? "grid-cols-1" : "grid-cols-2"} gap-2 text-[10px] font-mono leading-normal`}>
                          {/* Original */}
                          <div className="bg-danger/5 border border-danger/20 p-3 rounded max-h-56 overflow-auto whitespace-pre text-slate-200">
                            <div className="text-danger border-b border-surface-800 pb-1 mb-1.5 font-bold uppercase text-[9px] tracking-wider">Original Code</div>
                            {change.original}
                          </div>
                          {/* Updated */}
                          <div className="bg-success/5 border border-success/20 p-3 rounded max-h-56 overflow-auto whitespace-pre text-slate-200">
                            <div className="text-success border-b border-surface-800 pb-1 mb-1.5 font-bold uppercase text-[9px] tracking-wider">Proposed Changes</div>
                            {change.updated}
                          </div>
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          ) : (
            <div className="flex-1 flex flex-col items-center justify-center text-slate-500 text-xs text-center py-8">
              <Eye size={22} className="mb-2 text-slate-600" />
              <span>Select an agent proposal from the list to review, apply, or reject file updates.</span>
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
