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
import { useWorkspaceStore } from "../../stores/workspaceStore";
import { useAIStore } from "../../stores/aiStore";
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

  const switchToDiff = () => {
    window.dispatchEvent(new CustomEvent("code-os:switch-utility", { detail: "diff" }));
  };

  return (
    <div className={`rounded-lg border transition-all ${isLatest ? "border-accent-500/40 bg-surface-850" : "border-surface-700 bg-surface-900"}`}>
      {/* Round header */}
      <button
        onClick={() => setExpanded((v) => !v)}
        className="flex w-full items-center justify-between px-3 py-2 text-left"
      >
        <div className="flex items-center gap-2">
          <span className="text-[11px] font-bold text-accent-400">Round {round.round_number}</span>
          {verdict === null && (
            <span className="flex items-center gap-1 text-[10px] text-slate-500">
              <Loader2 size={10} className="animate-spin" /> Running…
            </span>
          )}
          {verdict?.approved && (
            <span className="flex items-center gap-1 text-[10px] text-emerald-400">
              <CheckCircle2 size={10} /> Approved by Critic
            </span>
          )}
          {verdict && !verdict.approved && (
            <span className="flex items-center gap-1 text-[10px] text-red-400">
              <XCircle size={10} /> {verdict.issues.length} issue{verdict.issues.length !== 1 ? "s" : ""}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {round.proposal_id && (
            <button
              onClick={(e) => { e.stopPropagation(); switchToDiff(); }}
              className="flex items-center gap-1 rounded bg-accent-500/15 border border-accent-500/30 px-1.5 py-0.5 text-[10px] text-accent-400 hover:bg-accent-500/25 transition-colors"
              title="View this proposal in DiffViewer"
            >
              <FileDiff size={10} /> View Diff
            </button>
          )}
          {expanded ? <ChevronDown size={14} className="text-slate-500" /> : <ChevronRight size={14} className="text-slate-500" />}
        </div>
      </button>

      {expanded && (
        <div className="px-3 pb-3 space-y-2.5 border-t border-surface-700/60 pt-2.5">
          {/* Generator output preview */}
          <div>
            <div className="text-[10px] text-slate-500 mb-1 font-semibold uppercase tracking-wider">⚙ Generator Output</div>
            <pre className="max-h-48 overflow-y-auto rounded bg-surface-950 border border-surface-700 p-2 text-[11px] text-slate-300 whitespace-pre-wrap font-mono leading-relaxed">
              {round.generator_output || <span className="text-slate-600 italic">Generating…</span>}
            </pre>
          </div>

          {/* Critic verdict */}
          {verdict && (
            <div>
              <div className="text-[10px] text-slate-500 mb-1 font-semibold uppercase tracking-wider">
                🔍 Critic Verdict
              </div>
              {verdict.reasoning && (
                <p className="text-[11px] text-slate-400 mb-2 italic">{verdict.reasoning}</p>
              )}
              {verdict.issues.length > 0 ? (
                <div className="space-y-1.5">
                  {verdict.issues.map((issue, idx) => (
                    <div
                      key={idx}
                      className={`rounded border p-2 text-[11px] ${severityColor(issue.severity)}`}
                    >
                      <div className="flex items-start gap-1.5">
                        <span className={`shrink-0 mt-0.5 rounded px-1 py-px text-[9px] font-bold uppercase border ${severityColor(issue.severity)}`}>
                          {issue.severity}
                        </span>
                        <span className="text-slate-300">{issue.description}</span>
                      </div>
                      {issue.suggested_fix && (
                        <p className="mt-1 pl-5 text-slate-500 text-[10px]">→ {issue.suggested_fix}</p>
                      )}
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-[11px] text-emerald-400 flex items-center gap-1">
                  <CheckCircle2 size={11} /> No issues found
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
  const switchToDiff = () => {
    window.dispatchEvent(new CustomEvent("code-os:switch-utility", { detail: "diff" }));
  };

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
      <div className="h-1 rounded-full bg-surface-800 overflow-hidden">
        <div
          className={`h-full rounded-full transition-all duration-500 ${
            session.status === "approved" ? "bg-emerald-500" :
            session.status === "unresolved" ? "bg-amber-500" :
            session.status === "cancelled" ? "bg-slate-500" :
            session.status === "error" ? "bg-red-500" :
            session.status === "waiting_for_recovery" ? "bg-amber-500" :
            "bg-accent-500 animate-pulse"
          }`}
          style={{ width: `${Math.max(4, (session.current_round / session.max_rounds) * 100)}%` }}
        />
      </div>

      {/* Recovery Prompt */}
      {session.status === "waiting_for_recovery" && session.pending_action?.type === "llm_failure" && (
        <div className="rounded-lg border border-amber-500/40 bg-amber-500/5 p-3 text-[11px] text-amber-300 space-y-2">
          <div className="flex items-center gap-1.5 font-bold uppercase tracking-wider">
            <AlertTriangle size={14} className="shrink-0 animate-pulse" /> LLM Execution Failed
          </div>
          <p className="font-mono text-amber-300/80 leading-relaxed max-h-24 overflow-y-auto bg-surface-950 p-2 rounded border border-amber-500/10">
            {session.pending_action.details}
          </p>
          <div className="flex gap-2 pt-1">
            <button type="button" onClick={() => onRecover("retry")} className="rounded bg-amber-500/20 border border-amber-500/40 px-3 py-1.5 font-semibold hover:bg-amber-500/30 transition-colors flex-1">Retry Round</button>
            <button type="button" onClick={() => onRecover("switch_to_api")} className="rounded bg-amber-500/20 border border-amber-500/40 px-3 py-1.5 font-semibold hover:bg-amber-500/30 transition-colors flex-1">Switch to API</button>
            <button type="button" onClick={() => onRecover("cancel")} className="rounded border border-amber-500/20 px-3 py-1.5 font-semibold hover:bg-amber-500/10 transition-colors flex-1 text-amber-500/70 hover:text-amber-500">Cancel Loop</button>
          </div>
        </div>
      )}

      {/* Final status banner */}
      {(session.status !== "running" && session.status !== "waiting_for_recovery") && (
        <div className={`rounded-lg border p-3 text-xs ${
          session.status === "approved" ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-305" :
          session.status === "unresolved" ? "border-amber-500/40 bg-amber-500/10 text-amber-305" :
          "border-surface-600 bg-surface-800 text-slate-400"
        }`}>
          {session.status === "approved" && (
            <div className="space-y-2">
              <span className="flex items-center gap-1.5 text-[12px] font-semibold text-emerald-400">
                <CheckCircle2 size={14} /> Loop approved after {session.current_round} round{session.current_round !== 1 ? "s" : ""}
              </span>
              {session.final_proposal_id && (
                <div className="mt-2.5">
                  <PermissionGate
                    type="duo-finalize"
                    details="The generator and critic models have agreed on the solution. Finalize the Loop by reviewing the proposed diff in the AI Proposals tab."
                    onApprove={switchToDiff}
                    onReject={switchToDiff}
                  />
                </div>
              )}
            </div>
          )}
          {session.status === "unresolved" && (
            <div className="flex items-center justify-between">
              <span className="flex items-center gap-1.5 text-[12px] font-semibold">
                <AlertTriangle size={14} /> Unresolved after {session.max_rounds} rounds — review manually
              </span>
              {session.final_proposal_id && (
                <button
                  onClick={switchToDiff}
                  className="flex items-center gap-1 rounded bg-amber-500/20 border border-amber-500/40 px-2 py-1 text-[11px] text-amber-300 hover:bg-amber-500/30 transition-colors"
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
export function DuoPanel() {
  const currentWorkspace = useWorkspaceStore((s) => s.currentWorkspace);
  const models = useAIStore((s) => s.models);

  // Sync defaults from current AI store provider so Duo Loop uses whatever is already configured
  const aiPreset = useAIStore((s) => s.preset);
  const aiModel = useAIStore((s) => s.model);
  const aiBaseUrl = useAIStore((s) => s.baseUrl);
  const aiApiKeyProvider = useAIStore((s) => s.apiKeyProvider);

  const defaultProvider: ProviderConfig = {
    preset: aiPreset,
    model: aiModel,
    base_url: aiBaseUrl,
    api_key_provider: aiApiKeyProvider ?? undefined,
  };

  // Form state
  const [task, setTask] = useState("");
  const [generator, setGenerator] = useState<ProviderConfig>(defaultProvider);
  const [critic, setCritic] = useState<ProviderConfig>(defaultProvider);
  const [maxRounds, setMaxRounds] = useState(5);
  const [showHistory, setShowHistory] = useState(false);
  const [configuredKeys, setConfiguredKeys] = useState<string[]>([]);

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
        const res = await fetch(`${API}/api/duo/sessions/${sessionId}`);
        if (!res.ok) return;
        const data: DuoSession = await res.json();
        setActiveSession(data);
        if (data.status !== "running") {
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
        const res = await fetch(`${API}/api/duo/sessions?workspace=${encodeURIComponent(currentWorkspace.path)}`);
        if (res.ok) {
          const data: DuoSession[] = await res.json();
          setSessionHistory(data);
          // Restore most recent running session if any
          const running = data.find((s) => s.status === "running");
          if (running) {
            setActiveSession(running);
            startPolling(running.id);
          }
        }
      } catch { /* ignore */ }
    })();
  }, [currentWorkspace, startPolling]);

  const handleStart = async () => {
    if (!currentWorkspace || !task.trim() || !generator.model || !critic.model) return;
    setError(null);
    setStarting(true);

    // Map ProviderConfig → backend ModelConfig
    const toModelConfig = (cfg: ProviderConfig) => ({
      provider: cfg.preset === "ollama" ? "ollama" : "openai-compatible",
      model: cfg.model,
      base_url: cfg.base_url,
      api_key_provider: cfg.api_key_provider,
    });

    try {
      const res = await fetch(`${API}/api/duo/sessions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          workspace: currentWorkspace.path,
          task_description: task.trim(),
          generator: toModelConfig(generator),
          critic: toModelConfig(critic),
          max_rounds: maxRounds,
        }),
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail ?? "Failed to start session");
      }
      const session: DuoSession = await res.json();
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
      const res = await fetch(`${API}/api/duo/sessions/${activeSession.id}/cancel`, { method: "POST" });
      if (res.ok) {
        const updated: DuoSession = await res.json();
        setActiveSession(updated);
        if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
      }
    } catch { /* ignore */ }
  };

  const handleRecover = async (action: "retry" | "switch_to_api" | "cancel") => {
    if (!activeSession) return;
    try {
      await fetch(`${API}/api/duo/sessions/${activeSession.id}/recover`, { 
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action })
      });
      // Polling will catch the updated status
    } catch { /* ignore */ }
  };

  const canStart = !!(currentWorkspace && task.trim() && generator.model && critic.model && !starting && activeSession?.status !== "running");

  return (
    <div className="flex h-full flex-col bg-surface-900">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-surface-700 px-3 py-2 shrink-0">
        <div className="flex items-center gap-2">
          <Zap size={14} className="text-accent-400" />
          <span className="text-xs font-semibold text-white">Duo Loop</span>
          <span className="rounded bg-accent-500/15 border border-accent-500/30 px-1.5 py-px text-[9px] font-bold uppercase tracking-wide text-accent-400">
            Gen × Critic
          </span>
        </div>
        <button
          onClick={() => setShowHistory((v) => !v)}
          className={`flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] text-slate-400 hover:text-white transition-colors ${showHistory ? "bg-surface-700" : ""}`}
        >
          <History size={11} /> History ({sessionHistory.length})
        </button>
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto">
        <div className="p-3 space-y-3">
          {/* No workspace warning */}
          {!currentWorkspace && (
            <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 text-[11px] text-amber-300">
              Open a workspace folder first to use Duo Loop.
            </div>
          )}

          {/* Error */}
          {error && (
            <div className="rounded-lg border border-red-500/40 bg-red-500/10 p-2 text-[11px] text-red-300 flex items-start gap-2">
              <XCircle size={12} className="mt-0.5 shrink-0" />
              {error}
            </div>
          )}

          {/* Config form — hide when session is running */}
          {!activeSession || activeSession.status !== "running" ? (
            <>
              {/* Task */}
              <div>
                <label className="text-[10px] text-slate-500 mb-1 block font-semibold uppercase tracking-wider">Task Description</label>
                <textarea
                  rows={3}
                  placeholder="Describe what you want the Generator to build or fix…"
                  value={task}
                  onChange={(e) => setTask(e.target.value)}
                  className="w-full rounded-lg bg-surface-800 border border-surface-600 px-2.5 py-2 text-xs text-slate-200 placeholder:text-slate-600 focus:outline-none focus:border-accent-500 resize-none"
                />
              </div>

              {/* Model configs */}
              <ProviderSelector
                label="⚙ Generator"
                value={generator}
                onChange={setGenerator}
                configuredKeys={configuredKeys}
                models={models}
                compact
              />
              <ProviderSelector
                label="🔍 Critic"
                value={critic}
                onChange={setCritic}
                configuredKeys={configuredKeys}
                models={models}
                compact
              />

              {/* Max rounds */}
              <div className="flex items-center gap-2">
                <label className="text-[10px] text-slate-500 shrink-0 font-semibold uppercase tracking-wider">Max Rounds</label>
                <input
                  type="number"
                  min={1}
                  max={20}
                  value={maxRounds}
                  onChange={(e) => setMaxRounds(Math.max(1, Math.min(20, Number(e.target.value))))}
                  className="w-16 rounded bg-surface-800 border border-surface-600 px-2 py-1 text-xs text-slate-200 focus:outline-none focus:border-accent-500"
                />
                <span className="text-[10px] text-slate-600">Loop auto-stops when Critic approves or limit is reached</span>
              </div>

              {/* Start button */}
              <button
                onClick={() => void handleStart()}
                disabled={!canStart}
                className={`flex w-full items-center justify-center gap-2 rounded-lg px-4 py-2.5 text-sm font-semibold transition-all ${
                  canStart
                    ? "bg-accent-500 text-white hover:bg-accent-400 shadow-lg shadow-accent-500/20"
                    : "bg-surface-700 text-slate-500 cursor-not-allowed"
                }`}
              >
                {starting ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />}
                {starting ? "Starting…" : "Start Duo Loop"}
              </button>

              {/* Safety note */}
              <p className="text-[10px] text-slate-600 text-center leading-relaxed">
                The loop runs automatically but <span className="text-slate-400">never writes to disk</span> — all proposals require your approval in DiffViewer first.
              </p>
            </>
          ) : null}

          {/* Active session view */}
          {activeSession && (
            <div>
              {activeSession.status !== "running" && (
                <div className="flex items-center justify-between mb-2">
                  <span className="text-[10px] text-slate-500 font-semibold uppercase tracking-wider">Last Session</span>
                  <button
                    onClick={() => { setActiveSession(null); setTask(""); }}
                    className="text-[10px] text-accent-400 hover:text-accent-300"
                  >
                    + New session
                  </button>
                </div>
              )}
              <SessionView session={activeSession} onCancel={() => void handleCancel()} onRetry={() => void handleStart()} onRecover={(action) => void handleRecover(action)} />
            </div>
          )}

          {/* Session history */}
          {showHistory && sessionHistory.length > 0 && (
            <div className="mt-2 space-y-1.5">
              <div className="text-[10px] text-slate-500 font-semibold uppercase tracking-wider">Session History</div>
              {sessionHistory.map((s) => (
                <button
                  key={s.id}
                  onClick={() => { setActiveSession(s); setShowHistory(false); }}
                  className="w-full text-left rounded-lg border border-surface-700 bg-surface-900 hover:bg-surface-850 px-3 py-2 transition-colors"
                >
                  <div className="flex items-center justify-between mb-0.5">
                    <StatusBadge status={s.status} />
                    <span className="text-[9px] text-slate-600 flex items-center gap-0.5">
                      <Clock size={9} /> {new Date(s.created_at).toLocaleTimeString()}
                    </span>
                  </div>
                  <p className="text-[11px] text-slate-400 line-clamp-1">{s.task_description}</p>
                  <p className="text-[10px] text-slate-600 mt-0.5">
                    {s.generator.model} × {s.critic.model} — {s.current_round}/{s.max_rounds} rounds
                  </p>
                </button>
              ))}
            </div>
          )}

          {showHistory && sessionHistory.length === 0 && (
            <div className="text-center py-4 text-[11px] text-slate-600">No sessions yet</div>
          )}
        </div>
      </div>
    </div>
  );
}
