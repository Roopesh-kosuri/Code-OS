import { useEffect, useState, useRef } from "react";
import {
  Check,
  X,
  FileDiff,
  Eye,
  ShieldAlert,
  FileCode,
  Brain,
  Gauge,
  Target,
  GitBranch,
  FlaskConical,
  Shield,
  Filter,
  Trash2,
  Lock,
  RotateCcw,
  Loader2,
} from "lucide-react";
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
  created_at?: string;
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

export function DiffViewer() {
  const [proposals, setProposals] = useState<Proposal[]>([]);
  const [selectedProposal, setSelectedProposal] = useState<Proposal | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [actionInProgress, setActionInProgress] = useState(false);
  const workspace = useWorkspaceStore((state) => state.currentWorkspace);

  const fetchProposals = async () => {
    if (!workspace) return;
    try {
      const data = await api.get<Proposal[]>("/api/ai/edit-proposals", { workspace: workspace.path });
      const pendingList = data.filter((p) => p.status === "pending");
      setProposals(pendingList);
      if (pendingList.length > 0 && (!selectedProposal || !pendingList.some((p) => p.id === selectedProposal.id))) {
        setSelectedProposal(pendingList[0]);
      } else if (pendingList.length === 0) {
        setSelectedProposal(null);
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
    const interval = setInterval(() => void fetchProposals(), 6000);

    const handler = () => void fetchProposals();
    const selectHandler = (e: Event) => {
      const targetId = (e as CustomEvent<string>).detail;
      void api.get<Proposal[]>("/api/ai/edit-proposals", { workspace: workspace?.path }).then((data) => {
        const pendingList = data.filter((p) => p.status === "pending");
        setProposals(pendingList);
        const match = pendingList.find((p) => p.id === targetId);
        if (match) setSelectedProposal(match);
        else if (pendingList.length > 0) setSelectedProposal(pendingList[0]);
        else setSelectedProposal(null);
      }).catch(() => undefined);
    };

    window.addEventListener("code-os:proposal-created", handler);
    window.addEventListener("code-os:proposal-applied", handler);
    window.addEventListener("code-os:proposal-updated", handler);
    window.addEventListener("code-os:select-proposal", selectHandler);
    return () => {
      clearInterval(interval);
      window.removeEventListener("code-os:proposal-created", handler);
      window.removeEventListener("code-os:proposal-applied", handler);
      window.removeEventListener("code-os:proposal-updated", handler);
      window.removeEventListener("code-os:select-proposal", selectHandler);
    };
  }, [workspace?.path]);

  const handleApply = async (id: string) => {
    setError(null);
    setActionInProgress(true);
    try {
      await api.post(`/api/ai/edit-proposals/${id}/apply`);
      setSelectedProposal(null);
      window.dispatchEvent(new CustomEvent("code-os:proposal-applied", { detail: id }));
      await useWorkspaceStore.getState().refreshTree();
      await fetchProposals();
    } catch (err: any) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setActionInProgress(false);
    }
  };

  const handleReject = async (id: string) => {
    setError(null);
    const feedback = prompt("Reason for rejection (optional feedback for agent):");
    if (feedback === null) return; // User cancelled prompt
    setActionInProgress(true);
    try {
      await api.post(`/api/ai/edit-proposals/${id}/reject`, { feedback: feedback.trim() || undefined });
      setSelectedProposal(null);
      window.dispatchEvent(new CustomEvent("code-os:proposal-updated", { detail: id }));
      await fetchProposals();
    } catch (err: any) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setActionInProgress(false);
    }
  };

  const parseProposalSummary = (summaryText: string) => {
    const agentMatch = summaryText.match(/\(([^)]+)\)$/);
    const taskMatch = summaryText.match(/^Task:\s*(.*?)(?:\s*\([^)]+\))?$/);
    return {
      agent: agentMatch ? agentMatch[1] : "Coding Agent",
      task: taskMatch ? taskMatch[1] : summaryText || "General Code Refactor",
    };
  };

  if (!workspace) {
    return (
      <div className="flex-1 flex items-center justify-center p-6 text-sm text-on-surface-variant font-mono">
        Open a workspace to inspect proposals.
      </div>
    );
  }

  const details = selectedProposal ? parseProposalSummary(selectedProposal.summary) : null;

  return (
    <div className="flex-1 flex flex-col h-full overflow-hidden bg-background text-on-surface font-ui-label-reg text-ui-label-reg p-6 antialiased select-none">
      <div className="flex flex-1 gap-6 overflow-hidden">
        {/* ── Left Proposals List Panel ─────────────────────────────────────── */}
        <section className="w-80 flex flex-col bg-surface-container rounded-xl border border-surface-variant overflow-hidden shrink-0 shadow-lg">
          <div className="p-4 border-b border-surface-variant flex justify-between items-center bg-surface-container-low">
            <h2 className="font-ui-label-bold text-ui-label-bold text-on-surface font-bold">
              Advanced Diff Inspector ({proposals.length})
            </h2>
            <button onClick={() => void fetchProposals()} className="text-on-surface-variant hover:text-on-surface p-1">
              <RotateCcw size={13} />
            </button>
          </div>

          <div className="flex-1 overflow-y-auto p-2 space-y-1.5">
            {proposals.length === 0 ? (
              <div className="text-xs text-on-surface-variant/50 p-6 text-center italic space-y-2">
                <FileDiff size={24} className="mx-auto text-outline-variant" />
                <p>No pending proposals found in workspace.</p>
              </div>
            ) : (
              proposals.map((p) => {
                const { agent, task } = parseProposalSummary(p.summary);
                const isSelected = selectedProposal?.id === p.id;
                const additions = (p.changes || []).reduce((acc, c) => acc + (c.updated ? c.updated.split("\n").length : 0), 0);
                const deletions = (p.changes || []).reduce((acc, c) => acc + (c.original ? c.original.split("\n").length : 0), 0);

                return (
                  <button
                    key={p.id}
                    onClick={() => selectProposal(p)}
                    className={`w-full text-left p-3.5 rounded-lg transition-all relative group cursor-pointer ${
                      isSelected
                        ? "bg-surface-variant border border-primary/30 active-glow shadow-md"
                        : "hover:bg-surface-container-high border border-transparent"
                    }`}
                  >
                    {isSelected && (
                      <div className="absolute left-0 top-1/2 -translate-y-1/2 w-1 h-8 bg-primary rounded-r-full" />
                    )}
                    <div className="flex justify-between items-start mb-1">
                      <span className={`font-caption text-caption uppercase font-bold text-[10px] ${
                        isSelected ? "text-primary" : "text-on-surface-variant"
                      }`}>
                        By: {agent}
                      </span>
                      <span className="font-caption text-[10px] text-on-surface-variant font-mono">
                        {p.created_at ? new Date(p.created_at).toLocaleTimeString() : "Pending"}
                      </span>
                    </div>
                    <h3 className="font-ui-label-bold text-ui-label-bold text-on-surface truncate">
                      {task}
                    </h3>
                    <div className="flex gap-2 mt-2">
                      <span className="px-2 py-0.5 rounded-full bg-surface-container-highest text-on-surface-variant font-code-sm text-code-sm text-[10px] flex items-center gap-1">
                        <span className="material-symbols-outlined text-[12px] text-emerald-400">add</span> {additions}
                      </span>
                      <span className="px-2 py-0.5 rounded-full bg-surface-container-highest text-on-surface-variant font-code-sm text-code-sm text-[10px] flex items-center gap-1">
                        <span className="material-symbols-outlined text-[12px] text-error">remove</span> {deletions}
                      </span>
                    </div>
                  </button>
                );
              })
            )}
          </div>
        </section>

        {/* ── Right Proposal Details Panel ──────────────────────────────────── */}
        <section className="flex-1 flex flex-col bg-surface-container rounded-xl border border-surface-variant overflow-hidden relative shadow-lg">
          {selectedProposal && details ? (
            <>
              {/* Header */}
              <header className="p-6 pb-4 border-b border-surface-variant bg-surface-container-low shrink-0 flex justify-between items-start">
                <div>
                  <div className="flex items-center gap-3 mb-2">
                    <span className="px-2.5 py-1 rounded-full bg-surface-variant text-on-surface font-caption text-[10px] tracking-widest uppercase flex items-center gap-1.5 border border-outline-variant font-bold">
                      <span className="material-symbols-outlined text-[14px] text-primary">smart_toy</span>
                      {details.agent.toUpperCase()}
                    </span>
                    {selectedProposal.self_review?.approved && (
                      <span className="flex items-center gap-1 text-emerald-400 font-caption text-caption px-2.5 py-1 bg-emerald-500/10 rounded-full border border-emerald-500/20 font-semibold">
                        <span className="material-symbols-outlined text-[14px]" style={{ fontVariationSettings: "'FILL' 1" }}>
                          check_circle
                        </span>
                        self-reviewed
                      </span>
                    )}
                  </div>
                  <h1 className="font-headline-md text-headline-md text-on-surface mb-1 font-bold">
                    {details.task}
                  </h1>
                  <p className="font-ui-label-reg text-ui-label-reg text-on-surface-variant text-xs font-mono">
                    Proposal ID: #{selectedProposal.id.slice(0, 8)} • {(selectedProposal.changes || []).length} files modified
                  </p>
                </div>

                <div className="flex gap-2">
                  <button
                    onClick={() => void handleReject(selectedProposal.id)}
                    disabled={actionInProgress}
                    className="px-4 py-2 rounded-full border border-outline text-on-surface font-ui-label-bold text-ui-label-bold hover:bg-surface-variant transition-colors cursor-pointer text-xs disabled:opacity-40"
                  >
                    Reject with Feedback
                  </button>
                </div>
              </header>

              {/* Scrollable Details Body */}
              <div className="flex-1 overflow-y-auto p-6 space-y-6">
                {/* File Write Permission Alert Card */}
                <div className="danger-glow rounded-xl p-6 relative overflow-hidden flex flex-col gap-4 shadow-lg">
                  <div className="absolute top-0 left-0 w-1 h-full bg-error" />
                  <div className="flex items-start gap-4">
                    <div className="p-2 rounded-full bg-error/10 text-error shrink-0">
                      <span className="material-symbols-outlined text-2xl" style={{ fontVariationSettings: "'FILL' 1" }}>
                        warning
                      </span>
                    </div>
                    <div className="flex-1">
                      <h3 className="font-ui-label-bold text-ui-label-bold text-error mb-1 text-base">
                        File Write Permission Required
                      </h3>
                      <p className="font-ui-label-reg text-ui-label-reg text-on-surface mb-4 text-xs leading-relaxed">
                        Review target file changes and implementation plan below before authorizing disk writes.
                      </p>
                      <div>
                        <p className="font-caption text-caption text-on-surface-variant uppercase tracking-wider mb-2 font-bold">
                          AFFECTED FILES ({(selectedProposal.changes || []).length}):
                        </p>
                        <div className="flex flex-wrap gap-2">
                          {(selectedProposal.changes || []).map((change, idx) => (
                            <span
                              key={idx}
                              className="px-2.5 py-1 rounded bg-background border border-outline-variant text-on-surface font-code-sm text-code-sm text-[11px] flex items-center gap-1.5"
                            >
                              <FileCode size={13} className="text-primary" />
                              <span>{change.path}</span>
                            </span>
                          ))}
                        </div>
                      </div>
                    </div>
                  </div>

                  <div className="flex justify-end gap-3 border-t border-error/20 pt-4">
                    <button
                      onClick={() => void handleReject(selectedProposal.id)}
                      disabled={actionInProgress}
                      className="px-6 py-2 rounded-full border border-outline text-on-surface font-ui-label-bold text-ui-label-bold hover:bg-surface-variant transition-colors cursor-pointer text-xs disabled:opacity-40"
                    >
                      Deny
                    </button>
                    
                      <button
                        onClick={() => void handleApply(selectedProposal.id)}
                        disabled={actionInProgress}
                        className="px-6 py-2 rounded-full bg-primary-container text-[#001f24] font-ui-label-bold text-ui-label-bold hover:bg-primary-fixed transition-colors shadow-lg flex items-center gap-2 cursor-pointer text-xs disabled:opacity-40"
                      >
                        {actionInProgress ? <Loader2 size={13} className="animate-spin" /> : <Check size={14} />}
                        <span>Approve &amp; Apply</span>
                      </button>
                    
                  </div>
                </div>

                {/* Test Results Collapsible Section (Restored) */}
                {selectedProposal.test_results && (
                  <div className={`bg-surface-container-low rounded-xl border p-4 text-xs shadow-md ${
                    selectedProposal.test_results.status === "pass"
                      ? "border-emerald-500/30"
                      : selectedProposal.test_results.status === "fail"
                        ? "border-error/30"
                        : "border-surface-variant"
                  }`}>
                    <div className="flex items-center justify-between font-bold mb-2">
                      <div className="flex items-center gap-2">
                        <Gauge size={16} className={selectedProposal.test_results.status === "pass" ? "text-emerald-400" : "text-error"} />
                        <span className="text-on-surface">Automated Test Execution</span>
                      </div>
                      <span className={`px-2.5 py-0.5 rounded font-mono text-[10px] uppercase font-bold ${
                        selectedProposal.test_results.status === "pass"
                          ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20"
                          : "bg-error/10 text-error border border-error/20"
                      }`}>
                        {selectedProposal.test_results.status === "pass"
                          ? `Passed (${selectedProposal.test_results.passed}/${selectedProposal.test_results.total})`
                          : `Failed (${selectedProposal.test_results.failed}/${selectedProposal.test_results.total})`}
                      </span>
                    </div>
                    {selectedProposal.test_results.summary && (
                      <pre className="bg-[#0a0a0c] border border-surface-variant rounded p-3 font-mono text-[11px] text-on-surface-variant overflow-x-auto whitespace-pre-wrap leading-relaxed">
                        {selectedProposal.test_results.summary}
                      </pre>
                    )}
                  </div>
                )}

                {/* Implementation Plan Card */}
                {selectedProposal.plan && (
                  <div className="bg-surface-container-low border border-surface-variant rounded-xl p-6 shadow-md">
                    <h2 className="font-headline-md text-headline-md text-on-surface mb-6 flex items-center gap-2 font-bold">
                      <span className="material-symbols-outlined text-primary">account_tree</span>
                      <span>Implementation Plan</span>
                    </h2>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
                      <div className="space-y-6">
                        <div>
                          <h4 className="font-ui-label-bold text-ui-label-bold text-primary mb-1.5 flex items-center gap-1.5 uppercase tracking-wide text-xs font-bold">
                            <span className="material-symbols-outlined text-[16px]">flag</span> Goal
                          </h4>
                          <p className="font-ui-label-reg text-ui-label-reg text-on-surface-variant leading-relaxed text-xs">
                            {selectedProposal.plan.goal}
                          </p>
                        </div>
                        <div>
                          <h4 className="font-ui-label-bold text-ui-label-bold text-secondary mb-1.5 flex items-center gap-1.5 uppercase tracking-wide text-xs font-bold">
                            <span className="material-symbols-outlined text-[16px]">science</span> Hypothesis
                          </h4>
                          <p className="font-ui-label-reg text-ui-label-reg text-on-surface-variant leading-relaxed text-xs">
                            {selectedProposal.plan.hypothesis}
                          </p>
                        </div>
                      </div>

                      <div className="space-y-6">
                        <div>
                          <h4 className="font-ui-label-bold text-ui-label-bold text-tertiary mb-1.5 flex items-center gap-1.5 uppercase tracking-wide text-xs font-bold">
                            <span className="material-symbols-outlined text-[16px]">route</span> Approach
                          </h4>
                          <p className="font-ui-label-reg text-ui-label-reg text-on-surface-variant leading-relaxed text-xs">
                            {selectedProposal.plan.approach}
                          </p>
                        </div>
                        {selectedProposal.plan.risks && selectedProposal.plan.risks.length > 0 && (
                          <div>
                            <h4 className="font-ui-label-bold text-ui-label-bold text-error mb-1.5 flex items-center gap-1.5 uppercase tracking-wide text-xs font-bold">
                              <span className="material-symbols-outlined text-[16px]">gavel</span> Risks
                            </h4>
                            <ul className="list-disc pl-4 space-y-1 text-xs text-on-surface-variant">
                              {selectedProposal.plan.risks.map((r, ri) => (
                                <li key={ri}>{r}</li>
                              ))}
                            </ul>
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                )}

                {/* Diff Inspect Per File */}
                <div className="space-y-4">
                  <h3 className="font-headline-md text-headline-md text-on-surface font-bold">
                    File Modifications
                  </h3>
                  {(selectedProposal.changes || []).map((change, idx) => {
                    const filename = change.path.split(/[\\/]/).pop();
                    const isNewFile = !change.original || !change.original.trim();

                    return (
                      <div key={idx} className="bg-surface-container-low border border-surface-variant rounded-xl overflow-hidden shadow-md">
                        <div className="p-3 bg-surface-container-high/60 border-b border-surface-variant flex items-center justify-between">
                          <div className="flex items-center gap-2 font-mono text-xs font-semibold text-on-surface">
                            <FileCode size={14} className="text-primary" />
                            <span>{filename}</span>
                            <span className="text-on-surface-variant text-[11px]">({change.path})</span>
                          </div>
                          {isNewFile && (
                            <span className="text-[10px] font-bold text-emerald-400 uppercase font-mono bg-emerald-500/10 border border-emerald-500/30 px-2 py-0.5 rounded">
                              New File
                            </span>
                          )}
                        </div>
                        {isNewFile ? (
                          <div className="p-4 bg-emerald-500/5 max-h-72 overflow-y-auto font-code-sm text-code-sm font-mono">
                            <div className="text-emerald-400 font-bold uppercase tracking-wider text-[10px] mb-2">Creating File</div>
                            <pre className="whitespace-pre text-on-surface">{change.updated}</pre>
                          </div>
                        ) : (
                          <div className="grid grid-cols-1 md:grid-cols-2 divide-y md:divide-y-0 md:divide-x divide-surface-variant font-code-sm text-code-sm font-mono">
                            <div className="p-4 bg-error/5 max-h-72 overflow-y-auto">
                              <div className="text-error font-bold uppercase tracking-wider text-[10px] mb-2">Original Code</div>
                              <pre className="whitespace-pre text-on-surface-variant">{change.original}</pre>
                            </div>
                            <div className="p-4 bg-primary-container/5 max-h-72 overflow-y-auto">
                              <div className="text-primary-container font-bold uppercase tracking-wider text-[10px] mb-2">Proposed Changes</div>
                              <pre className="whitespace-pre text-on-surface">{change.updated}</pre>
                            </div>
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            </>
          ) : (
            <div className="flex-1 flex flex-col items-center justify-center text-on-surface-variant/50 p-12 text-center text-xs space-y-2">
              <span className="material-symbols-outlined text-4xl text-outline">visibility</span>
              <span>Select an agent proposal from the list to review, apply, or reject file updates.</span>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
