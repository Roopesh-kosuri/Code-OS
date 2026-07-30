import { useState, useEffect, useRef, useCallback } from "react";
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
  History,
} from "lucide-react";
import { ProviderSelector, type ProviderConfig } from "../../components/ui/ProviderSelector";
import { getPreset } from "../../lib/providerPresets";
import { useWorkspaceStore } from "../../stores/workspaceStore";
import { useAIStore } from "../../stores/aiStore";
import { useEditorStore } from "../../stores/editorStore";
import { api } from "../../lib/api";

const API = "http://127.0.0.1:8000";


// ── Types (mirroring backend schemas) ────────────────────────────────────────

interface ModelConfig {
  provider: "ollama" | "openai-compatible";
  model: string;
  base_url?: string;
  temperature?: number;
}

interface CriticIssue {
  description: string;
  severity: "high" | "medium" | "low";
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
}

interface DuoSession {
  id: string;
  workspace: string;
  task_description: string;
  status: "running" | "approved" | "unresolved" | "cancelled" | "error" | "waiting_for_recovery";
  current_round: number;
  max_rounds: number;
  rounds: DuoRound[];
  final_proposal_id: string | null;
  generator: ModelConfig;
  critic: ModelConfig;
  created_at: string;
  pending_action?: {
    type: string;
    details: string;
  };
}

function severityColor(s: string) {
  if (s === "high") return "text-red-400 bg-red-400/10 border-red-500/30";
  if (s === "medium") return "text-amber-400 bg-amber-400/10 border-amber-500/30";
  return "text-sky-400 bg-sky-400/10 border-sky-500/30";
}

function StatusBadge({ status }: { status: DuoSession["status"] }) {
  const map: Record<string, { label: string; cls: string; icon: React.ReactNode }> = {
    running: { label: "Running", cls: "text-blue-400 bg-blue-400/10 border-blue-500/30", icon: <Loader2 size={11} className="animate-spin" /> },
    waiting_for_recovery: { label: "Recovery Needed", cls: "text-amber-400 bg-amber-400/10 border-amber-500/30", icon: <AlertTriangle size={11} className="animate-pulse" /> },
    approved: { label: "Approved", cls: "text-emerald-400 bg-emerald-400/10 border-emerald-500/30", icon: <CheckCircle2 size={11} /> },
    unresolved: { label: "Unresolved", cls: "text-amber-400 bg-amber-400/10 border-amber-500/30", icon: <AlertTriangle size={11} /> },
    cancelled: { label: "Cancelled", cls: "text-slate-400 bg-surface-700 border-surface-600", icon: <Square size={11} /> },
    error: { label: "Error", cls: "text-red-400 bg-red-400/10 border-red-500/30", icon: <XCircle size={11} /> },
  };
  const { label, cls, icon } = map[status] ?? map.error;
  return (
    <span className={`inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${cls}`}>
      {icon} {label}
    </span>
  );
}

// (ModelConfigForm replaced by shared ProviderSelector component)

// ── Sub-components ────────────────────────────────────────────────────────────

function RoundCard({ round, isLatest }: { round: DuoRound; isLatest: boolean }) {
  const [expanded, setExpanded] = useState(isLatest);
  const verdict = round.critic_verdict;
  const isGenerating = verdict === null;

  const switchToDiff = () => {
    window.dispatchEvent(new CustomEvent("code-os:switch-utility", { detail: "diff" }));
  };

  return (
    <div className={`rounded-xl border transition-all glass-panel overflow-hidden ${isLatest ? "border-primary-container/40 shadow-lg shadow-primary-container/5" : "border-outline-variant/20"}`}>
      {/* Round header */}
      <button
        onClick={() => setExpanded((v) => !v)}
        className="flex w-full items-center justify-between px-3.5 py-2.5 text-left bg-surface-container-high/40 hover:bg-surface-container-high/80 transition-colors"
      >
        <div className="flex items-center gap-2.5">
          <span className="font-label-caps text-label-caps text-primary tracking-wider uppercase bg-primary-container/10 border border-primary-container/30 px-2 py-0.5 rounded-full">
            Round {round.round_number}
          </span>
          {isGenerating && (
            <span className="flex items-center gap-1 text-[11px] font-medium text-primary animate-pulse">
              <Loader2 size={12} className="animate-spin" /> Generating &amp; Reviewing…
            </span>
          )}
          {verdict?.approved && (
            <span className="flex items-center gap-1 font-label-caps text-label-caps text-emerald-400 bg-emerald-500/10 border border-emerald-500/30 px-2 py-0.5 rounded-full">
              <CheckCircle2 size={11} /> VERDICT: APPROVED
            </span>
          )}
          {verdict && !verdict.approved && (
            <span className="flex items-center gap-1 font-label-caps text-label-caps text-error bg-error/10 border border-error/30 px-2 py-0.5 rounded-full">
              <XCircle size={11} /> VERDICT: REJECTED ({(verdict.issues?.length ?? 0)} issue{(verdict.issues?.length ?? 0) !== 1 ? "s" : ""})
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {round.proposal_id && (
            <button
              onClick={(e) => { e.stopPropagation(); switchToDiff(); }}
              className="flex items-center gap-1 rounded-lg bg-primary-container/15 border border-primary-container/30 px-2 py-1 text-xs font-medium text-primary hover:bg-primary-container/25 transition-all active:scale-95 duration-200"
              title="View this proposal in DiffViewer"
            >
              <FileDiff size={12} /> View Diff
            </button>
          )}
          {expanded ? <ChevronDown size={14} className="text-on-surface-variant" /> : <ChevronRight size={14} className="text-on-surface-variant" />}
        </div>
      </button>

      {expanded && (
        <div className="p-3 space-y-3 border-t border-outline-variant/20">
          {/* Generator output card */}
          <div className={`rounded-lg border-l-4 border-l-primary-container border border-outline-variant/20 bg-surface-container-lowest/80 p-3 space-y-2 relative overflow-hidden ${isGenerating ? "pulse-border" : ""}`}>
            {isGenerating && (
              <div className="absolute inset-0 bg-gradient-to-r from-transparent via-primary-container/5 to-transparent animate-pulse pointer-events-none" />
            )}
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className="font-label-caps text-label-caps text-primary tracking-widest uppercase">GENERATOR</span>
                <span className="font-label-caps text-[10px] px-2 py-0.5 rounded bg-surface-container-high text-on-surface-variant font-mono">
                  GPT-4 / Local LLM
                </span>
              </div>
            </div>
            <pre className="max-h-52 overflow-y-auto rounded-md bg-surface-dim/90 border border-outline-variant/10 p-2.5 text-code-base font-code-base text-on-surface-variant whitespace-pre-wrap leading-relaxed select-text">
              {round.generator_output || <span className="text-on-surface-variant/40 italic">Generating response stream…</span>}
            </pre>
          </div>

          {/* Critic verdict card */}
          {verdict && (
            <div className={`rounded-lg border-l-4 ${verdict.approved ? "border-l-emerald-500" : "border-l-secondary-container"} border border-outline-variant/20 bg-surface-container-lowest/80 p-3 space-y-2`}>
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="font-label-caps text-label-caps text-secondary tracking-widest uppercase">CRITIC</span>
                  <span className="font-label-caps text-[10px] px-2 py-0.5 rounded bg-surface-container-high text-on-surface-variant font-mono">
                    Claude / Critic LLM
                  </span>
                </div>
                <span className={`font-label-caps text-label-caps px-2.5 py-0.5 rounded-full border ${verdict.approved ? "border-emerald-500/50 bg-emerald-500/10 text-emerald-400" : "border-error/50 bg-error/10 text-error"}`}>
                  {verdict.approved ? "✓ APPROVED" : "✕ REJECTED"}
                </span>
              </div>
              {verdict.reasoning && (
                <p className="font-body-base text-body-base text-on-surface-variant italic bg-surface-dim/40 p-2 rounded border border-outline-variant/10">{verdict.reasoning}</p>
              )}
              {verdict.issues && verdict.issues.length > 0 ? (
                <div className="space-y-1.5 pt-1">
                  {verdict.issues.map((issue, idx) => (
                    <div
                      key={idx}
                      className={`rounded-md border p-2 text-body-base font-body-base ${severityColor(issue.severity)}`}
                    >
                      <div className="flex items-start gap-1.5">
                        <span className={`shrink-0 mt-0.5 rounded px-1.5 py-px text-[9px] font-bold uppercase border ${severityColor(issue.severity)}`}>
                          {issue.severity}
                        </span>
                        <span className="text-on-surface">{issue.description}</span>
                      </div>
                      {issue.suggested_fix && (
                        <p className="mt-1 pl-5 text-on-surface-variant/70 text-xs">→ {issue.suggested_fix}</p>
                      )}
                    </div>
                  ))}
                </div>
              ) : (
                <p className="font-body-base text-body-base text-emerald-400 flex items-center gap-1 pt-1">
                  <CheckCircle2 size={13} /> All criteria satisfied — zero issues detected.
                </p>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

import { PermissionGate } from "../../components/ui/PermissionGate";

function SessionView({ session, onCancel, onRetry, onRecover }: { session: DuoSession; onCancel: () => void; onRetry: () => void; onRecover: (action: "retry" | "switch_to_api" | "cancel") => void }) {
  const [applying, setApplying] = useState(false);
  const [applied, setApplied] = useState(false);
  const [applyError, setApplyError] = useState<string | null>(null);

  const switchToDiff = (proposalId?: string | null) => {
    window.dispatchEvent(new CustomEvent("code-os:switch-top-view", { detail: "proposals" }));
    if (proposalId) {
      window.dispatchEvent(new CustomEvent("code-os:select-proposal", { detail: proposalId }));
    }
  };

  const handleApproveProposal = async () => {
    if (!session.final_proposal_id) return;
    setApplying(true);
    setApplyError(null);
    try {
      const res = await api.post<{ id: string; status: string; changes: { path: string }[] }>(`/api/ai/edit-proposals/${session.final_proposal_id}/apply`);
      setApplied(true);
      window.dispatchEvent(new CustomEvent("code-os:proposal-applied", { detail: session.final_proposal_id }));
      void useWorkspaceStore.getState().refreshTree();

      // Automatically open all applied files in editor workspace tabs
      if (res && res.changes && res.changes.length > 0) {
        for (const change of res.changes) {
          void useEditorStore.getState().openFile(change.path);
        }
      }
      // Switch top view tab to main editor workspace so user sees files immediately
      window.dispatchEvent(new CustomEvent("code-os:switch-top-view", { detail: "main" }));
    } catch (err) {
      // Show inline error — do NOT navigate away to proposals
      const msg = err instanceof Error ? err.message : String(err);
      setApplyError(`Apply failed: ${msg}. You can view the diff manually.`);
      console.error("Direct proposal application failed from Duo Loop:", err);
    } finally {
      setApplying(false);
    }
  };

  const isCompleted = session.status === "approved" || session.status === "unresolved" || session.status === "cancelled" || session.status === "error";

  return (
    <div className="space-y-3">
      {/* Session header */}
      <div className="rounded-lg border border-surface-700 bg-surface-900 p-3">
        <div className="flex items-start justify-between gap-2 mb-1">
          <StatusBadge status={session.status} />
          <span className="text-[10px] text-slate-600">
            Round {session.current_round}/{session.max_rounds}
          </span>
        </div>
        <p className="text-[11px] text-slate-400 mt-1.5 line-clamp-2">{session.task_description}</p>

        {/* Model config summary */}
        <div className="mt-2 grid grid-cols-2 gap-1.5 text-[10px]">
          <div className="rounded bg-surface-800 px-2 py-1">
            <span className="text-slate-500">Gen: </span>
            <span className="text-slate-300">{session.generator.model}</span>
            <span className="text-slate-600 ml-1">({session.generator.provider === "ollama" ? "local" : "api"})</span>
          </div>
          <div className="rounded bg-surface-800 px-2 py-1">
            <span className="text-slate-500">Critic: </span>
            <span className="text-slate-300">{session.critic.model}</span>
            <span className="text-slate-600 ml-1">({session.critic.provider === "ollama" ? "local" : "api"})</span>
          </div>
        </div>
      </div>

      {/* Progress bar */}
      <div className="h-1.5 rounded-full bg-surface-800 overflow-hidden">
        <div
          className={`h-full rounded-full transition-all duration-500 ${
            session.status === "approved" ? "bg-emerald-500" :
            session.status === "unresolved" ? "bg-amber-500" :
            session.status === "cancelled" ? "bg-slate-500" :
            session.status === "error" ? "bg-red-500" :
            session.status === "waiting_for_recovery" ? "bg-amber-500" :
            "bg-accent-500 animate-pulse"
          }`}
          style={{
            width: `${
              isCompleted
                ? 100
                : Math.max(4, (session.current_round / session.max_rounds) * 100)
            }%`
          }}
        />
      </div>

      {/* Recovery Prompt */}
      {session.status === "waiting_for_recovery" && session.pending_action?.type === "llm_failure" && (
        <div className="rounded-lg border border-amber-500/40 bg-amber-500/5 p-3 text-[11px] text-amber-300 space-y-2">
          <div className="flex items-center gap-1.5 font-bold uppercase tracking-wider">
            <AlertTriangle size={14} className="shrink-0 animate-pulse" /> LLM Execution Failed
          </div>
          <p className="font-mono text-tertiary/80 leading-relaxed max-h-24 overflow-y-auto bg-surface-dim p-2 rounded border border-tertiary-container/10">
            {session.pending_action.details}
          </p>
          <div className="flex gap-2 pt-1">
            <button type="button" onClick={() => onRecover("retry")} className="rounded bg-tertiary-container/20 border border-tertiary-container/40 px-3 py-1.5 font-semibold hover:bg-tertiary-container/30 transition-colors active:scale-95 duration-200 flex-1">Retry Round</button>
            <button type="button" onClick={() => onRecover("switch_to_api")} className="rounded bg-tertiary-container/20 border border-tertiary-container/40 px-3 py-1.5 font-semibold hover:bg-tertiary-container/30 transition-colors active:scale-95 duration-200 flex-1">Switch to API</button>
            <button type="button" onClick={() => onRecover("cancel")} className="rounded border border-tertiary-container/20 px-3 py-1.5 font-semibold hover:bg-tertiary-container/10 transition-colors active:scale-95 duration-200 flex-1 text-tertiary/70 hover:text-tertiary">Cancel Loop</button>
          </div>
        </div>
      )}

      {/* Final status banner */}
      {(session.status !== "running" && session.status !== "waiting_for_recovery") && (
        <div className={`rounded-lg border p-3 text-xs ${
          session.status === "approved" ? "border-primary-container/40 bg-primary-container/10 text-primary/80" :
          session.status === "unresolved" ? "border-tertiary-container/40 bg-tertiary-container/10 text-tertiary/80" :
          "border-outline-variant/20 bg-surface-container text-on-surface-variant/60 dark:text-on-surface-variant/60"
        }`}>
          {session.status === "approved" && (
            <div className="space-y-2">
              <span className="flex items-center gap-1.5 text-[12px] font-semibold text-primary-container">
                <CheckCircle2 size={14} /> Loop approved after {session.current_round} round{session.current_round !== 1 ? "s" : ""}
              </span>
              {applied ? (
                <div className="flex items-center gap-2 p-2 rounded-md bg-emerald-500/10 border border-emerald-500/30 text-emerald-400 text-xs font-semibold">
                  <CheckCircle2 size={15} />
                  <span>Changes successfully applied to workspace files!</span>
                </div>
              ) : applyError ? (
                <div className="space-y-2">
                  <div className="flex items-start gap-2 p-2 rounded-md bg-red-500/10 border border-red-500/30 text-red-300 text-xs">
                    <XCircle size={14} className="shrink-0 mt-0.5" />
                    <span>{applyError}</span>
                  </div>
                  <button
                    onClick={() => switchToDiff(session.final_proposal_id)}
                    className="text-xs text-primary underline hover:no-underline"
                  >
                    View diff manually →
                  </button>
                </div>
              ) : session.final_proposal_id ? (
                <div className="mt-2.5">
                  <PermissionGate
                    type="duo-finalize"
                    details="The generator and critic models have agreed on the solution. Click Approve to apply changes directly to your workspace, or View Diff to inspect before applying."
                    onApprove={handleApproveProposal}
                    onReject={() => switchToDiff(session.final_proposal_id)}
                    isLoading={applying}
                  />
                </div>
              ) : null}
            </div>
          )}
          {session.status === "unresolved" && (
            <div className="flex items-center justify-between">
              <span className="flex items-center gap-1.5 text-[12px] font-semibold">
                <AlertTriangle size={14} /> Unresolved after {session.max_rounds} rounds — review manually
              </span>
              {session.final_proposal_id && (
                <button
                  onClick={() => switchToDiff(session.final_proposal_id)}
                  className="flex items-center gap-1 rounded bg-tertiary-container/20 border border-tertiary-container/40 px-2 py-1 text-[11px] text-tertiary hover:bg-tertiary-container/30 transition-colors active:scale-95 duration-200"
                >
                  <FileDiff size={11} /> Last Diff
                </button>
              )}
            </div>
          )}
          {session.status === "cancelled" && (
            <span className="flex items-center gap-1.5 text-[12px]">
              <Square size={14} /> Session cancelled
            </span>
          )}
          {session.status === "error" && (
            <div className="flex items-center justify-between gap-2">
              <span className="flex items-center gap-1.5 text-[12px]">
                <XCircle size={14} /> Session ended with an error
              </span>
              <button onClick={onRetry} className="rounded border border-red-500/40 px-2 py-1 text-[10px] font-semibold text-red-300 hover:bg-red-500/10">Retry</button>
            </div>
          )}
        </div>
      )}

      {/* Cancel button */}
      {session.status === "running" && (
        <button
          onClick={onCancel}
          className="flex w-full items-center justify-center gap-1.5 rounded-lg border border-red-500/40 bg-red-500/10 px-3 py-2 text-xs font-semibold text-red-400 hover:bg-red-500/20 transition-colors"
        >
          <Square size={12} /> Cancel Loop
        </button>
      )}

      {/* Rounds */}
      <div className="space-y-2">
        {session.rounds.map((round, idx) => (
          <RoundCard
            key={round.round_number}
            round={round}
            isLatest={idx === session.rounds.length - 1}
          />
        ))}
        {session.status === "running" && session.rounds.length === 0 && (
          <div className="flex items-center justify-center gap-2 py-6 text-slate-500 text-xs">
            <Loader2 size={14} className="animate-spin" /> Starting first round…
          </div>
        )}
      </div>
    </div>
  );
}

// ── Main panel ────────────────────────────────────────────────────────────────

// Default provider configs are initialized from aiStore in the component
export function DuoPanel({ compact = false }: { compact?: boolean }) {
  const currentWorkspace = useWorkspaceStore((s) => s.currentWorkspace);
  const models = useAIStore((s) => s.models);

  // Sync defaults from current AI store provider so Duo Loop uses whatever is already configured
  const aiPreset = useAIStore((s) => s.preset);
  const aiModel = useAIStore((s) => s.model);
  const aiBaseUrl = useAIStore((s) => s.baseUrl);
  const aiApiKeyProvider = useAIStore((s) => s.apiKeyProvider);

  const defaultProvider: ProviderConfig = {
    preset: aiPreset || "ollama",
    model: aiModel || getPreset(aiPreset)?.model_example || "llama3",
    base_url: aiBaseUrl,
    api_key_provider: aiApiKeyProvider ?? undefined,
  };

  // Form state
  const [task, setTask] = useState("");
  const [criticPrompt, setCriticPrompt] = useState("Identify race conditions, memory bottlenecks, or architectural flaws in proposed modifications.");
  const [generator, setGenerator] = useState<ProviderConfig>(defaultProvider);
  const [critic, setCritic] = useState<ProviderConfig>(defaultProvider);
  const [maxRounds, setMaxRounds] = useState(5);
  const [showHistory, setShowHistory] = useState(false);
  const [configuredKeys, setConfiguredKeys] = useState<string[]>([]);

  // Keep generator/critic updated if store model resolves late
  useEffect(() => {
    if (!generator.model && aiModel) {
      setGenerator((prev) => ({ ...prev, model: aiModel }));
    }
    if (!critic.model && aiModel) {
      setCritic((prev) => ({ ...prev, model: aiModel }));
    }
  }, [aiModel, generator.model, critic.model]);

  // Session state
  const [activeSession, setActiveSession] = useState<DuoSession | null>(null);
  const [sessionHistory, setSessionHistory] = useState<DuoSession[]>([]);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Load configured keys for badge display in ProviderSelector
  useEffect(() => {
    void api.get<{ provider_id: string; configured: boolean }[]>("/api/settings/api-keys")
      .then((keys) => setConfiguredKeys(keys.filter((k) => k.configured).map((k) => k.provider_id)))
      .catch(() => undefined);
  }, []);

  // Listen for utility-switch events from round cards
  useEffect(() => {
    const handler = (e: Event) => {
      const utility = (e as CustomEvent<string>).detail;
      window.dispatchEvent(new CustomEvent("code-os:menu", { detail: `view.switchUtility:${utility}` }));
    };
    window.addEventListener("code-os:switch-utility", handler);
    return () => window.removeEventListener("code-os:switch-utility", handler);
  }, []);

  // Polling
  const startPolling = useCallback((sessionId: string) => {
    if (pollRef.current) clearInterval(pollRef.current);
    pollRef.current = setInterval(async () => {
      try {
        const data = await api.get<DuoSession>(`/api/duo/sessions/${sessionId}`);
        setActiveSession(data);
        if (data.status !== "running" && data.status !== "waiting_for_recovery") {
          clearInterval(pollRef.current!);
          pollRef.current = null;
        }
      } catch {
        // Network blip — keep polling
      }
    }, 2000);
  }, []);

  useEffect(() => () => { if (pollRef.current) clearInterval(pollRef.current); }, []);

  // Load session history on mount / workspace change
  useEffect(() => {
    if (!currentWorkspace) return;
    void (async () => {
      try {
        const data = await api.get<DuoSession[]>(`/api/duo/sessions?workspace=${encodeURIComponent(currentWorkspace.path)}`);
        setSessionHistory(data);
        // Restore active running or recovery session if any
        const active = data.find((s) => s.status === "running" || s.status === "waiting_for_recovery");
        if (active) {
          setActiveSession(active);
          startPolling(active.id);
        }
      } catch { /* ignore */ }
    })();
  }, [currentWorkspace, startPolling]);

  const handleStart = async () => {
    if (!currentWorkspace || !task.trim()) return;
    setError(null);
    setStarting(true);

    // Map ProviderConfig → backend ModelConfig with robust preset fallback
    const toModelConfig = (cfg: ProviderConfig) => {
      const presetObj = getPreset(cfg.preset);
      const wireProvider = presetObj ? presetObj.provider : (cfg.preset === "ollama" ? "ollama" : "openai-compatible");
      return {
        provider: wireProvider,
        model: cfg.model || presetObj?.model_example || aiModel || "llama3",
        base_url: cfg.base_url || presetObj?.base_url,
        api_key_provider: cfg.api_key_provider ?? presetObj?.api_key_provider ?? undefined,
      };
    };

    try {
      const session = await api.post<DuoSession>("/api/duo/sessions", {
        workspace: currentWorkspace.path,
        task_description: task.trim(),
        generator: toModelConfig(generator),
        critic: toModelConfig(critic),
        max_rounds: maxRounds,
      });
      setActiveSession(session);
      setSessionHistory((h) => [session, ...h]);
      startPolling(session.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
    } finally {
      setStarting(false);
    }
  };

  const handleCancel = async () => {
    if (!activeSession) return;
    try {
      const updated = await api.post<DuoSession>(`/api/duo/sessions/${activeSession.id}/cancel`);
      setActiveSession(updated);
      if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
    } catch { /* ignore */ }
  };

  const handleRecover = async (action: "retry" | "switch_to_api" | "cancel") => {
    if (!activeSession) return;
    try {
      await api.post(`/api/duo/sessions/${activeSession.id}/recover`, { action });
      // Polling will catch the updated status
    } catch { /* ignore */ }
  };

  const canStart = !!(currentWorkspace && task.trim() && generator.model && critic.model && !starting && activeSession?.status !== "running");

  /* ── Compact (sidebar) layout ─────────────────────────────────────────── */
  if (compact) {
    return (
      <main
        data-testid="duo-loop-panel"
        className="flex flex-col h-full overflow-y-auto bg-[#131314] text-on-surface select-none"
      >
        {/* Compact Header */}
        <div className="flex items-center justify-between px-3 py-2 border-b border-white/5 shrink-0">
          <div className="flex items-center gap-1.5">
            <span className="material-symbols-outlined text-primary text-sm">loop</span>
            <span className="text-[11px] font-bold text-on-surface tracking-tight">Duo Loop</span>
          </div>
          <div className="bg-surface-variant px-1.5 py-0.5 rounded font-mono text-[9px] text-primary-fixed uppercase flex items-center gap-1 border border-primary/20">
            <span className="w-1 h-1 rounded-full bg-primary animate-pulse" />
            {activeSession ? `R${activeSession.current_round}/${activeSession.max_rounds}` : "0/5"}
          </div>
        </div>

        {/* Compact scrollable body */}
        <div className="flex flex-col gap-2 p-2 overflow-y-auto flex-1 min-h-0">

          {/* Error */}
          {error && (
            <div className="text-[9px] text-error bg-error/5 border border-error/30 rounded p-1.5">{error}</div>
          )}

          {/* Task input */}
          <div className="glass-panel rounded-md p-2 flex flex-col gap-1.5">
            <label className="text-[9px] font-bold uppercase tracking-wider text-secondary">Task</label>
            <textarea
              rows={3}
              value={task}
              onChange={(e) => setTask(e.target.value)}
              placeholder="Describe the task for the Generator AI…"
              className="w-full bg-transparent text-on-surface text-[10px] focus:outline-none resize-none font-mono leading-relaxed placeholder:text-on-surface-variant/30 select-text"
            />
          </div>

          {/* Critic prompt */}
          <div className="glass-panel rounded-md p-2 flex flex-col gap-1.5">
            <label className="text-[9px] font-bold uppercase tracking-wider text-tertiary">Critic Instructions</label>
            <textarea
              rows={2}
              value={criticPrompt}
              onChange={(e) => setCriticPrompt(e.target.value)}
              placeholder="Identify flaws in proposed modifications…"
              className="w-full bg-transparent text-on-surface text-[10px] focus:outline-none resize-none font-mono leading-relaxed placeholder:text-on-surface-variant/30 select-text"
            />
          </div>

          {/* Generator + Critic model pickers stacked */}
          <div className="glass-panel rounded-md p-2 flex flex-col gap-2">
            <div className="flex items-center justify-between">
              <span className="text-[9px] font-bold uppercase tracking-wider text-outline">Agents</span>
              <div className="flex items-center gap-1.5">
                <span className="text-[9px] text-on-surface-variant">Rounds</span>
                <select
                  value={maxRounds}
                  onChange={(e) => setMaxRounds(Number(e.target.value))}
                  className="bg-surface-container-high text-on-surface border border-white/10 rounded px-1.5 py-0.5 text-[9px] font-mono"
                >
                  {[3, 5, 8, 10].map((n) => <option key={n} value={n}>{n}</option>)}
                </select>
              </div>
            </div>
            <div className="flex flex-col gap-1.5">
              <div className="bg-surface-container-low rounded p-1.5 border border-secondary/30">
                <div className="text-[9px] text-secondary uppercase font-bold mb-1">Generator</div>
                <ProviderSelector value={generator} onChange={setGenerator} configuredKeys={configuredKeys} models={models} compact />
              </div>
              <div className="bg-surface-container-low rounded p-1.5 border border-tertiary/30">
                <div className="text-[9px] text-tertiary uppercase font-bold mb-1">Critic</div>
                <ProviderSelector value={critic} onChange={setCritic} configuredKeys={configuredKeys} models={models} compact />
              </div>
            </div>
          </div>

          {/* Launch / Active session */}
          {!activeSession ? (
            <button
              onClick={() => void handleStart()}
              disabled={!canStart}
              className="bg-primary-container text-on-primary-container font-mono text-[10px] px-4 py-1.5 rounded-full font-bold uppercase tracking-wider shadow-[0_0_10px_rgba(0,229,255,0.3)] disabled:opacity-50 w-full"
            >
              {starting ? "Starting…" : "Launch Duo Loop"}
            </button>
          ) : (
            <div className="space-y-2">
              <SessionView
                session={activeSession}
                onCancel={() => void handleCancel()}
                onRetry={() => void handleStart()}
                onRecover={(action) => void handleRecover(action)}
              />
              <button
                type="button"
                onClick={() => setActiveSession(null)}
                className="text-[9px] text-on-surface-variant hover:text-on-surface underline font-mono w-full text-right"
              >
                + New Session
              </button>
            </div>
          )}

          {/* Session history */}
          {sessionHistory.length > 1 && (
            <div className="glass-panel rounded-md p-2 flex flex-col gap-1">
              <span className="text-[9px] font-bold uppercase tracking-wider text-outline">History</span>
              <div className="space-y-1 max-h-32 overflow-y-auto">
                {sessionHistory.slice(0, 5).map((s) => (
                  <button
                    key={s.id}
                    onClick={() => setActiveSession(s)}
                    className="w-full text-left text-[9px] bg-surface-container-low border border-white/5 rounded p-1.5 hover:bg-surface-container transition-colors"
                  >
                    <div className="flex justify-between items-center">
                      <span className="font-mono text-on-surface-variant truncate max-w-[140px]">{s.task_description}</span>
                      <StatusBadge status={s.status} />
                    </div>
                  </button>
                ))}
              </div>
            </div>
          )}

        </div>
      </main>
    );
  }

  /* ── Full (topbar) layout — unchanged ──────────────────────────────────── */
  return (
    <main data-testid="duo-loop-panel" className="flex-1 flex flex-col p-3 sm:p-4 md:p-6 gap-3 sm:gap-4 overflow-y-auto bg-[#131314] text-on-surface h-full select-none">

      {/* Page Header */}
      <header className="flex justify-between items-center mb-1 shrink-0 flex-wrap gap-2">
        <div className="flex items-center gap-2 sm:gap-3">
          <span className="material-symbols-outlined text-primary text-xl sm:text-3xl">loop</span>
          <h1 className="text-base sm:text-headline-lg text-on-surface font-bold">Duo Loop</h1>
        </div>
        <div className="bg-surface-variant px-2.5 py-1 rounded font-micro-label text-[10px] sm:text-micro-label text-primary-fixed uppercase flex items-center gap-1.5 border border-primary/20 shadow-[0_0_8px_rgba(0,229,255,0.1)]">
          <span className="w-1.5 h-1.5 rounded-full bg-primary animate-pulse" />
          <span>
            {activeSession ? `ROUND ${activeSession.current_round} / ${activeSession.max_rounds}` : "ROUND 0 / 5"}
          </span>
        </div>
      </header>


      {/* Configuration Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-2 shrink-0">
        {/* Task Division */}
        <div className="glass-panel rounded-lg p-4 flex flex-col gap-4">
          <div className="flex items-center justify-between border-b border-white/5 pb-2">
            <h2 className="font-micro-label text-micro-label text-on-surface-variant uppercase font-bold">Task Division</h2>
            <div className="flex items-center gap-2">
              <label className="font-micro-label text-micro-label text-on-surface-variant/60">Max Rounds</label>
              <select
                value={maxRounds}
                onChange={(e) => setMaxRounds(Number(e.target.value))}
                className="bg-surface-container-high text-on-surface border border-white/10 rounded px-2 py-0.5 text-xs font-mono"
              >
                {[3,5,8,10].map(n => <option key={n} value={n}>{n}</option>)}
              </select>
            </div>
          </div>
          <div className="flex flex-col gap-3">
            <div className="bg-surface-container-low rounded p-3 border border-secondary/20 focus-within:border-secondary/50 transition-colors">
              <label className="font-micro-label text-micro-label text-secondary mb-2 block uppercase font-bold">Generator Task</label>
              <textarea
                rows={3}
                value={task}
                onChange={(e) => setTask(e.target.value)}
                placeholder="Describe the task for the Generator AI. E.g. Refactor AuthModule for better concurrency. Ensure thread safety..."
                className="w-full bg-transparent text-on-surface text-sm focus:outline-none resize-none font-code-block leading-relaxed placeholder:text-on-surface-variant/30 select-text"
              />
            </div>
            <div className="bg-surface-container-low rounded p-3 border border-tertiary/20 focus-within:border-tertiary/50 transition-colors">
              <label className="font-micro-label text-micro-label text-tertiary mb-2 block uppercase font-bold">Critic Instructions (Strict Mode)</label>
              <textarea
                rows={2}
                value={criticPrompt}
                onChange={(e) => setCriticPrompt(e.target.value)}
                placeholder="Identify race conditions, memory bottlenecks, or architectural flaws in proposed modifications..."
                className="w-full bg-transparent text-on-surface text-sm focus:outline-none resize-none font-code-block leading-relaxed placeholder:text-on-surface-variant/30 select-text"
              />
            </div>
          </div>
        </div>

        {/* Agent Selection */}
        <div className="glass-panel rounded-lg p-4 flex flex-col gap-4">
          <div className="flex items-center justify-between border-b border-white/5 pb-2">
            <h2 className="font-micro-label text-micro-label text-on-surface-variant uppercase font-bold">Agent Selection</h2>
            <span className="material-symbols-outlined text-outline text-sm">group</span>
          </div>
          <div className="grid grid-cols-2 gap-3 h-full">
            {/* Generator Role */}
            <div className="bg-surface-container-low rounded p-3 flex flex-col border border-secondary/30 relative overflow-hidden">
              <div className="font-micro-label text-micro-label text-secondary uppercase mb-2 font-bold">Generator Role</div>
              <ProviderSelector
                value={generator}
                onChange={setGenerator}
                configuredKeys={configuredKeys}
                models={models}
                compact
              />
            </div>
            {/* Critic Role */}
            <div className="bg-surface-container-low rounded p-3 flex flex-col border border-tertiary/30 relative overflow-hidden">
              <div className="font-micro-label text-micro-label text-tertiary uppercase mb-2 font-bold">Critic Role</div>
              <ProviderSelector
                value={critic}
                onChange={setCritic}
                configuredKeys={configuredKeys}
                models={models}
                compact
              />
            </div>
          </div>
        </div>
      </div>

      {/* Stream Section */}
      <div className="flex flex-col gap-4 flex-1 min-h-0">
        <div className="flex items-center gap-2">
          <h2 className="font-micro-label text-micro-label text-on-surface-variant uppercase tracking-widest font-bold">Execution Stream</h2>
          <div className="h-[1px] flex-1 bg-white/5" />
          {!activeSession && (
            <button
              onClick={() => void handleStart()}
              disabled={!canStart}
              className="bg-primary-container text-on-primary-container font-micro-label text-micro-label px-5 py-1.5 rounded-full font-bold uppercase tracking-wider shadow-[0_0_12px_rgba(0,229,255,0.4)] disabled:opacity-50"
            >
              {starting ? "Starting Duo..." : "Launch Duo Loop"}
            </button>
          )}
        </div>

        {/* Active Session View Banner & Controls */}
        {activeSession && (
          <div className="space-y-4">
            <SessionView
              session={activeSession}
              onCancel={() => void handleCancel()}
              onRetry={() => void handleStart()}
              onRecover={(action) => void handleRecover(action)}
            />
            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setActiveSession(null)}
                className="text-xs text-on-surface-variant hover:text-on-surface underline font-mono"
              >
                + Start New Duo Session
              </button>
            </div>
          </div>
        )}

        {/* Demo Stream View if no session running */}
        {!activeSession && (
          <div className="space-y-3">
            {/* Demo Generator Card */}
            <div className="glass-panel rounded-lg p-0 border-l-2 border-l-secondary overflow-hidden ml-4">
              <div className="bg-surface-variant/30 px-4 py-2 flex items-center justify-between border-b border-white/5">
                <div className="flex items-center gap-2">
                  <span className="material-symbols-outlined text-secondary text-sm">smart_toy</span>
                  <span className="font-micro-label text-micro-label text-secondary uppercase font-bold">Generator ({generator.model})</span>
                  <span className="font-micro-label text-micro-label text-on-surface-variant ml-2">Round 2 Output</span>
                </div>
                <span className="font-micro-label text-micro-label text-on-surface-variant">2.4s</span>
              </div>
              <div className="p-4 font-code-block text-code-block text-on-surface text-sm overflow-x-auto bg-surface-container-lowest font-mono leading-relaxed">
                <pre><code><span className="text-secondary-fixed-dim">export</span> <span className="text-primary">{"class"}</span> AuthModule {"{\n"}
  <span className="text-secondary-fixed-dim">private</span> lock = <span className="text-secondary-fixed-dim">new</span> Mutex();{"\n"}
  <span className="text-primary-fixed">async</span> validateToken(token: <span className="text-tertiary">string</span>) {"{\n"}
    <span className="text-secondary-fixed-dim">await</span> <span className="text-primary-container">this</span>.lock.acquire();{"\n"}
    <span className="text-secondary-fixed-dim">try</span> {"{\n"}
      <span className="text-outline-variant">// Validation logic</span>{"\n"}
      <span className="text-secondary-fixed-dim">const</span> isValid = <span className="text-secondary-fixed-dim">await</span> cache.check(token);{"\n"}
      <span className="text-secondary-fixed-dim">return</span> isValid;{"\n"}
    {"}"} <span className="text-secondary-fixed-dim">finally</span> {"{\n"}
      <span className="text-primary-container">this</span>.lock.release();{"\n"}
    {"}"}\n  {"}"}\n{"}"}</code></pre>
              </div>
            </div>

            {/* Demo Critic Card */}
            <div className="glass-panel rounded-lg p-0 border-l-2 border-l-tertiary overflow-hidden ml-8">
              <div className="bg-surface-variant/30 px-4 py-2 flex items-center justify-between border-b border-white/5">
                <div className="flex items-center gap-2">
                  <span className="material-symbols-outlined text-tertiary text-sm">psychology</span>
                  <span className="font-micro-label text-micro-label text-tertiary uppercase font-bold">Critic ({critic.model})</span>
                </div>
                <div className="bg-error-container/20 border border-error/30 text-error px-2 py-0.5 rounded flex items-center gap-1 font-micro-label text-micro-label font-bold uppercase">
                  <span className="material-symbols-outlined text-[10px]">close</span>
                  REJECTED
                </div>
              </div>
              <div className="p-4 font-body-sm text-body-sm text-on-surface">
                <p className="mb-2 text-on-surface-variant">The implementation introduces a severe bottleneck. Using a single global Mutex for token validation means that all concurrent requests will be serialized, completely defeating the purpose of asynchronous concurrency.</p>
                <div className="bg-surface-container-highest p-2.5 rounded border border-white/5 font-code-block text-code-block text-xs mt-2 text-outline font-mono">
                  &gt; Fix requirement: Implement a per-token locking mechanism or use a lock-free optimistic caching strategy to allow non-conflicting validations to proceed concurrently.
                </div>
              </div>
            </div>

            {/* Demo Iterated Generator Card (Active/Shimmer) */}
            <div className="glass-panel rounded-lg p-0 border-l-2 border-l-secondary overflow-hidden ml-4 relative">
              <div className="absolute inset-0 shimmer pointer-events-none z-0" />
              <div className="relative z-10">
                <div className="bg-surface-variant/50 px-4 py-2 flex items-center justify-between border-b border-white/5">
                  <div className="flex items-center gap-2">
                    <span className="material-symbols-outlined text-secondary text-sm animate-spin">autorenew</span>
                    <span className="font-micro-label text-micro-label text-secondary uppercase font-bold">Generator ({generator.model})</span>
                    <span className="font-micro-label text-micro-label text-on-surface-variant ml-2">Round 3 Generating...</span>
                  </div>
                  <div className="flex gap-1">
                    <span className="w-1.5 h-1.5 rounded-full bg-secondary animate-bounce" />
                    <span className="w-1.5 h-1.5 rounded-full bg-secondary animate-bounce" style={{ animationDelay: "0.1s" }} />
                    <span className="w-1.5 h-1.5 rounded-full bg-secondary animate-bounce" style={{ animationDelay: "0.2s" }} />
                  </div>
                </div>
                <div className="p-4 font-code-block text-code-block text-on-surface text-sm opacity-70 bg-surface-container-lowest font-mono">
                  <pre><code><span className="text-secondary-fixed-dim">export</span> <span className="text-primary">{"class"}</span> AuthModule {"{\n"}  <span className="text-outline-variant">// Refactoring based on critic feedback</span>{"\n"}  <span className="text-secondary-fixed-dim">private</span> tokenLocks = <span className="text-secondary-fixed-dim">new</span> Map&lt;<span className="text-tertiary">string</span>, Mutex&gt;();{"\n"}  <span className="text-primary-fixed">async</span> validateToken(token: <span className="text-tertiary">string</span>) {"{\n"}    <span className="text-outline-variant">...</span></code><span className="inline-block w-2 h-4 bg-secondary ml-1 animate-pulse align-middle" /></pre>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Bottom Action */}
      {activeSession?.status === "running" && (
        <div className="mt-4 flex justify-end shrink-0">
          <button
            onClick={() => void handleCancel()}
            className="bg-surface-container text-error hover:bg-error/10 border border-error/30 px-4 py-2 rounded-full font-body-sm text-body-sm font-semibold transition-colors flex items-center gap-2"
          >
            <span className="material-symbols-outlined text-sm">stop_circle</span>
            Halt Loop
          </button>
        </div>
      )}
    </main>
  );
}
