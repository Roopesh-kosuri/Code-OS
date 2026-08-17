import { useEffect, useState } from "react";
import {
  Zap, Info, Play, CheckCircle2, XCircle, Clock, Check,
  AlertTriangle, RefreshCw, FileDiff, Sparkles, Split
} from "lucide-react";
import { api } from "../../lib/api";
import { useWorkspaceStore } from "../../stores/workspaceStore";
import { useAIStore } from "../../stores/aiStore";
import { ProviderSelector, type ProviderConfig } from "../../components/ui/ProviderSelector";
import { getPreset } from "../../lib/providerPresets";

interface DualAttemptResult {
  attempt: "A" | "B";
  model: string;
  provider: string;
  duration: number;
  proposal_id: string | null;
  summary: string;
  raw_output: string;
  changes: any[];
  diff: string;
  self_review: {
    approved: boolean;
    verdict: string;
  };
}

interface DualCoderSession {
  id: string;
  workspace: string;
  task_description: string;
  status: string;
  total_duration: number;
  attempt_a: DualAttemptResult;
  attempt_b: DualAttemptResult;
  created_at: string;
}

export function DualCoderPanel() {
  const currentWorkspace = useWorkspaceStore((state) => state.currentWorkspace);
  const [taskText, setTaskText] = useState("");
  const [loading, setLoading] = useState(false);
  const [session, setSession] = useState<DualCoderSession | null>(null);

  const [appliedProposalId, setAppliedProposalId] = useState<string | null>(null);
  const [applying, setApplying] = useState(false);

  // Model A and Model B configs
  const [configA, setConfigA] = useState<ProviderConfig>({
    preset: "auto",
    model: "",
  });
  const [configB, setConfigB] = useState<ProviderConfig>({
    preset: "auto",
    model: "",
  });

  const [configuredKeys, setConfiguredKeys] = useState<string[]>([]);
  const models = useAIStore((s) => s.models);

  useEffect(() => {
    void api.get<{ provider_id: string; configured: boolean }[]>("/api/settings/api-keys")
      .then((keys) => setConfiguredKeys(keys.filter((k) => k.configured).map((k) => k.provider_id)))
      .catch(() => undefined);
  }, []);

  const buildModelPayload = (config: ProviderConfig) => {
    const presetObj = getPreset(config.preset);
    return {
      provider: presetObj?.provider || (config.preset === "ollama" ? "ollama" : "openai-compatible"),
      preset: config.preset,
      model: config.model || presetObj?.model_example || "llama3",
      base_url: config.base_url || presetObj?.base_url,
      api_key_provider: config.api_key_provider || presetObj?.api_key_provider,
    };
  };

  const handleRunDualCoder = async () => {
    if (!currentWorkspace || !taskText.trim()) return;
    setLoading(true);
    setAppliedProposalId(null);
    try {
      const res = await api.post<DualCoderSession>("/api/dual-coder/execute", {
        workspace: currentWorkspace.path,
        task_description: taskText,
        model_a: buildModelPayload(configA),
        model_b: buildModelPayload(configB),
      });
      setSession(res);
    } catch (err) {
      alert("Dual Coder execution failed: " + (err instanceof Error ? err.message : String(err)));
    } finally {
      setLoading(false);
    }
  };

  const handleApplyCandidate = async (proposalId: string) => {
    if (!proposalId) return;
    setApplying(true);
    try {
      await api.post(`/api/ai/edit-proposals/${proposalId}/apply`);
      setAppliedProposalId(proposalId);
      window.dispatchEvent(new CustomEvent("code-os:proposal-applied", { detail: proposalId }));
    } catch (err) {
      alert("Failed to apply candidate proposal: " + (err instanceof Error ? err.message : String(err)));
    } finally {
      setApplying(false);
    }
  };

  if (!currentWorkspace) {
    return (
      <section className="flex h-full flex-col items-center justify-center p-4 text-center space-y-3 select-none bg-[#131314] text-on-surface font-mono">
        <Zap size={32} className="text-amber-500/60 animate-pulse" />
        <span className="text-xs text-slate-400">Open a workspace to access Dual Coder for quick tasks.</span>
      </section>
    );
  }

  return (
    <main data-testid="dual-coder-panel" className="flex-1 overflow-y-auto p-4 md:p-6 flex flex-col gap-6 bg-[var(--surface)] text-on-surface h-full select-none font-mono">
      {/* Permanent Scope Banner */}
      <div className="bg-amber-500/10 border border-amber-500/30 text-amber-300 px-4 py-2.5 rounded-lg flex items-center gap-2.5 text-xs font-bold shrink-0">
        <Info size={16} className="shrink-0 text-amber-400" />
        <span>For small tasks only — big task support is coming in a future update.</span>
      </div>

      {/* Page Header */}
      <div className="flex justify-between items-center pb-2 border-b border-white/5 flex-wrap gap-3">
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-lg bg-amber-500/10 border border-amber-500/30 text-amber-400">
            <Split size={24} />
          </div>
          <div>
            <h1 className="font-bold text-on-surface text-base sm:text-lg tracking-tight">Dual Coder</h1>
            <p className="text-xs text-on-surface-variant">Parallel 2-model quick attempt generator & side-by-side comparison</p>
          </div>
        </div>
      </div>

      {/* Task Prompt & Dual Model Controls */}
      <div className="glass-panel p-4 rounded-xl border border-white/5 bg-surface-container-lowest flex flex-col gap-4">
        <div>
          <label className="text-xs font-bold text-slate-300 block mb-1.5 uppercase tracking-wider">
            Quick Task Instruction
          </label>
          <textarea
            rows={2}
            value={taskText}
            onChange={(e) => setTaskText(e.target.value)}
            placeholder="e.g. Add a helper function to format dates as ISO strings, or fix styling in header..."
            className="w-full bg-surface-container text-on-surface text-xs border border-white/10 focus:border-amber-500/50 p-3 rounded-lg outline-none font-mono resize-none"
          />
        </div>

        {/* Dual Model Pickers */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 pt-1">
          <div className="p-3 rounded-lg bg-surface-container border border-white/5 flex flex-col gap-2">
            <span className="text-[11px] font-bold text-cyan-400 uppercase tracking-wide flex items-center gap-1.5">
              <span>🤖 Model A (Candidate 1)</span>
            </span>
            <ProviderSelector
              value={configA}
              onChange={setConfigA}
              configuredKeys={configuredKeys}
              models={models}
              compact
            />
          </div>

          <div className="p-3 rounded-lg bg-surface-container border border-white/5 flex flex-col gap-2">
            <span className="text-[11px] font-bold text-violet-400 uppercase tracking-wide flex items-center gap-1.5">
              <span>🤖 Model B (Candidate 2)</span>
            </span>
            <ProviderSelector
              value={configB}
              onChange={setConfigB}
              configuredKeys={configuredKeys}
              models={models}
              compact
            />
          </div>
        </div>

        <div className="flex justify-end pt-1">
          <button
            onClick={() => void handleRunDualCoder()}
            disabled={loading || !taskText.trim()}
            className="bg-amber-500 hover:bg-amber-400 text-slate-950 px-6 py-2.5 rounded-full text-xs font-bold transition-all flex items-center gap-2 shadow-[0_0_15px_rgba(245,158,11,0.2)] disabled:opacity-40"
          >
            {loading ? (
              <>
                <RefreshCw size={14} className="animate-spin" />
                <span>Running Both Models in Parallel...</span>
              </>
            ) : (
              <>
                <Zap size={14} />
                <span>Run Dual Coder</span>
              </>
            )}
          </button>
        </div>
      </div>

      {/* Side-by-Side Comparison Section */}
      {session ? (
        <div className="flex flex-col gap-4">
          <div className="flex justify-between items-center text-xs text-slate-400 font-bold uppercase tracking-wider">
            <span>Side-by-Side Candidate Outputs</span>
            <span>Total Time: {session.total_duration}s</span>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            {/* Attempt A Card */}
            <div className="glass-panel p-4 rounded-xl border border-cyan-500/20 bg-surface-container-lowest flex flex-col justify-between gap-3 relative">
              <div className="flex justify-between items-start gap-2 border-b border-white/5 pb-3">
                <div>
                  <span className="text-[10px] font-bold text-cyan-400 uppercase tracking-wider block">Candidate Attempt A</span>
                  <h3 className="text-xs font-bold text-on-surface mt-0.5">{session.attempt_a?.model || "Model A"}</h3>
                  <span className="text-[10px] text-slate-400 font-mono">Provider: {session.attempt_a?.provider || "N/A"}</span>
                </div>
                <div className="flex flex-col items-end gap-1">
                  <span className={`text-[9px] px-2 py-0.5 rounded border font-bold uppercase ${
                    session.attempt_a?.self_review?.approved ? "bg-emerald-950/60 border-emerald-600/40 text-emerald-300" : "bg-rose-950/60 border-rose-600/40 text-rose-300"
                  }`}>
                    {session.attempt_a?.self_review?.approved ? "Self-Verified" : "Attempt Failed"}
                  </span>
                  <span className="text-[10px] text-slate-400 font-mono flex items-center gap-1">
                    <Clock size={10} />
                    {session.attempt_a?.duration ?? 0}s
                  </span>
                </div>
              </div>

              {/* Summary & Diff Preview */}
              <div className="flex flex-col gap-2">
                <p className="text-xs text-slate-300 leading-relaxed">{session.attempt_a?.summary || "No summary available"}</p>

                <div className="bg-surface-container p-3 rounded-lg border border-white/5 font-mono text-[11px] max-h-64 overflow-y-auto overflow-x-auto text-slate-200">
                  <pre className="whitespace-pre-wrap">{session.attempt_a?.diff || "(No diff output)"}</pre>
                </div>
              </div>

              {/* Apply Action Button */}
              <div className="pt-2 border-t border-white/5 flex justify-end">
                {session.attempt_a?.proposal_id ? (
                  appliedProposalId === session.attempt_a.proposal_id ? (
                    <div className="px-4 py-2 rounded bg-emerald-950/60 border border-emerald-500/40 text-emerald-300 text-xs font-bold flex items-center gap-1.5">
                      <Check size={14} />
                      <span>Output A Applied</span>
                    </div>
                  ) : (
                    <button
                      onClick={() => void handleApplyCandidate(session.attempt_a.proposal_id!)}
                      disabled={applying}
                      className="bg-cyan-500/20 text-cyan-300 border border-cyan-500/40 hover:bg-cyan-500/30 px-4 py-2 rounded-lg text-xs font-bold transition-all flex items-center gap-1.5"
                    >
                      <FileDiff size={14} />
                      <span>Apply Candidate Output A</span>
                    </button>
                  )
                ) : (
                  <span className="text-xs text-rose-400 italic">No proposal generated</span>
                )}
              </div>
            </div>

            {/* Attempt B Card */}
            <div className="glass-panel p-4 rounded-xl border border-violet-500/20 bg-surface-container-lowest flex flex-col justify-between gap-3 relative">
              <div className="flex justify-between items-start gap-2 border-b border-white/5 pb-3">
                <div>
                  <span className="text-[10px] font-bold text-violet-400 uppercase tracking-wider block">Candidate Attempt B</span>
                  <h3 className="text-xs font-bold text-on-surface mt-0.5">{session.attempt_b?.model || "Model B"}</h3>
                  <span className="text-[10px] text-slate-400 font-mono">Provider: {session.attempt_b?.provider || "N/A"}</span>
                </div>
                <div className="flex flex-col items-end gap-1">
                  <span className={`text-[9px] px-2 py-0.5 rounded border font-bold uppercase ${
                    session.attempt_b?.self_review?.approved ? "bg-emerald-950/60 border-emerald-600/40 text-emerald-300" : "bg-rose-950/60 border-rose-600/40 text-rose-300"
                  }`}>
                    {session.attempt_b?.self_review?.approved ? "Self-Verified" : "Attempt Failed"}
                  </span>
                  <span className="text-[10px] text-slate-400 font-mono flex items-center gap-1">
                    <Clock size={10} />
                    {session.attempt_b?.duration ?? 0}s
                  </span>
                </div>
              </div>

              {/* Summary & Diff Preview */}
              <div className="flex flex-col gap-2">
                <p className="text-xs text-slate-300 leading-relaxed">{session.attempt_b?.summary || "No summary available"}</p>

                <div className="bg-surface-container p-3 rounded-lg border border-white/5 font-mono text-[11px] max-h-64 overflow-y-auto overflow-x-auto text-slate-200">
                  <pre className="whitespace-pre-wrap">{session.attempt_b?.diff || "(No diff output)"}</pre>
                </div>
              </div>

              {/* Apply Action Button */}
              <div className="pt-2 border-t border-white/5 flex justify-end">
                {session.attempt_b?.proposal_id ? (
                  appliedProposalId === session.attempt_b.proposal_id ? (
                    <div className="px-4 py-2 rounded bg-emerald-950/60 border border-emerald-500/40 text-emerald-300 text-xs font-bold flex items-center gap-1.5">
                      <Check size={14} />
                      <span>Output B Applied</span>
                    </div>
                  ) : (
                    <button
                      onClick={() => void handleApplyCandidate(session.attempt_b.proposal_id!)}
                      disabled={applying}
                      className="bg-violet-500/20 text-violet-300 border border-violet-500/40 hover:bg-violet-500/30 px-4 py-2 rounded-lg text-xs font-bold transition-all flex items-center gap-1.5"
                    >
                      <FileDiff size={14} />
                      <span>Apply Candidate Output B</span>
                    </button>
                  )
                ) : (
                  <span className="text-xs text-rose-400 italic">No proposal generated</span>
                )}
              </div>
            </div>
          </div>
        </div>
      ) : (
        /* Empty State */
        <div className="flex-1 glass-panel rounded-xl border border-white/5 flex flex-col items-center justify-center p-8 text-center space-y-3">
          <div className="p-3.5 rounded-full bg-amber-500/10 border border-amber-500/30 text-amber-400">
            <Split size={32} />
          </div>
          <div>
            <h2 className="text-sm font-bold text-on-surface">Dual Coder Quick Comparison Ready</h2>
            <p className="text-xs text-slate-400 max-w-md mt-1 leading-relaxed">
              Enter a small coding instruction above and pick two models to compare two candidate solutions generated independently in parallel.
            </p>
          </div>
        </div>
      )}
    </main>
  );
}
