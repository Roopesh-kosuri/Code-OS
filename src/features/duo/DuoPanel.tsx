import { useState, useEffect, useRef } from "react";
import {
  Play,
  Square,
  ChevronDown,
  ChevronRight,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Clock,
  Loader2,
  FileDiff,
  Zap,
  RotateCcw,
  RefreshCw,
  Check,
  X,
  Eye,
  Sparkles,
} from "lucide-react";
import { ProviderSelector, type ProviderConfig } from "../../components/ui/ProviderSelector";
import { PROVIDER_PRESETS } from "../../lib/providerPresets";
import { useWorkspaceStore } from "../../stores/workspaceStore";
import { useAIStore } from "../../stores/aiStore";
import { useEditorStore } from "../../stores/editorStore";
import { api } from "../../lib/api";

interface ModelConfig {
  provider: "ollama" | "openai" | "anthropic" | "groq" | "deepseek" | "mistral" | "openrouter" | "nvidia" | "gemini" | string;
  model: string;
  base_url?: string;
  temperature?: number;
}

interface CriticIssue {
  description: string;
  severity: "high" | "medium" | "low" | string;
  suggested_fix?: string;
}

interface CriticVerdict {
  approved: boolean;
  issues: CriticIssue[];
  reasoning: string;
}

interface DuoRound {
  round_number: number;
  generator_output: string;
  proposal_id: string | null;
  critic_verdict: CriticVerdict | null;
  created_at: string;
  duration_sec?: number;
}

interface DuoSession {
  id: string;
  workspace: string;
  task_description: string;
  critic_instructions?: string;
  status: "running" | "approved" | "unresolved" | "cancelled" | "error" | "waiting_for_recovery";
  current_round: number;
  max_rounds: number;
  rounds: DuoRound[];
  final_proposal_id: string | null;
  generator: ModelConfig;
  critic: ModelConfig;
  created_at: string;
}

export function DuoPanel({ compact = false }: { compact?: boolean }) {
  const workspace = useWorkspaceStore((state) => state.currentWorkspace);
  const models = useAIStore((state) => state.models);
  const globalModel = useAIStore((state) => state.model);

  const [generatorTask, setGeneratorTask] = useState("");
  const [criticInstructions, setCriticInstructions] = useState("");
  const [maxRounds, setMaxRounds] = useState(5);

  const [genConfig, setGenConfig] = useState<ProviderConfig>({
    preset: "ollama",
    model: globalModel || "llama3",
  });

  const [criticConfig, setCriticConfig] = useState<ProviderConfig>({
    preset: "anthropic",
    model: "claude-3-5-sonnet-20241022",
  });

  const [activeSession, setActiveSession] = useState<DuoSession | null>(null);
  const [loading, setLoading] = useState(false);
  const [actionLoading, setActionLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [applyingProposal, setApplyingProposal] = useState(false);
  const [appliedSuccess, setAppliedSuccess] = useState(false);
  const [recoveryProvider, setRecoveryProvider] = useState<string>("groq");
  const [recoveryModel, setRecoveryModel] = useState<string>("llama-3.3-70b-versatile");

  // Poll active session
  const fetchSession = async () => {
    if (!workspace) return;
    try {
      if (activeSession?.id) {
        const session = await api.get<DuoSession>(`/api/duo/sessions/${activeSession.id}`);
        if (session) {
          setActiveSession(session);
          return;
        }
      }

      // Check most recent session for workspace
      const sessions = await api.get<DuoSession[]>("/api/duo/sessions", { workspace: workspace.path });
      if (Array.isArray(sessions) && sessions.length > 0) {
        const running = sessions.find((s) => s.status === "running" || s.status === "waiting_for_recovery");
        if (running) {
          const detailed = await api.get<DuoSession>(`/api/duo/sessions/${running.id}`);
          setActiveSession(detailed);
        }
      }
    } catch {
      // ignore
    }
  };

  useEffect(() => {
    void fetchSession();
    const interval = setInterval(() => {
      if (activeSession?.status === "running" || activeSession?.status === "waiting_for_recovery") {
        void fetchSession();
      }
    }, 2000);
    return () => clearInterval(interval);
  }, [workspace?.path, activeSession?.id, activeSession?.status]);

  const handleLaunch = async () => {
    if (!generatorTask.trim() || !workspace) return;
    setLoading(true);
    setError(null);
    setAppliedSuccess(false);

    try {
      const payload = {
        workspace: workspace.path,
        task_description: generatorTask.trim(),
        critic_instructions: criticInstructions.trim() || undefined,
        max_rounds: maxRounds,
        generator: {
          provider: genConfig.preset,
          model: genConfig.model,
          base_url: genConfig.base_url,
        },
        critic: {
          provider: criticConfig.preset,
          model: criticConfig.model,
          base_url: criticConfig.base_url,
        },
      };

      const session = await api.post<DuoSession>("/api/duo/sessions", payload);
      setActiveSession(session);
    } catch (err: any) {
      setError(err?.message || "Failed to launch Duo Loop");
    } finally {
      setLoading(false);
    }
  };

  const handleStop = async () => {
    if (!activeSession) return;
    setActionLoading(true);
    try {
      const updated = await api.post<DuoSession>(`/api/duo/sessions/${activeSession.id}/cancel`);
      setActiveSession(updated);
    } catch (err: any) {
      setError(err?.message || "Failed to stop Duo session");
    } finally {
      setActionLoading(false);
    }
  };

  const handleRecover = async (
    action: "retry" | "switch_to_api" | "change_model" | "cancel",
    modelPayload?: { provider?: string; model?: string; api_key_provider?: string }
  ) => {
    if (!activeSession) return;
    setActionLoading(true);
    try {
      await api.post(`/api/duo/sessions/${activeSession.id}/recover`, {
        action,
        provider: modelPayload?.provider,
        model: modelPayload?.model,
        api_key_provider: modelPayload?.api_key_provider,
      });
      await fetchSession();
    } catch (err: any) {
      setError(err?.message || "Failed to submit recovery action");
    } finally {
      setActionLoading(false);
    }
  };

  const handleApplyFinalProposal = async () => {
    if (!activeSession?.final_proposal_id) return;
    setApplyingProposal(true);
    try {
      const res = await api.post<{ changes?: { path: string }[] }>(`/api/ai/edit-proposals/${activeSession.final_proposal_id}/apply`);
      setAppliedSuccess(true);
      window.dispatchEvent(new CustomEvent("code-os:proposal-applied", { detail: activeSession.final_proposal_id }));
      await useWorkspaceStore.getState().refreshTree();

      // Open applied files in editor workspace
      if (res?.changes && res.changes.length > 0) {
        for (const change of res.changes) {
          void useEditorStore.getState().openFile(change.path);
        }
      }
    } catch (err: any) {
      setError(err?.message || "Failed to apply final proposal");
    } finally {
      setApplyingProposal(false);
    }
  };

  const isRunning = Boolean(activeSession && activeSession.status === "running");
  const isPausedRecovery = Boolean(activeSession && activeSession.status === "waiting_for_recovery");
  const isApproved = Boolean(activeSession && activeSession.status === "approved");
  const currentRoundNum = activeSession?.current_round ?? 0;
  const maxRoundNum = activeSession?.max_rounds ?? maxRounds;

  return (
    <div className="flex-1 flex flex-col h-full overflow-y-auto bg-background text-on-surface p-6 font-ui-label-reg text-ui-label-reg select-none antialiased">
      {/* ── Top Header ──────────────────────────────────────────────────────── */}
      <div className="flex justify-between items-center mb-6 shrink-0">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-primary/10 border border-primary/20 flex items-center justify-center text-primary">
            <span className="material-symbols-outlined text-lg">sync_alt</span>
          </div>
          <h1 className="font-headline-md text-headline-md text-on-surface font-bold tracking-tight">
            Duo Loop
          </h1>
          <button 
            onClick={() => void fetchSession()}
            className="p-1.5 rounded-full bg-surface-container-low hover:bg-surface-container-high text-on-surface-variant hover:text-on-surface transition-colors cursor-pointer border border-white/5"
            title="Refresh Status"
          >
            <RefreshCw size={13} />
          </button>
        </div>

        <div className="flex items-center gap-4">
          <div className="px-3.5 py-1.5 rounded-full bg-surface-container-low border border-white/5 font-caption text-caption text-on-surface-variant flex items-center gap-2">
            <span className={`w-2 h-2 rounded-full ${
              isRunning
                ? "bg-primary-container animate-pulse"
                : isPausedRecovery
                  ? "bg-amber-400 animate-pulse"
                  : isApproved
                    ? "bg-emerald-400"
                    : "bg-outline"
            }`} />
            <span>
              {activeSession
                ? `Round ${currentRoundNum}/${maxRoundNum} (${activeSession.status})`
                : `Round 0/${maxRounds} (Ready)`}
            </span>
          </div>

          {isRunning ? (
            <button
              onClick={handleStop}
              disabled={actionLoading}
              className="px-6 py-2.5 rounded-full font-ui-label-bold text-ui-label-bold bg-error text-on-error hover:bg-error-container hover:text-on-error-container transition-all flex items-center gap-2 shadow-lg cursor-pointer disabled:opacity-50"
            >
              <Square size={14} /> Stop Loop
            </button>
          ) : (
            <button
              onClick={handleLaunch}
              disabled={loading || !generatorTask.trim()}
              className="bg-primary-container hover:bg-primary-fixed text-[#001f24] font-ui-label-bold text-ui-label-bold px-8 py-3 rounded-full flex items-center gap-2 transition-all shadow-[0_0_20px_rgba(0,218,243,0.25)] hover:shadow-[0_0_30px_rgba(0,218,243,0.45)] hover:scale-[1.02] disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer"
            >
              <span className="material-symbols-outlined text-[18px]">play_arrow</span>
              <span>{loading ? "Starting Loop..." : "Launch Duo Loop"}</span>
            </button>
          )}
        </div>
      </div>

      {error && (
        <div className="mb-4 rounded-xl border border-error/40 bg-error/10 p-3 text-xs text-error flex items-center justify-between">
          <div className="flex items-center gap-2">
            <AlertTriangle size={16} />
            <span>{error}</span>
          </div>
          <button onClick={() => setError(null)} className="text-error hover:opacity-80">
            <X size={14} />
          </button>
        </div>
      )}

      {/* ── Active Session Alert & Recovery Banner (Priority 1) ──────────────── */}
      {isPausedRecovery && (
        <div className="danger-glow rounded-xl p-6 mb-6 flex flex-col gap-4 shadow-xl">
          <div className="flex items-start gap-3">
            <div className="p-2 rounded-full bg-amber-500/10 text-amber-400 shrink-0">
              <AlertTriangle size={22} />
            </div>
            <div className="flex-1">
              <h3 className="font-ui-label-bold text-ui-label-bold text-amber-400 text-base mb-1">
                Duo Loop Paused — Recovery Action Required
              </h3>
              <p className="text-xs text-on-surface leading-relaxed">
                The generator or critic model encountered an inference error (e.g. rate limit, connection timeout, or invalid JSON). Choose a recovery action to continue the loop:
              </p>
            </div>
          </div>

          {/* ── Dynamic Model Switcher Panel ── */}
          <div className="bg-surface/50 rounded-xl p-3.5 border border-outline/30 space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-xs font-semibold text-on-surface flex items-center gap-1.5">
                <Sparkles size={14} className="text-primary" />
                Select Replacement Model & Provider
              </span>
              <span className="text-[11px] text-on-surface-variant">Switch model to resume loop</span>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-2.5">
              <div>
                <label className="text-[11px] text-on-surface-variant font-medium block mb-1">Provider</label>
                <select
                  value={recoveryProvider}
                  onChange={(e) => {
                    const nextP = e.target.value;
                    setRecoveryProvider(nextP);
                    const preset = PROVIDER_PRESETS.find((p) => p.id === nextP);
                    if (preset?.model_example) {
                      setRecoveryModel(preset.model_example);
                    }
                  }}
                  className="w-full bg-surface-variant/40 border border-outline/40 rounded-lg px-2.5 py-1.5 text-xs text-on-surface focus:outline-none focus:border-primary"
                >
                  {PROVIDER_PRESETS.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.label} {p.group === "api" ? "(Cloud API)" : "(Local)"}
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label className="text-[11px] text-on-surface-variant font-medium block mb-1">Model Name / ID</label>
                <input
                  type="text"
                  value={recoveryModel}
                  onChange={(e) => setRecoveryModel(e.target.value)}
                  placeholder="e.g. llama-3.3-70b-versatile, gpt-4o"
                  className="w-full bg-surface-variant/40 border border-outline/40 rounded-lg px-2.5 py-1.5 text-xs text-on-surface focus:outline-none focus:border-primary font-mono"
                />
              </div>
            </div>

            {/* Quick Model Suggestions */}
            <div className="flex items-center gap-1.5 flex-wrap pt-1">
              <span className="text-[10px] text-on-surface-variant font-medium mr-1">Suggestions:</span>
              {recoveryProvider === "groq" && (
                <>
                  <button
                    type="button"
                    onClick={() => setRecoveryModel("llama-3.3-70b-versatile")}
                    className={`text-[10px] px-2 py-0.5 rounded-full border transition-all cursor-pointer ${recoveryModel === "llama-3.3-70b-versatile" ? "bg-primary text-[#001f24] border-primary font-bold shadow" : "bg-surface-variant/30 border-outline/40 hover:border-primary text-on-surface"}`}
                  >
                    llama-3.3-70b-versatile (Recommended)
                  </button>
                  <button
                    type="button"
                    onClick={() => setRecoveryModel("llama-3.1-8b-instant")}
                    className={`text-[10px] px-2 py-0.5 rounded-full border transition-all cursor-pointer ${recoveryModel === "llama-3.1-8b-instant" ? "bg-primary text-[#001f24] border-primary font-bold shadow" : "bg-surface-variant/30 border-outline/40 hover:border-primary text-on-surface"}`}
                  >
                    llama-3.1-8b-instant (Fast / High Quota)
                  </button>
                  <button
                    type="button"
                    onClick={() => setRecoveryModel("openai/gpt-oss-120b")}
                    className={`text-[10px] px-2 py-0.5 rounded-full border transition-all cursor-pointer ${recoveryModel === "openai/gpt-oss-120b" ? "bg-primary text-[#001f24] border-primary font-bold shadow" : "bg-surface-variant/30 border-outline/40 hover:border-primary text-on-surface"}`}
                  >
                    openai/gpt-oss-120b
                  </button>
                  <button
                    type="button"
                    onClick={() => setRecoveryModel("openai/gpt-oss-20b")}
                    className={`text-[10px] px-2 py-0.5 rounded-full border transition-all cursor-pointer ${recoveryModel === "openai/gpt-oss-20b" ? "bg-primary text-[#001f24] border-primary font-bold shadow" : "bg-surface-variant/30 border-outline/40 hover:border-primary text-on-surface"}`}
                  >
                    openai/gpt-oss-20b
                  </button>
                </>
              )}
              {recoveryProvider === "openai" && (
                <>
                  <button
                    type="button"
                    onClick={() => setRecoveryModel("gpt-4o")}
                    className={`text-[10px] px-2 py-0.5 rounded-full border transition-all cursor-pointer ${recoveryModel === "gpt-4o" ? "bg-primary text-[#001f24] border-primary font-bold shadow" : "bg-surface-variant/30 border-outline/40 hover:border-primary text-on-surface"}`}
                  >
                    gpt-4o
                  </button>
                  <button
                    type="button"
                    onClick={() => setRecoveryModel("gpt-4o-mini")}
                    className={`text-[10px] px-2 py-0.5 rounded-full border transition-all cursor-pointer ${recoveryModel === "gpt-4o-mini" ? "bg-primary text-[#001f24] border-primary font-bold shadow" : "bg-surface-variant/30 border-outline/40 hover:border-primary text-on-surface"}`}
                  >
                    gpt-4o-mini
                  </button>
                </>
              )}
              {recoveryProvider === "gemini" && (
                <>
                  <button
                    type="button"
                    onClick={() => setRecoveryModel("gemini-2.5-flash")}
                    className={`text-[10px] px-2 py-0.5 rounded-full border transition-all cursor-pointer ${recoveryModel === "gemini-2.5-flash" ? "bg-primary text-[#001f24] border-primary font-bold shadow" : "bg-surface-variant/30 border-outline/40 hover:border-primary text-on-surface"}`}
                  >
                    gemini-2.5-flash
                  </button>
                  <button
                    type="button"
                    onClick={() => setRecoveryModel("gemini-2.5-pro")}
                    className={`text-[10px] px-2 py-0.5 rounded-full border transition-all cursor-pointer ${recoveryModel === "gemini-2.5-pro" ? "bg-primary text-[#001f24] border-primary font-bold shadow" : "bg-surface-variant/30 border-outline/40 hover:border-primary text-on-surface"}`}
                  >
                    gemini-2.5-pro
                  </button>
                </>
              )}
            </div>
          </div>

          <div className="flex flex-wrap gap-2.5 pt-1">
            <button
              onClick={() => handleRecover("change_model", { provider: recoveryProvider, model: recoveryModel, api_key_provider: recoveryProvider })}
              disabled={actionLoading}
              className="px-4 py-2 rounded-full bg-primary text-[#001f24] font-ui-label-bold text-xs hover:bg-primary/90 transition-colors flex items-center gap-1.5 shadow-md cursor-pointer disabled:opacity-40"
            >
              <Sparkles size={13} />
              <span>Switch Model & Resume</span>
            </button>
            <button
              onClick={() => handleRecover("retry")}
              disabled={actionLoading}
              className="px-4 py-2 rounded-full bg-surface-variant text-on-surface font-ui-label-bold text-xs hover:bg-surface-variant/80 transition-colors flex items-center gap-1.5 border border-outline/30 cursor-pointer disabled:opacity-40"
            >
              <RotateCcw size={13} />
              <span>Retry Current Model</span>
            </button>
            <button
              onClick={() => handleRecover("cancel")}
              disabled={actionLoading}
              className="px-4 py-2 rounded-full border border-outline text-on-surface font-ui-label-bold text-xs hover:bg-surface-variant transition-colors cursor-pointer disabled:opacity-40"
            >
              Cancel Session
            </button>
          </div>
        </div>
      )}

      {/* ── Approved Session Banner ────────────────────────────────────────── */}
      {isApproved && activeSession?.final_proposal_id && (
        <div className="bg-emerald-500/10 border border-emerald-500/30 rounded-xl p-5 mb-6 flex items-center justify-between shadow-lg">
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-full bg-emerald-500/20 text-emerald-400">
              <CheckCircle2 size={20} />
            </div>
            <div>
              <h4 className="font-ui-label-bold text-ui-label-bold text-emerald-400">
                Critic Approved Final Implementation
              </h4>
              <p className="text-xs text-on-surface-variant mt-0.5">
                All verification criteria satisfied. Proposal #{activeSession.final_proposal_id.slice(0, 8)} is ready to apply to workspace.
              </p>
            </div>
          </div>

          <div className="flex items-center gap-3">
            <button
              onClick={() => {
                window.dispatchEvent(new CustomEvent("code-os:switch-top-view", { detail: "proposals" }));
              }}
              className="px-4 py-2 rounded-full border border-outline text-on-surface font-ui-label-bold text-xs hover:bg-surface-variant transition-colors cursor-pointer flex items-center gap-1.5"
            >
              <Eye size={13} />
              <span>Inspect Diff</span>
            </button>
            {appliedSuccess ? (
              <span className="px-5 py-2 rounded-full bg-emerald-500 text-[#001f24] font-ui-label-bold text-xs flex items-center gap-1.5">
                <Check size={14} /> Applied to Files
              </span>
            ) : (
              <button
                onClick={handleApplyFinalProposal}
                disabled={applyingProposal}
                className="px-6 py-2 rounded-full bg-emerald-400 text-[#001f24] font-ui-label-bold text-xs hover:bg-emerald-300 transition-all shadow-md cursor-pointer flex items-center gap-1.5 disabled:opacity-40"
              >
                {applyingProposal ? <Loader2 size={13} className="animate-spin" /> : <Check size={14} />}
                <span>Authorize &amp; Apply Changes</span>
              </button>
            )}
          </div>
        </div>
      )}

      {/* ── Top Grid: Task Division & Agent Configuration ──────────────────── */}
      <div className={`grid grid-cols-1 ${compact ? "gap-4" : "lg:grid-cols-2 gap-6"} mb-8`}>
        {/* Left Card: Task Division */}
        <div className="bg-surface-container-low rounded-xl border border-surface-container-high p-6 flex flex-col gap-4 shadow-lg">
          <div className="flex justify-between items-center border-b border-surface-variant pb-3">
            <h3 className="font-ui-label-bold text-ui-label-bold text-on-surface">Task Division</h3>
            <div className="flex items-center gap-2">
              <span className="font-caption text-caption text-on-surface-variant">Max Rounds</span>
              <input
                type="number"
                min={1}
                max={20}
                value={maxRounds}
                onChange={(e) => setMaxRounds(Math.max(1, Math.min(20, Number(e.target.value))))}
                disabled={isRunning}
                className="w-14 bg-[#131315] border border-surface-variant rounded px-2 py-1 text-xs font-mono text-center text-on-surface focus:border-primary-container focus:outline-none disabled:opacity-50"
              />
            </div>
          </div>

          <div>
            <label className="font-caption text-caption text-primary font-bold mb-1.5 block uppercase tracking-wider">
              Generator Task
            </label>
            <textarea
              value={generatorTask}
              onChange={(e) => setGeneratorTask(e.target.value)}
              disabled={isRunning}
              placeholder="Define the primary objective (e.g. Implement resilient WebSocket connection pool with automatic backoff)..."
              rows={4}
              className="w-full bg-[#131315] border border-surface-variant rounded-lg p-3 text-xs text-on-surface placeholder:text-outline-variant focus:border-primary-container focus:outline-none resize-none font-mono disabled:opacity-50"
            />
          </div>

          <div>
            <label className="font-caption text-caption text-tertiary-container font-bold mb-1.5 block uppercase tracking-wider">
              Critic Instructions (Strict Mode)
            </label>
            <textarea
              value={criticInstructions}
              onChange={(e) => setCriticInstructions(e.target.value)}
              disabled={isRunning}
              placeholder="Define constraints, security standards, and review criteria (e.g. Verify thread-safety, no memory leaks, edge cases handled)..."
              rows={4}
              className="w-full bg-[#131315] border border-surface-variant rounded-lg p-3 text-xs text-on-surface placeholder:text-outline-variant focus:border-primary-container focus:outline-none resize-none font-mono disabled:opacity-50"
            />
          </div>
        </div>

        {/* Right Card: Agent Configuration */}
        <div className="bg-surface-container-low rounded-xl border border-surface-container-high p-6 flex flex-col gap-4 shadow-lg">
          <h3 className="font-ui-label-bold text-ui-label-bold text-on-surface border-b border-surface-variant pb-3">
            Agent Configuration
          </h3>

          {/* Generator Role Sub-card */}
          <div className="bg-[#1e1f24] rounded-xl border border-white/5 p-4 space-y-3">
            <div className="flex items-center gap-2 text-xs font-bold text-on-surface">
              <span className="material-symbols-outlined text-primary text-[18px]">edit_note</span>
              <span>Generator Role</span>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="font-caption text-[11px] text-on-surface-variant mb-1 block">Provider</label>
                <select
                  value={genConfig.preset}
                  onChange={(e) => setGenConfig({ ...genConfig, preset: e.target.value })}
                  disabled={isRunning}
                  className="custom-select w-full bg-[#131315] border border-surface-variant rounded-lg px-2.5 py-1.5 text-xs text-on-surface focus:border-primary-container focus:outline-none disabled:opacity-50"
                >
                  <option value="ollama">Ollama (Local)</option>
                  <option value="openai">OpenAI</option>
                  <option value="anthropic">Anthropic</option>
                  <option value="groq">Groq</option>
                  <option value="deepseek">DeepSeek</option>
                </select>
              </div>
              <div>
                <label className="font-caption text-[11px] text-on-surface-variant mb-1 block">Model</label>
                <input
                  type="text"
                  value={genConfig.model}
                  onChange={(e) => setGenConfig({ ...genConfig, model: e.target.value })}
                  disabled={isRunning}
                  className="w-full bg-[#131315] border border-surface-variant rounded-lg px-2.5 py-1.5 text-xs text-on-surface font-mono focus:border-primary-container focus:outline-none disabled:opacity-50"
                />
              </div>
            </div>
          </div>

          {/* Critic Role Sub-card */}
          <div className="bg-[#1e1f24] rounded-xl border border-white/5 p-4 space-y-3">
            <div className="flex items-center gap-2 text-xs font-bold text-on-surface">
              <span className="material-symbols-outlined text-tertiary text-[18px]">rate_review</span>
              <span>Critic Role</span>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="font-caption text-[11px] text-on-surface-variant mb-1 block">Provider</label>
                <select
                  value={criticConfig.preset}
                  onChange={(e) => setCriticConfig({ ...criticConfig, preset: e.target.value })}
                  disabled={isRunning}
                  className="custom-select w-full bg-[#131315] border border-surface-variant rounded-lg px-2.5 py-1.5 text-xs text-on-surface focus:border-primary-container focus:outline-none disabled:opacity-50"
                >
                  <option value="anthropic">Anthropic</option>
                  <option value="openai">OpenAI</option>
                  <option value="groq">Groq</option>
                  <option value="deepseek">DeepSeek</option>
                  <option value="ollama">Ollama (Local)</option>
                </select>
              </div>
              <div>
                <label className="font-caption text-[11px] text-on-surface-variant mb-1 block">Model</label>
                <input
                  type="text"
                  value={criticConfig.model}
                  onChange={(e) => setCriticConfig({ ...criticConfig, model: e.target.value })}
                  disabled={isRunning}
                  className="w-full bg-[#131315] border border-surface-variant rounded-lg px-2.5 py-1.5 text-xs text-on-surface font-mono focus:border-primary-container focus:outline-none disabled:opacity-50"
                />
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* ── Bottom Section: Real Execution Stream ──────────────────────────── */}
      <div className="space-y-4">
        <div className="flex justify-between items-center">
          <h2 className="font-headline-md text-headline-md text-on-surface font-bold">
            Execution Stream
          </h2>
          {activeSession && (
            <button
              onClick={() => {
                setActiveSession(null);
                setGeneratorTask("");
                setCriticInstructions("");
              }}
              className="text-xs text-on-surface-variant hover:text-on-surface underline font-mono cursor-pointer"
            >
              + Start New Session
            </button>
          )}
        </div>

        {activeSession?.rounds && activeSession.rounds.length > 0 ? (
          activeSession.rounds.map((round) => (
            <div key={round.round_number} className="space-y-4">
              {/* Generator Round Card */}
              <div className="bg-[#1e1f24] rounded-xl border border-white/5 p-6 shadow-lg">
                <div className="flex justify-between items-center mb-3">
                  <div className="flex items-center gap-2 font-ui-label-bold text-ui-label-bold text-on-surface">
                    <span className="material-symbols-outlined text-primary text-[18px]">edit_note</span>
                    <span>Generator ({activeSession.generator?.model || "Generator"}) — Round {round.round_number} Output</span>
                  </div>
                  <div className="flex items-center gap-1.5 text-xs font-mono text-on-surface-variant bg-surface-container-low px-2 py-0.5 rounded">
                    <Clock size={12} className="text-primary-container" />
                    <span>{round.created_at ? new Date(round.created_at).toLocaleTimeString() : ""}</span>
                  </div>
                </div>

                <div className="bg-[#0a0a0c] border border-surface-variant rounded-lg p-4 font-code-sm text-code-sm text-on-surface whitespace-pre-wrap max-h-64 overflow-y-auto font-mono">
                  {round.generator_output || <span className="text-outline-variant italic">Generating code stream...</span>}
                </div>
              </div>

              {/* Critic Verdict Card */}
              {round.critic_verdict ? (
                <div className="bg-[#1e1f24] rounded-xl border border-white/5 p-6 shadow-lg space-y-3">
                  <div className="flex justify-between items-center">
                    <div className="flex items-center gap-2 font-ui-label-bold text-ui-label-bold text-on-surface">
                      <span className="material-symbols-outlined text-tertiary text-[18px]">rate_review</span>
                      <span>Critic Analysis ({activeSession.critic?.model || "Critic"})</span>
                    </div>
                    <span className={`px-3 py-1 rounded-full font-caption text-caption font-bold uppercase ${
                      round.critic_verdict.approved
                        ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/30"
                        : "bg-error/10 text-error border border-error/30"
                    }`}>
                      {round.critic_verdict.approved ? "VERDICT: APPROVED" : "VERDICT: REJECTED"}
                    </span>
                  </div>

                  {round.critic_verdict.reasoning && (
                    <p className="text-xs text-on-surface-variant leading-relaxed italic bg-surface-dim/40 p-3 rounded border border-outline-variant/10">
                      {round.critic_verdict.reasoning}
                    </p>
                  )}

                  {round.critic_verdict.issues && round.critic_verdict.issues.length > 0 && (
                    <div className="space-y-2 pt-2">
                      {round.critic_verdict.issues.map((issue, idx) => (
                        <div key={idx} className="rounded-lg border border-amber-500/20 bg-amber-500/5 p-3 text-xs flex items-start gap-2">
                          <span className="px-1.5 py-0.5 rounded font-bold text-[9px] uppercase bg-amber-500/20 text-amber-300 shrink-0">
                            {issue.severity}
                          </span>
                          <div className="flex-1">
                            <span className="text-on-surface font-medium">{issue.description}</span>
                            {issue.suggested_fix && (
                              <p className="text-on-surface-variant/70 text-[11px] mt-1">Suggested fix: {issue.suggested_fix}</p>
                            )}
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              ) : (
                <div className="rounded-xl border border-dashed border-white/10 p-6 text-center text-xs text-on-surface-variant/50 flex items-center justify-center gap-2">
                  <Loader2 size={14} className="animate-spin text-primary-container" />
                  <span>Awaiting Critic Analysis for Round {round.round_number}...</span>
                </div>
              )}
            </div>
          ))
        ) : (
          <div className="rounded-xl border border-dashed border-white/10 p-12 text-center text-xs text-on-surface-variant/50 space-y-2">
            <span className="material-symbols-outlined text-3xl text-outline-variant">loop</span>
            <p>Click "Launch Duo Loop" to start the generator/critic iterative feedback cycle.</p>
          </div>
        )}
      </div>
    </div>
  );
}
