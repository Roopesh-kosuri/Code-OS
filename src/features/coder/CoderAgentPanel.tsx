import { useEffect, useState } from "react";
import {
  Code2, Info, Play, CheckCircle2, XCircle, Clock, Check,
  RefreshCw, FileDiff, Sparkles, TestTube2, ShieldCheck, Terminal
} from "lucide-react";
import { api } from "../../lib/api";
import { useWorkspaceStore } from "../../stores/workspaceStore";
import { useAIStore } from "../../stores/aiStore";
import { ProviderSelector, type ProviderConfig } from "../../components/ui/ProviderSelector";
import { getPreset } from "../../lib/providerPresets";

interface CoderModeResult {
  status: string;
  duration: number;
  proposal: {
    id: string | null;
    summary: string;
    diff: string;
    changes: any[];
    raw_output: string;
  };
  test_result: {
    tested: boolean;
    runner: string | null;
    command?: string;
    passed: boolean;
    summary: string;
    raw_output?: string;
  };
}

export function CoderAgentPanel() {
  const currentWorkspace = useWorkspaceStore((state) => state.currentWorkspace);
  const [taskText, setTaskText] = useState("");
  const [targetFile, setTargetFile] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<CoderModeResult | null>(null);

  const [appliedProposalId, setAppliedProposalId] = useState<string | null>(null);
  const [applying, setApplying] = useState(false);
  const [showRawTestLogs, setShowRawTestLogs] = useState(false);

  const [providerConfig, setProviderConfig] = useState<ProviderConfig>({
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

  const handleRunCoder = async () => {
    if (!currentWorkspace || !taskText.trim()) return;
    setLoading(true);
    setAppliedProposalId(null);
    try {
      const res = await api.post<CoderModeResult>("/api/agents/coder-mode/execute", {
        workspace: currentWorkspace.path,
        user_request: taskText,
        target_file: targetFile.trim() || undefined,
        provider_config: buildModelPayload(providerConfig),
      });
      setResult(res);
    } catch (err) {
      alert("Coder Agent execution failed: " + (err instanceof Error ? err.message : String(err)));
    } finally {
      setLoading(false);
    }
  };

  const handleApplyProposal = async (proposalId: string) => {
    if (!proposalId) return;
    setApplying(true);
    try {
      await api.post(`/api/ai/edit-proposals/${proposalId}/apply`);
      setAppliedProposalId(proposalId);
    } catch (err) {
      alert("Failed to apply proposal: " + (err instanceof Error ? err.message : String(err)));
    } finally {
      setApplying(false);
    }
  };

  if (!currentWorkspace) {
    return (
      <section className="flex h-full flex-col items-center justify-center p-4 text-center space-y-3 select-none bg-[var(--surface)] text-on-surface font-mono">
        <Code2 size={32} className="text-cyan-400 animate-pulse" />
        <span className="text-xs text-slate-400">Open a workspace to use the Coder Agent pipeline.</span>
      </section>
    );
  }

  return (
    <main data-testid="coder-agent-panel" className="flex-1 overflow-y-auto p-4 md:p-6 flex flex-col gap-6 bg-[var(--surface)] text-on-surface h-full select-none font-mono">
      {/* Scope Banner */}
      <div className="bg-cyan-500/10 border border-cyan-500/30 text-cyan-300 px-4 py-2.5 rounded-lg flex items-center gap-2.5 text-xs font-bold shrink-0">
        <Info size={16} className="shrink-0 text-cyan-400" />
        <span>Medium-weight fast task pipeline (CoderAgent + TesterAgent). Skips multi-step planning for Duo Loop speed.</span>
      </div>

      {/* Header */}
      <div className="flex justify-between items-center pb-2 border-b border-white/5 flex-wrap gap-3">
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-lg bg-cyan-500/10 border border-cyan-500/30 text-cyan-400">
            <Code2 size={24} />
          </div>
          <div>
            <h1 className="font-bold text-on-surface text-base sm:text-lg tracking-tight">Coder Agent</h1>
            <p className="text-xs text-on-surface-variant">Single-model fast code generator + automated test suite verifier</p>
          </div>
        </div>
      </div>

      {/* Task Input & Controls */}
      <div className="glass-panel p-4 rounded-xl border border-white/5 bg-surface-container-lowest flex flex-col gap-4">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div className="md:col-span-2">
            <label className="text-xs font-bold text-slate-300 block mb-1.5 uppercase tracking-wider">
              Medium Task Instruction
            </label>
            <textarea
              rows={3}
              value={taskText}
              onChange={(e) => setTaskText(e.target.value)}
              placeholder="e.g. Add input validation to the calculator divide function and handle negative numbers gracefully..."
              className="w-full bg-surface-container text-on-surface text-xs border border-white/10 focus:border-cyan-500/50 p-3 rounded-lg outline-none font-mono resize-none"
            />
          </div>

          <div className="flex flex-col gap-3">
            <div>
              <label className="text-xs font-bold text-slate-300 block mb-1.5 uppercase tracking-wider">
                Target File (Optional)
              </label>
              <input
                type="text"
                value={targetFile}
                onChange={(e) => setTargetFile(e.target.value)}
                placeholder="e.g. src/calculator.js"
                className="w-full bg-surface-container text-on-surface text-xs border border-white/10 focus:border-cyan-500/50 px-3 py-2 rounded-lg outline-none font-mono"
              />
            </div>

            <div>
              <label className="text-xs font-bold text-slate-300 block mb-1.5 uppercase tracking-wider">
                LLM Provider Model
              </label>
              <ProviderSelector
                value={providerConfig}
                onChange={setProviderConfig}
                configuredKeys={configuredKeys}
                models={models}
                compact
              />
            </div>
          </div>
        </div>

        <div className="flex justify-end pt-1">
          <button
            onClick={() => void handleRunCoder()}
            disabled={loading || !taskText.trim()}
            className="bg-cyan-500 hover:bg-cyan-400 text-slate-950 px-6 py-2.5 rounded-full text-xs font-bold transition-all flex items-center gap-2 shadow-[0_0_15px_rgba(6,182,212,0.25)] disabled:opacity-40"
          >
            {loading ? (
              <>
                <RefreshCw size={14} className="animate-spin" />
                <span>Generating & Testing Proposal...</span>
              </>
            ) : (
              <>
                <Sparkles size={14} />
                <span>Run Coder Agent</span>
              </>
            )}
          </button>
        </div>
      </div>

      {/* Results View */}
      {result ? (
        <div className="flex flex-col gap-4">
          <div className="flex justify-between items-center text-xs text-slate-400 font-bold uppercase tracking-wider">
            <span>Coder Agent Execution Results</span>
            <span className="text-cyan-400">Total Duration: {result.duration}s</span>
          </div>

          {/* Tester Verification Status Card */}
          <div className={`glass-panel p-4 rounded-xl border ${
            result.test_result.tested
              ? result.test_result.passed
                ? "border-emerald-500/30 bg-emerald-950/20"
                : "border-rose-500/30 bg-rose-950/20"
              : "border-white/5 bg-surface-container-lowest"
          } flex flex-col gap-2`}>
            <div className="flex justify-between items-center">
              <div className="flex items-center gap-2">
                <TestTube2 size={18} className={result.test_result.tested ? (result.test_result.passed ? "text-emerald-400" : "text-rose-400") : "text-slate-400"} />
                <span className="text-xs font-bold text-on-surface uppercase tracking-wider">Automated Test Verification</span>
              </div>
              <span className={`text-[10px] px-2 py-0.5 rounded border font-bold uppercase ${
                result.test_result.tested
                  ? result.test_result.passed
                    ? "bg-emerald-950/60 border-emerald-600/40 text-emerald-300"
                    : "bg-rose-950/60 border-rose-600/40 text-rose-300"
                  : "bg-slate-800/60 border-slate-700/50 text-slate-400"
              }`}>
                {result.test_result.tested ? (result.test_result.passed ? "✓ Tests Passed" : "✕ Tests Failed") : "No Runner Detected"}
              </span>
            </div>

            <p className="text-xs text-slate-300">{result.test_result.summary}</p>

            {result.test_result.raw_output && (
              <div className="pt-2">
                <button
                  onClick={() => setShowRawTestLogs(!showRawTestLogs)}
                  className="text-[11px] text-cyan-400 flex items-center gap-1 hover:underline font-bold"
                >
                  <Terminal size={12} />
                  <span>{showRawTestLogs ? "Hide Test Output Logs" : "View Raw Test Output Logs"}</span>
                </button>
                {showRawTestLogs && (
                  <pre className="mt-2 p-3 rounded-lg bg-surface-container border border-white/5 text-[11px] font-mono text-slate-300 max-h-48 overflow-y-auto whitespace-pre-wrap">
                    {result.test_result.raw_output}
                  </pre>
                )}
              </div>
            )}
          </div>

          {/* Proposal & Diff Card */}
          <div className="glass-panel p-5 rounded-xl border border-white/5 bg-surface-container-lowest flex flex-col gap-3">
            <div className="flex justify-between items-center border-b border-white/5 pb-3">
              <div>
                <span className="text-[10px] font-bold text-cyan-400 uppercase tracking-wider block">Generated Code Proposal</span>
                <h3 className="text-xs font-bold text-on-surface mt-0.5">{result.proposal.summary}</h3>
              </div>
              {result.proposal.id && (
                <div>
                  {appliedProposalId === result.proposal.id ? (
                    <div className="px-4 py-2 rounded bg-emerald-950/60 border border-emerald-500/40 text-emerald-300 text-xs font-bold flex items-center gap-1.5">
                      <Check size={14} />
                      <span>Proposal Applied to Workspace</span>
                    </div>
                  ) : (
                    <button
                      onClick={() => void handleApplyProposal(result.proposal.id!)}
                      disabled={applying}
                      className="bg-cyan-500/20 text-cyan-300 border border-cyan-500/40 hover:bg-cyan-500/30 px-4 py-2 rounded-lg text-xs font-bold transition-all flex items-center gap-1.5"
                    >
                      <FileDiff size={14} />
                      <span>Apply Edit Proposal</span>
                    </button>
                  )}
                </div>
              )}
            </div>

            <div className="bg-surface-container p-3.5 rounded-lg border border-white/5 font-mono text-[11px] max-h-96 overflow-y-auto overflow-x-auto text-slate-200">
              <pre className="whitespace-pre-wrap">{result.proposal.diff}</pre>
            </div>
          </div>
        </div>
      ) : (
        /* Empty State */
        <div className="flex-1 glass-panel rounded-xl border border-white/5 flex flex-col items-center justify-center p-8 text-center space-y-3">
          <div className="p-3.5 rounded-full bg-cyan-500/10 border border-cyan-500/30 text-cyan-400">
            <Code2 size={32} />
          </div>
          <div>
            <h2 className="text-sm font-bold text-on-surface">Coder Agent Fast Pipeline Ready</h2>
            <p className="text-xs text-slate-400 max-w-md mt-1 leading-relaxed">
              Enter a medium-complexity programming instruction above to generate a tested code edit proposal at Duo-Loop speed.
            </p>
          </div>
        </div>
      )}
    </main>
  );
}
