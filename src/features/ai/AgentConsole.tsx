import { useEffect, useState, useRef } from "react";
import {
  Play, Square, CheckCircle2, Circle, Loader2,
  Sparkles, Terminal, Cpu, Brain, ChevronDown, ChevronRight,
  FileCode, Zap, GitBranch, Shield, FlaskConical, Target, ShieldCheck
} from "lucide-react";
import { api } from "../../lib/api";
import { useWorkspaceStore } from "../../stores/workspaceStore";
import { useAIStore } from "../../stores/aiStore";
import { ProviderSelector, type ProviderConfig } from "../../components/ui/ProviderSelector";
import { getPreset } from "../../lib/providerPresets";

type Task = {
  id: string;
  title: string;
  agent_role: string;
  status: "queued" | "running" | "waiting" | "completed" | "failed" | "cancelled";
  dependencies: string[];
  assigned_agent: string | null;
  reasoning_summary: string;
  estimated_effort: string;
  started_at: string | null;
  completed_at: string | null;
  pending_action: {
    type: string;
    details: string;
    command?: string;
  } | null;
  structured_data?: {
    agent_type?: string;
    test_runner_detected?: boolean;
    test_results?: {
      total: number;
      passed: number;
      failed: number;
      skipped: number;
      errors: Array<{ test: string; status: string; error: string }>;
      duration?: string;
    };
    issues?: Array<{
      file: string;
      line: number;
      severity: string;
      category: string;
      description: string;
      suggested_fix: string;
    }>;
    approved?: boolean;
    files_modified?: number;
    model?: string;
    provider?: string;
    duo_escalation?: { invoked: boolean; rounds: number; status: string };
    diagnostics?: {
      llm_call_count: number;
      phase_timings_seconds: Record<string, number>;
      quick_edit: boolean;
      duo_escalated: boolean;
      duo_reasons: string[];
      trivial_change: boolean;
    };
  };
};

type Job = {
  id: string;
  workflow: string;
  status: string;
  progress: number;
  token_usage: number;
  duration: number;
  files_modified: string[];
  errors: string;
  logs: string[];
  tasks: Task[];
};

type LivePlan = {
  goal: string;
  hypothesis: string;
  files_to_touch: string[];
  approach: string;
  risks: string[];
  verification: string;
};

// ── Parse [PLAN_EMITTED] log entries ─────────────────────────────────────────
function extractLivePlan(logs: string[]): LivePlan | null {
  for (let i = logs.length - 1; i >= 0; i--) {
    const line = logs[i];
    const match = line.match(/\[PLAN_EMITTED\]\s+(\{.*\})/);
    if (match) {
      try {
        return JSON.parse(match[1]) as LivePlan;
      } catch {
        return null;
      }
    }
  }
  return null;
}

// ── Phase status badge ────────────────────────────────────────────────────────
function phaseBadge(logs: string[]) {
  const last = [...logs].reverse().find((l) =>
    l.includes("Phase 1") || l.includes("Phase 2") || l.includes("Phase 3") || l.includes("Phase 4") || l.includes("Grounding")
  );
  if (!last) return null;
  let label = "";
  let color = "text-blue-400 bg-blue-950/40 border-blue-800/50";
  if (last.includes("Phase 1")) { label = "Planning"; color = "text-violet-400 bg-violet-950/40 border-violet-800/50"; }
  else if (last.includes("Grounding")) { label = "Grounding"; color = "text-cyan-400 bg-cyan-950/40 border-cyan-800/50"; }
  else if (last.includes("Phase 2")) { label = "Generating"; color = "text-blue-400 bg-blue-950/40 border-blue-800/50"; }
  else if (last.includes("Phase 3")) { label = "Self-Review"; color = "text-amber-400 bg-amber-950/40 border-amber-800/50"; }
  else if (last.includes("Phase 4")) { label = "Testing"; color = "text-emerald-400 bg-emerald-950/40 border-emerald-800/50"; }
  return (
    <span className={`inline-flex items-center gap-1 text-[9px] font-mono font-bold px-1.5 py-0.5 rounded border animate-pulse ${color}`}>
      <Zap size={8} />
      {label}
    </span>
  );
}

// ── Granular Status Line Helper ─────────────────────────────────────────────
function getCurrentStatusLine(logs: string[]): { text: string; icon: string } | null {
  const reversed = [...logs].reverse();
  for (const line of reversed) {
    if (line.includes("Phase 1: Planning")) {
      return { text: "Generating implementation plan...", icon: "📝" };
    }
    if (line.includes("Grounding: reading")) {
      const match = line.match(/reading\s+([^\s]+)/);
      return { text: `Grounding context for ${match ? match[1].split(/[/\\]/).pop() : "files"}...`, icon: "🔍" };
    }
    if (line.includes("[EDITING]")) {
      const match = line.match(/\[EDITING\]\s+(.*)/);
      return { text: `Writing code proposal for ${match ? match[1].split(/[/\\]/).pop() : "files"}...`, icon: "✍️" };
    }
    if (line.includes("[EDITED]")) {
      const match = line.match(/\[EDITED\]\s+(.*)/);
      return { text: `Finished writing code for ${match ? match[1].split(/[/\\]/).pop() : "files"}`, icon: "✓" };
    }
    if (line.includes("Phase 3: Self-review")) {
      return { text: "Reviewing code proposals...", icon: "🔬" };
    }
    if (line.includes("Running affected tests")) {
      return { text: "Executing test suite...", icon: "🧪" };
    }
    if (line.includes("High-stakes task detected") || line.includes("Running inside internal DuoLoop")) {
      return { text: "Escalated to internal Duo loop...", icon: "👥" };
    }
  }
  return null;
}

// ── Live Plan Card ────────────────────────────────────────────────────────────
function LivePlanCard({ plan }: { plan: LivePlan }) {
  const [expanded, setExpanded] = useState(true);
  return (
    <div className="rounded-lg border border-violet-700/40 bg-gradient-to-br from-violet-950/30 to-surface-900/60 overflow-hidden">
      {/* Header */}
      <button
        className="w-full flex items-center justify-between px-3 py-2 text-left hover:bg-violet-900/10 transition-colors"
        onClick={() => setExpanded((v) => !v)}
      >
        <div className="flex items-center gap-2 min-w-0">
          <Brain size={13} className="text-violet-400 shrink-0 animate-pulse" />
          <span className="text-[11px] font-semibold text-violet-200 truncate">
            Live Agent Plan
          </span>
          <span className="text-[9px] font-mono text-violet-500 bg-violet-950/50 border border-violet-800/40 px-1.5 py-0.5 rounded shrink-0">
            {plan.files_to_touch.length} file{plan.files_to_touch.length !== 1 ? "s" : ""}
          </span>
        </div>
        {expanded
          ? <ChevronDown size={12} className="text-violet-500 shrink-0" />
          : <ChevronRight size={12} className="text-violet-500 shrink-0" />
        }
      </button>

      {expanded && (
        <div className="px-3 pb-3 space-y-2.5 border-t border-violet-800/30">
          {/* Goal */}
          <div className="pt-2.5">
            <div className="flex items-center gap-1.5 mb-1">
              <Target size={10} className="text-violet-400 shrink-0" />
              <span className="text-[9px] uppercase font-bold tracking-wider text-violet-500">Goal</span>
            </div>
            <p className="text-[11px] text-violet-100 leading-snug">{plan.goal}</p>
          </div>

          {/* Approach */}
          <div>
            <div className="flex items-center gap-1.5 mb-1">
              <GitBranch size={10} className="text-cyan-400 shrink-0" />
              <span className="text-[9px] uppercase font-bold tracking-wider text-cyan-600">Approach</span>
            </div>
            <p className="text-[10px] text-slate-300 leading-snug">{plan.approach}</p>
          </div>

          {/* Files to touch */}
          {plan.files_to_touch.length > 0 && (
            <div>
              <div className="flex items-center gap-1.5 mb-1.5">
                <FileCode size={10} className="text-on-surface-variant/60 dark:text-on-surface-variant/60 shrink-0" />
                <span className="text-[9px] uppercase font-bold tracking-wider text-on-surface-variant/60 dark:text-on-surface-variant/60">Files targeted</span>
              </div>
              <div className="flex flex-wrap gap-1">
                {plan.files_to_touch.map((f, i) => (
                  <span
                    key={i}
                    className="text-[9px] font-mono text-on-surface-variant dark:text-on-surface-variant bg-surface-container-high border border-outline-variant/20 px-1.5 py-0.5 rounded truncate max-w-[150px]"
                    title={f}
                  >
                    {f.split(/[/\\]/).pop()}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Risks */}
          {plan.risks && plan.risks.length > 0 && (
            <div>
              <div className="flex items-center gap-1.5 mb-1">
                <Shield size={10} className="text-tertiary-container shrink-0" />
                <span className="text-[9px] uppercase font-bold tracking-wider text-tertiary-container">Risks</span>
              </div>
              <ul className="space-y-0.5">
                {plan.risks.map((r, i) => (
                  <li key={i} className="text-[9px] text-tertiary/70 flex items-start gap-1">
                    <span className="text-tertiary-container mt-0.5 shrink-0">▸</span>
                    {r}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Verification */}
          {plan.verification && (
            <div>
              <div className="flex items-center gap-1.5 mb-1">
                <FlaskConical size={10} className="text-primary-container shrink-0" />
                <span className="text-[9px] uppercase font-bold tracking-wider text-primary-container">Verification</span>
              </div>
              <p className="text-[9px] text-primary/60 leading-snug">{plan.verification}</p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export function AgentConsole({ compact = false }: { compact?: boolean }) {
  const [requestText, setRequestText] = useState("");
  const [quickMode, setQuickMode] = useState(false);
  const [loading, setLoading] = useState(false);
  const [planTasks, setPlanTasks] = useState<Task[]>([]);
  const [activeJob, setActiveJob] = useState<Job | null>(null);
  const workspace = useWorkspaceStore((state) => state.currentWorkspace);
  const logsEndRef = useRef<HTMLDivElement>(null);

  // Local state for AgentConsole's provider/model selection
  const [providerConfig, setProviderConfig] = useState<ProviderConfig>({
    preset: "auto",
    model: "",
  });
  const [configuredKeys, setConfiguredKeys] = useState<string[]>([]);
  const models = useAIStore((s) => s.models);

  // Fetch configured API keys
  useEffect(() => {
    void api.get<{ provider_id: string; configured: boolean }[]>("/api/settings/api-keys")
      .then((keys) => setConfiguredKeys(keys.filter((k) => k.configured).map((k) => k.provider_id)))
      .catch(() => undefined);
  }, []);

  // Poll for and restore any active running job on workspace change / tab switch
  useEffect(() => {
    if (!workspace) {
      setActiveJob(null);
      setPlanTasks([]);
      return;
    }

    const restoreActiveJob = async () => {
      try {
        const jobs = await api.get<Job[]>(`/api/agents/jobs?workspace=${encodeURIComponent(workspace.path)}`);
        if (jobs && jobs.length > 0) {
          const active = jobs.find((j) => ["queued", "running", "waiting"].includes(j.status));
          if (active) {
            void fetchJobDetails(active.id);
          }
        }
      } catch (err) {
        console.error("Failed to restore active job:", err);
      }
    };

    void restoreActiveJob();
  }, [workspace?.path]);

  /** Build provider_config payload the backend expects */
  const buildProviderConfig = () => {
    const presetObj = getPreset(providerConfig.preset);
    return {
      provider: presetObj?.provider || (providerConfig.preset === "ollama" ? "ollama" : "openai-compatible"),
      preset: providerConfig.preset,
      model: providerConfig.model || presetObj?.model_example || "llama3",
      base_url: providerConfig.base_url || presetObj?.base_url,
      api_key_provider: providerConfig.api_key_provider || presetObj?.api_key_provider,
    };
  };

  // Auto-scroll logs
  useEffect(() => {
    logsEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [activeJob?.logs?.length]);

  // 1. Generate task plan
  const handleGeneratePlan = async () => {
    if (!workspace || !requestText.trim()) return;
    
    // Block agent execution in restricted mode
    const restrictedMode = useWorkspaceStore.getState().restrictedMode;
    if (restrictedMode) {
      alert("Agent execution is disabled in Restricted Mode. Switch to Trusted mode to enable autonomous agents.");
      return;
    }
    
    setLoading(true);
    try {
      const data = await api.post<{ tasks: Task[] }>("/api/agents/plan", {
        workspace: workspace.path,
        user_request: requestText + (quickMode ? " --quick" : ""),
        provider_config: buildProviderConfig(),
      });
      setPlanTasks(data.tasks);
      setActiveJob(null);
    } catch (err) {
      alert("Failed to plan tasks: " + (err instanceof Error ? err.message : String(err)));
    } finally {
      setLoading(false);
    }
  };

  // 2. Start planned workflow
  const handleStartWorkflow = async () => {
    if (!workspace || planTasks.length === 0) return;
    setLoading(true);
    try {
      const data = await api.post<{ job_id: string }>("/api/agents/jobs", {
        workspace: workspace.path,
        workflow: "Feature Development",
        tasks: planTasks,
        provider_config: buildProviderConfig(),
      });
      setPlanTasks([]);
      await fetchJobDetails(data.job_id);
    } catch (err) {
      alert("Failed to start workflow: " + (err instanceof Error ? err.message : String(err)));
    } finally {
      setLoading(false);
    }
  };

  // 3. Poll job details
  const fetchJobDetails = async (jobId: string) => {
    try {
      const data = await api.get<Job>(`/api/agents/jobs/${jobId}`);
      setActiveJob(data);
    } catch {
      setActiveJob(null);
    }
  };

  useEffect(() => {
    if (!activeJob || ["completed", "failed", "cancelled"].includes(activeJob.status)) return;
    const interval = setInterval(() => {
      void fetchJobDetails(activeJob.id);
    }, 2000);
    return () => clearInterval(interval);
  }, [activeJob?.id, activeJob?.status]);

  // 4. Cancel job
  const handleCancelJob = async (jobId: string) => {
    try {
      await api.post(`/api/agents/jobs/${jobId}/cancel`);
      await fetchJobDetails(jobId);
    } catch (err) {
      alert("Failed to cancel job: " + (err instanceof Error ? err.message : String(err)));
    }
  };

  // 5. Approve pending action
  const handleApproveAction = async (jobId: string, taskId: string) => {
    try {
      await api.post(`/api/agents/jobs/${jobId}/tasks/${taskId}/approve`);
      await fetchJobDetails(jobId);
    } catch (err) {
      alert("Failed to approve action: " + (err instanceof Error ? err.message : String(err)));
    }
  };

  // 6. Reject pending action
  const handleRejectAction = async (jobId: string, taskId: string) => {
    try {
      await api.post(`/api/agents/jobs/${jobId}/tasks/${taskId}/reject`);
      await fetchJobDetails(jobId);
    } catch (err) {
      alert("Failed to reject action: " + (err instanceof Error ? err.message : String(err)));
    }
  };

  // 7. Recover pending action (LLM failure / Task failure)
  const handleRecoverAction = async (jobId: string, taskId: string, action: "retry" | "switch_to_api" | "cancel" | "reduced_pipeline") => {
    try {
      await api.post(`/api/agents/jobs/${jobId}/tasks/${taskId}/recover`, { action });
      await fetchJobDetails(jobId);
    } catch (err) {
      alert("Failed to recover action: " + (err instanceof Error ? err.message : String(err)));
    }
  };

  const [clarificationText, setClarificationText] = useState("");

  // 8. Submit clarification answer
  const handleAnswerClarification = async (jobId: string, taskId: string) => {
    if (!clarificationText.trim()) return;
    try {
      await api.post(`/api/agents/jobs/${jobId}/tasks/${taskId}/answer`, { answer: clarificationText.trim() });
      setClarificationText("");
      await fetchJobDetails(jobId);
    } catch (err) {
      alert("Failed to submit clarification: " + (err instanceof Error ? err.message : String(err)));
    }
  };

  // Render structured output based on agent type
  const renderStructuredOutput = (task: Task) => {
    if (!task.structured_data) return null;
    const data = task.structured_data;

    // TesterAgent output
    if (data.agent_type === "tester" && data.test_results) {
      const results = data.test_results;
      return (
        <div className="mt-2 space-y-1.5 border-t border-surface-800 pt-2">
          <div className="grid grid-cols-4 gap-1 text-[9px] font-mono">
            <div className="text-slate-400">Total: {results.total}</div>
            <div className="text-emerald-400">Passed: {results.passed}</div>
            <div className="text-rose-400">Failed: {results.failed}</div>
            <div className="text-slate-500">Skipped: {results.skipped}</div>
          </div>
          {results.errors.length > 0 && (
            <div className="max-h-16 overflow-auto space-y-1">
              <div className="text-[9px] font-semibold text-rose-300">Failed Tests:</div>
              {results.errors.map((err, idx) => (
                <div key={idx} className="text-[9px] bg-rose-950/20 p-1 rounded border border-rose-900/30">
                  <div className="font-mono text-rose-300 truncate">{err.test}</div>
                  <div className="text-slate-400 truncate">{err.error}</div>
                </div>
              ))}
            </div>
          )}
        </div>
      );
    }

    // ReviewerAgent output
    if (data.agent_type === "reviewer" && data.issues) {
      return (
        <div className="mt-2 space-y-1.5 border-t border-surface-800 pt-2">
          <div className="flex justify-between items-center">
            <span className="text-[9px] font-semibold text-slate-300">
              {data.issues.length} issues found
            </span>
            <span className={`text-[9px] font-semibold px-1 rounded ${
              data.approved ? "bg-emerald-950/40 text-emerald-400" : "bg-rose-950/40 text-rose-400"
            }`}>
              {data.approved ? "APPROVED" : "NEEDS REVIEW"}
            </span>
          </div>
          {data.issues.length > 0 && (
            <div className="max-h-20 overflow-auto space-y-1">
              {data.issues.slice(0, 5).map((issue, idx) => (
                <div key={idx} className="text-[9px] bg-surface-950 p-1 rounded border border-surface-800">
                  <div className="flex justify-between items-start">
                    <span className="font-mono text-slate-300 truncate">{issue.file}:{issue.line}</span>
                    <span className={`text-[8px] uppercase font-semibold px-0.5 rounded ${
                      issue.severity === "high" ? "bg-rose-950/40 text-rose-400" :
                      issue.severity === "medium" ? "bg-yellow-950/40 text-yellow-400" :
                      "bg-surface-800 text-slate-400"
                    }`}>
                      {issue.severity}
                    </span>
                  </div>
                  <div className="text-slate-400 truncate">{issue.description}</div>
                </div>
              ))}
              {data.issues.length > 5 && (
                <div className="text-[9px] text-slate-500">+{data.issues.length - 5} more issues</div>
              )}
            </div>
          )}
        </div>
      );
    }

    // CoderAgent/DocumenterAgent output
    if ((data.agent_type === "coder" || data.agent_type === "documenter") && data.files_modified !== undefined) {
      return (
        <div className="mt-2 border-t border-surface-800 pt-2">
          <div className="text-[9px] text-slate-400">
            {data.files_modified} file{data.files_modified !== 1 ? "s" : ""} modified
          </div>
        </div>
      );
    }

    return null;
  };

  if (!workspace) {
    return (
      <section className="flex h-full flex-col items-center justify-center p-4 text-center space-y-2 select-none border-b border-surface-700 bg-surface-900">
        <Cpu size={22} className="text-slate-600 mb-1 animate-pulse" />
        <span className="text-xs text-slate-500">Open a workspace to access the Agent Console.</span>
      </section>
    );
  }

  // Find currently active task/agent for the observability inspector
  const activeTask = activeJob?.tasks.find((t) => t.status === "running" || t.status === "waiting");

  // Extract live plan from logs if job is running
  const livePlan = activeJob ? extractLivePlan(activeJob.logs) : null;

  /* ── Compact (sidebar) layout ─────────────────────────────────────────── */
  if (compact) {
    return (
      <main
        data-testid="agent-console-panel"
        className="flex flex-col h-full overflow-y-auto bg-[#131314] text-on-surface select-none"
      >
        {/* Compact Header */}
        <div className="flex items-center justify-between px-3 py-2 border-b border-white/5 shrink-0">
          <div className="flex items-center gap-1.5">
            <Cpu size={13} className="text-primary shrink-0" />
            <span className="text-[11px] font-bold text-on-surface tracking-tight">Agent Console</span>
            <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${
              activeJob && !["completed", "failed", "cancelled"].includes(activeJob.status)
                ? "bg-primary-container animate-pulse" : "bg-outline"
            }`} />
          </div>
          <div className="flex items-center gap-1">
            {activeJob && !["completed", "failed", "cancelled"].includes(activeJob.status) ? (
              <button
                onClick={() => void handleCancelJob(activeJob.id)}
                className="text-[9px] text-error hover:bg-error/10 border border-error/30 px-1.5 py-0.5 rounded font-mono font-bold"
                title="Cancel running workflow"
              >
                Cancel
              </button>
            ) : activeJob ? (
              <button
                onClick={() => { setActiveJob(null); setPlanTasks([]); setRequestText(""); }}
                className="text-[9px] text-primary hover:bg-primary/10 border border-primary/30 px-1.5 py-0.5 rounded font-mono font-bold"
              >
                + New Task
              </button>
            ) : null}
            <span className="font-mono text-[9px] text-on-surface-variant bg-surface-container px-1.5 py-0.5 rounded border border-white/5">
              {activeJob ? `${activeJob.duration.toFixed(1)}s` : "READY"}
            </span>
          </div>
        </div>

        {/* Compact body: scrollable, single column */}
        <div className="flex flex-col gap-2 p-2 overflow-y-auto flex-1 min-h-0">

          {/* Instruction textarea */}
          <div className="glass-panel rounded-md p-2 flex flex-col gap-1.5">
            <div className="flex justify-between items-center">
              <span className="text-[9px] font-bold uppercase tracking-wider text-outline">Instruction</span>
              <ProviderSelector
                value={providerConfig}
                onChange={setProviderConfig}
                configuredKeys={configuredKeys}
                models={models}
                compact
              />
            </div>
            <textarea
              className="w-full bg-surface-container-lowest border-0 border-b border-primary/30 focus:border-primary text-on-surface font-mono text-[10px] resize-none h-16 p-1.5 transition-colors outline-none rounded"
              placeholder="e.g. Add rate-limiting middleware..."
              value={requestText}
              onChange={(e) => setRequestText(e.target.value)}
              disabled={loading}
              onKeyDown={(e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) void handleGeneratePlan(); }}
            />
            <div className="flex items-center justify-between">
              <label className="flex items-center gap-1 text-[9px] text-on-surface-variant cursor-pointer">
                <input
                  type="checkbox"
                  checked={quickMode}
                  onChange={(e) => setQuickMode(e.target.checked)}
                  disabled={loading}
                  className="rounded border-white/20 bg-surface text-primary focus:ring-primary w-2.5 h-2.5"
                />
                <span>⚡ Quick</span>
              </label>
              <button
                onClick={() => void handleGeneratePlan()}
                disabled={loading || !requestText.trim()}
                className="bg-primary/10 text-primary border border-primary/30 hover:bg-primary/20 px-2.5 py-1 rounded-full text-[9px] font-semibold transition-all flex items-center gap-1 disabled:opacity-50"
              >
                <Sparkles size={9} />
                {loading ? "Planning…" : "Generate Plan"}
              </button>
            </div>
          </div>

          {/* Approval / Clarification required */}
          {activeTask?.pending_action && (
            <div className={`glass-panel rounded-md p-2 flex flex-col gap-2 relative overflow-hidden ${
              activeTask.pending_action.type === "clarification" ? "border-amber-500/30 bg-amber-950/20" : "border-error/30 bg-error-container/10"
            }`}>
              <div className={`absolute top-0 left-0 w-0.5 h-full ${
                activeTask.pending_action.type === "clarification" ? "bg-amber-500" : "bg-error"
              }`} />
              <div className={`flex items-center gap-1.5 text-[10px] font-bold ${
                activeTask.pending_action.type === "clarification" ? "text-amber-400" : "text-error"
              }`}>
                <span className="material-symbols-outlined text-xs">
                  {activeTask.pending_action.type === "llm_failure" ? "error_med" :
                   activeTask.pending_action.type === "clarification" ? "help" : "warning"}
                </span>
                {activeTask.pending_action.type === "llm_failure" ? "LLM FAILURE" :
                 activeTask.pending_action.type === "clarification" ? "CLARIFICATION NEEDED" : "APPROVAL NEEDED"}
              </div>
              <p className="text-[9px] text-on-surface-variant leading-snug">{activeTask.pending_action.details}</p>

              {activeTask.pending_action.type === "clarification" ? (
                <div className="flex flex-col gap-1.5 mt-1">
                  <textarea
                    rows={2}
                    value={clarificationText}
                    onChange={(e) => setClarificationText(e.target.value)}
                    placeholder="Type your clarification answer..."
                    className="w-full bg-surface-container-lowest text-on-surface text-[10px] border border-amber-500/30 focus:border-amber-400 p-1.5 rounded outline-none font-mono resize-none"
                  />
                  <div className="flex gap-1.5 justify-end">
                    <button
                      onClick={() => void handleRejectAction(activeJob!.id, activeTask.id)}
                      className="text-[9px] border border-outline px-2 py-0.5 rounded text-on-surface-variant"
                    >
                      Cancel
                    </button>
                    <button
                      onClick={() => void handleAnswerClarification(activeJob!.id, activeTask.id)}
                      disabled={!clarificationText.trim()}
                      className="text-[9px] bg-amber-500/20 border border-amber-500/40 text-amber-300 font-bold px-2.5 py-0.5 rounded disabled:opacity-40"
                    >
                      Submit Answer
                    </button>
                  </div>
                </div>
              ) : activeTask.pending_action.type === "task_failure" ? (
                <div className="flex flex-col gap-1.5 mt-1">
                  <button
                    onClick={() => void handleRecoverAction(activeJob!.id, activeTask.id, "retry")}
                    className="text-[9px] bg-primary/10 border border-primary/30 text-primary hover:bg-primary/20 px-2 py-1 rounded text-left font-bold transition-colors"
                  >
                    🔄 Try Again (Re-ground & Retry)
                  </button>
                  <button
                    onClick={() => void handleRecoverAction(activeJob!.id, activeTask.id, "reduced_pipeline")}
                    className="text-[9px] bg-amber-500/10 border border-amber-500/30 text-amber-300 hover:bg-amber-500/20 px-2 py-1 rounded text-left font-bold transition-colors"
                  >
                    ⚡ Continue with Reduced Pipeline (Skip Review/Docs)
                  </button>
                  <button
                    onClick={() => void handleRecoverAction(activeJob!.id, activeTask.id, "cancel")}
                    className="text-[9px] border border-outline px-2 py-1 rounded text-left text-on-surface-variant hover:bg-white/5 transition-colors"
                  >
                    🛑 Cancel Workflow
                  </button>
                </div>
              ) : activeTask.pending_action.type === "llm_failure" ? (
                <div className="flex gap-1.5 flex-wrap">
                  <button onClick={() => void handleRecoverAction(activeJob!.id, activeTask.id, "retry")} className="text-[9px] bg-primary/10 border border-primary/30 text-primary px-2 py-0.5 rounded">Retry</button>
                  <button onClick={() => void handleRecoverAction(activeJob!.id, activeTask.id, "switch_to_api")} className="text-[9px] bg-secondary/10 border border-secondary/30 text-secondary px-2 py-0.5 rounded">Use API</button>
                  <button onClick={() => void handleRecoverAction(activeJob!.id, activeTask.id, "cancel")} className="text-[9px] border border-outline px-2 py-0.5 rounded text-on-surface-variant">Cancel</button>
                </div>
              ) : (
                <div className="flex gap-1.5 flex-wrap">
                  <button onClick={() => void handleRejectAction(activeJob!.id, activeTask.id)} className="text-[9px] bg-error/10 border border-error/30 text-error px-2 py-0.5 rounded">Deny</button>
                  <button onClick={() => void handleApproveAction(activeJob!.id, activeTask.id)} className="text-[9px] border border-outline px-2 py-0.5 rounded text-on-surface">Approve</button>
                </div>
              )}
            </div>
          )}

          {/* Planned tasks */}
          {planTasks.length > 0 && (
            <div className="glass-panel rounded-md p-2 border-primary/20 bg-primary/5 flex flex-col gap-1.5">
              <div className="flex justify-between items-center">
                <span className="text-[9px] font-bold text-primary uppercase">Plan ({planTasks.length} tasks)</span>
                <button
                  onClick={() => void handleStartWorkflow()}
                  disabled={loading}
                  className="text-[9px] bg-primary-container text-on-primary-container px-2 py-0.5 rounded-full font-bold"
                >
                  Execute
                </button>
              </div>
              {planTasks.map((t, idx) => (
                <div key={t.id} className="text-[9px] bg-surface-container-low border border-white/5 rounded p-1.5">
                  <span className="font-bold text-on-surface">Step {idx + 1}: {t.agent_role}</span>
                  <p className="text-on-surface-variant mt-0.5 leading-snug truncate">{t.title}</p>
                </div>
              ))}
            </div>
          )}

          {/* Execution timeline */}
          <div className="glass-panel rounded-md p-2 flex flex-col gap-1">
            <span className="text-[9px] font-bold uppercase tracking-wider text-outline mb-1">Execution Flow</span>
            <div className="relative pl-4 space-y-2 overflow-y-auto max-h-40">
              <div className="absolute top-1 bottom-1 left-[7px] w-px bg-white/10" />
              {activeJob?.tasks.map((task, idx) => (
                <div key={task.id} className="relative">
                  <div className={`absolute left-[-16px] top-1 w-2.5 h-2.5 rounded-full z-10 flex items-center justify-center ${
                    task.status === "completed" ? "bg-primary-container" :
                    task.status === "running" ? "bg-surface-container border border-primary-container animate-pulse" :
                    "bg-surface-container border border-outline-variant"
                  }`}>
                    {task.status === "completed" && <span className="material-symbols-outlined text-[8px] text-on-primary-container">check</span>}
                  </div>
                  <div className={`rounded p-1.5 border text-[9px] ${
                    task.status === "completed" ? "bg-surface-container-low border-white/5 opacity-80" :
                    task.status === "running" ? "bg-surface-container border-primary/30" :
                    "bg-surface-container-lowest border-white/5 opacity-50"
                  }`}>
                    <div className="flex justify-between items-center">
                      <span className="font-semibold text-on-surface">{task.agent_role}</span>
                      <span className="text-primary-container uppercase text-[8px]">{task.status}</span>
                    </div>
                    <p className="text-on-surface-variant leading-snug truncate mt-0.5">{task.title}</p>
                  </div>
                </div>
              )) ?? (
                <div className="text-[9px] text-outline-variant italic">No active workflow. Generate a plan to begin.</div>
              )}
            </div>
          </div>

          {/* Live logs */}
          <div className="glass-panel rounded-md flex flex-col overflow-hidden shrink-0">
            <div className="bg-surface-container-high px-2 py-1 border-b border-white/5 flex justify-between items-center">
              <div className="flex items-center gap-1">
                <Terminal size={10} className="text-on-surface-variant" />
                <span className="text-[9px] uppercase tracking-wider text-outline">Live Logs</span>
              </div>
              <span className="w-1.5 h-1.5 rounded-full bg-[#00ff00] animate-pulse" />
            </div>
            <div className="p-2 font-mono text-[9px] leading-relaxed text-on-surface-variant overflow-y-auto max-h-28 bg-surface-container-lowest">
              {activeJob?.logs.map((log, i) => (
                <div key={i} className="mb-0.5">{log}</div>
              )) ?? (
                <div className="text-outline-variant">[init] Waiting for task…</div>
              )}
              <div ref={logsEndRef} />
            </div>
          </div>

        </div>
      </main>
    );
  }

  /* ── Full (topbar) layout — unchanged ──────────────────────────────────── */
  return (
    <main data-testid="agent-console-panel" className="flex-1 overflow-y-auto p-3 sm:p-4 md:p-6 flex flex-col gap-3 sm:gap-6 bg-[#131314] text-on-surface h-full select-none">

      {/* Page Header */}
      <div className="flex justify-between items-center pb-2 sm:pb-4 border-b border-white/5 shrink-0 flex-wrap gap-2">
        <div>
          <h1 className="font-bold text-on-surface text-base sm:text-headline-lg">Agent Console</h1>
          <div className="flex items-center gap-2">
            <span className={`w-2 h-2 rounded-full ${activeJob && !["completed", "failed", "cancelled"].includes(activeJob.status) ? "bg-primary-container animate-pulse" : "bg-outline"}`} />
            <span className="font-micro-label text-micro-label text-primary-container">
              {activeJob && !["completed", "failed", "cancelled"].includes(activeJob.status) ? "WORKING" : "READY"}
            </span>
          </div>
        </div>
        <div className="flex items-center gap-3">
          {activeJob && !["completed", "failed", "cancelled"].includes(activeJob.status) ? (
            <button
              onClick={() => void handleCancelJob(activeJob.id)}
              className="bg-error/10 border border-error/30 text-error hover:bg-error/20 px-3 py-1.5 rounded text-xs font-bold transition-colors"
            >
              Cancel Workflow
            </button>
          ) : activeJob ? (
            <button
              onClick={() => { setActiveJob(null); setPlanTasks([]); setRequestText(""); }}
              className="bg-primary/10 border border-primary/30 text-primary hover:bg-primary/20 px-3 py-1.5 rounded text-xs font-bold transition-colors"
            >
              + New Task
            </button>
          ) : null}
          <div className="text-on-surface-variant flex items-center gap-2 font-code-block text-[11px] sm:text-xs bg-surface-container py-1 px-2.5 rounded border border-white/5">
            <span className="material-symbols-outlined text-xs sm:text-sm">timer</span>
            <span>{activeJob ? `${activeJob.duration.toFixed(1)}s` : "00:00:00"}</span>
          </div>
        </div>
      </div>

      {/* Main Layout Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-3 sm:gap-6 flex-1 min-h-0">
        {/* Left Column: Input & Actions */}
        <div className="lg:col-span-7 flex flex-col gap-3 sm:gap-6">
          {/* Instruction Input Card */}
          <div className="glass-panel rounded-lg p-3 sm:p-4 md:p-6 flex flex-col gap-2 sm:gap-4">
            <div className="flex justify-between items-center mb-1 flex-wrap gap-1">
              <span className="font-micro-label text-micro-label text-outline uppercase">Agent Instruction</span>
              <ProviderSelector
                value={providerConfig}
                onChange={setProviderConfig}
                configuredKeys={configuredKeys}
                models={models}
                compact
              />
            </div>
            <textarea
              className="w-full bg-surface-container-lowest border-0 border-b-2 border-primary/30 focus:border-primary focus:ring-0 text-on-surface font-code-block text-xs sm:text-sm resize-none h-24 sm:h-32 p-2 sm:p-3 transition-colors outline-none rounded"
              placeholder="Enter task instruction here (e.g. Add a rate-limiting middleware to the auth routes with unit tests...)"
              value={requestText}
              onChange={(e) => setRequestText(e.target.value)}
              disabled={loading}
              onKeyDown={(e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) void handleGeneratePlan(); }}
            />
            <div className="flex justify-between items-center mt-1 flex-wrap gap-2">
              <label className="flex items-center gap-1.5 text-[11px] sm:text-xs text-on-surface-variant cursor-pointer select-none">
                <input
                  type="checkbox"
                  checked={quickMode}
                  onChange={(e) => setQuickMode(e.target.checked)}
                  disabled={loading}
                  className="rounded border-white/20 bg-surface text-primary focus:ring-primary"
                />
                <span>⚡ Quick Edit Mode</span>
              </label>

              <button
                onClick={() => void handleGeneratePlan()}
                disabled={loading || !requestText.trim()}
                className="bg-primary/10 text-primary border border-primary/30 hover:bg-primary/20 px-3 sm:px-6 py-1.5 sm:py-2 rounded-full text-xs sm:text-sm font-semibold transition-all flex items-center gap-1.5 shadow-[0_0_15px_rgba(0,229,255,0.15)] disabled:opacity-50"
              >

                <span className="material-symbols-outlined text-sm">play_arrow</span>
                <span>{loading ? "Planning..." : "Generate Plan"}</span>
              </button>
            </div>
          </div>

          {/* Pending Approval / Planned Tasks */}
          {planTasks.length > 0 && (
            <div className="glass-panel rounded-lg p-6 flex flex-col gap-4 border-primary/30 bg-primary/5">
              <div className="flex justify-between items-center">
                <span className="font-micro-label text-micro-label text-primary uppercase font-bold">PLANNED WORKFLOW ({planTasks.length} TASKS)</span>
                <button
                  onClick={() => void handleStartWorkflow()}
                  disabled={loading}
                  className="bg-primary-container text-on-primary-container font-micro-label text-micro-label px-4 py-2 rounded-full font-bold uppercase tracking-wider shadow-[0_0_12px_rgba(0,229,255,0.4)]"
                >
                  Execute Planned Agent Workflow
                </button>
              </div>
              <div className="space-y-2">
                {planTasks.map((t, idx) => (
                  <div key={t.id} className="p-3 rounded bg-surface-container-low border border-white/5 flex items-center justify-between text-xs">
                    <div>
                      <span className="font-bold text-on-surface">Step {idx + 1}: {t.agent_role}</span>
                      <p className="text-on-surface-variant text-[11px] mt-0.5">{t.title}</p>
                    </div>
                    <span className="font-micro-label text-micro-label text-outline uppercase">{t.estimated_effort}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Approval Required Card (when active task requires user input) */}
          {activeTask?.pending_action && (
            <div className={`glass-panel rounded-lg p-6 flex flex-col gap-4 relative overflow-hidden ${
              activeTask.pending_action.type === "clarification" ? "border-amber-500/40 bg-amber-950/20" : "border-error/30 bg-error-container/10"
            }`}>
              <div className={`absolute top-0 left-0 w-1 h-full ${
                activeTask.pending_action.type === "clarification" ? "bg-amber-500" : "bg-error"
              }`} />
              <div className={`flex items-center gap-3 ${
                activeTask.pending_action.type === "clarification" ? "text-amber-400" : "text-error"
              }`}>
                <span className="material-symbols-outlined">
                  {activeTask.pending_action.type === "llm_failure" ? "error_med" :
                   activeTask.pending_action.type === "clarification" ? "help" : "warning"}
                </span>
                <span className="font-headline-md text-headline-md text-base font-bold">
                  {activeTask.pending_action.type === "llm_failure" ? "LLM CONNECTION FAILURE" :
                   activeTask.pending_action.type === "clarification" ? "CLARIFICATION NEEDED" : "APPROVAL REQUIRED"}
                </span>
              </div>
              <p className="font-body-sm text-body-sm text-on-surface-variant leading-relaxed">
                {activeTask.pending_action.details}
              </p>

              {activeTask.pending_action.type === "clarification" ? (
                <div className="flex flex-col gap-3 mt-1">
                  <textarea
                    rows={3}
                    value={clarificationText}
                    onChange={(e) => setClarificationText(e.target.value)}
                    placeholder="Type your clarification answer for the agent..."
                    className="w-full bg-surface-container-lowest text-on-surface text-xs sm:text-sm border border-amber-500/30 focus:border-amber-400 p-3 rounded outline-none font-mono resize-none"
                  />
                  <div className="flex gap-3 justify-end">
                    <button
                      onClick={() => void handleRejectAction(activeJob!.id, activeTask.id)}
                      className="bg-surface-container border border-outline px-4 py-1.5 rounded font-body-sm text-body-sm text-on-surface hover:bg-white/5 transition-colors"
                    >
                      Cancel
                    </button>
                    <button
                      onClick={() => void handleAnswerClarification(activeJob!.id, activeTask.id)}
                      disabled={!clarificationText.trim()}
                      className="bg-amber-500 text-slate-950 px-5 py-1.5 rounded font-body-sm text-body-sm font-bold hover:bg-amber-400 transition-colors disabled:opacity-40"
                    >
                      Submit Answer
                    </button>
                  </div>
                </div>
              ) : activeTask.pending_action.type === "task_failure" ? (
                <div className="flex flex-wrap gap-3 mt-2">
                  <button
                    onClick={() => void handleRecoverAction(activeJob!.id, activeTask.id, "retry")}
                    className="bg-primary text-on-primary px-4 py-2 rounded font-body-sm text-body-sm font-semibold hover:bg-primary/90 transition-colors flex items-center gap-1.5"
                  >
                    <span>🔄</span>
                    <span>Try Again (Re-ground & Retry)</span>
                  </button>
                  <button
                    onClick={() => void handleRecoverAction(activeJob!.id, activeTask.id, "reduced_pipeline")}
                    className="bg-amber-500 text-slate-950 px-4 py-2 rounded font-body-sm text-body-sm font-bold hover:bg-amber-400 transition-colors flex items-center gap-1.5"
                  >
                    <span>⚡</span>
                    <span>Continue with Reduced Pipeline (Skip Review/Docs)</span>
                  </button>
                  <button
                    onClick={() => void handleRecoverAction(activeJob!.id, activeTask.id, "cancel")}
                    className="bg-surface-container border border-outline px-4 py-2 rounded font-body-sm text-body-sm text-on-surface hover:bg-white/5 transition-colors flex items-center gap-1.5"
                  >
                    <span>🛑</span>
                    <span>Cancel Workflow</span>
                  </button>
                </div>
              ) : activeTask.pending_action.type === "llm_failure" ? (
                <div className="flex flex-wrap gap-3 mt-2">
                  <button
                    onClick={() => void handleRecoverAction(activeJob!.id, activeTask.id, "retry")}
                    className="bg-primary text-on-primary px-4 py-1.5 rounded font-body-sm text-body-sm font-semibold hover:bg-primary/90 transition-colors"
                  >
                    Retry Local Model
                  </button>
                  <button
                    onClick={() => void handleRecoverAction(activeJob!.id, activeTask.id, "switch_to_api")}
                    className="bg-secondary text-on-secondary px-4 py-1.5 rounded font-body-sm text-body-sm font-semibold hover:bg-secondary/90 transition-colors"
                  >
                    Switch to Cloud API
                  </button>
                  <button
                    onClick={() => void handleRecoverAction(activeJob!.id, activeTask.id, "cancel")}
                    className="bg-surface-container border border-outline px-4 py-1.5 rounded font-body-sm text-body-sm text-on-surface hover:bg-white/5 transition-colors"
                  >
                    Cancel Workflow
                  </button>
                </div>
              ) : (
                <div className="flex flex-wrap gap-3 mt-2">
                  <button
                    onClick={() => void handleRejectAction(activeJob!.id, activeTask.id)}
                    className="bg-error text-on-error px-4 py-1.5 rounded font-body-sm text-body-sm font-semibold hover:bg-error/90 transition-colors"
                  >
                    Deny Action
                  </button>
                  <button
                    onClick={() => void handleApproveAction(activeJob!.id, activeTask.id)}
                    className="bg-surface-container border border-outline px-4 py-1.5 rounded font-body-sm text-body-sm text-on-surface hover:bg-white/5 transition-colors"
                  >
                    Approve
                  </button>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Right Column: Timeline & Logs */}
        <div className="lg:col-span-5 flex flex-col gap-3 sm:gap-6 h-full min-w-0">
          {/* Execution Flow Timeline */}
          <div className="glass-panel rounded-lg p-3 sm:p-4 md:p-6 flex-1 flex flex-col min-h-[180px]">
            <span className="font-micro-label text-micro-label text-outline uppercase mb-3 sm:mb-6 block">Execution Flow</span>
            <div className="relative pl-5 sm:pl-6 flex-1 overflow-y-auto max-h-[300px] lg:max-h-none">
              <div className="absolute top-2 bottom-2 left-[11px] w-px bg-white/10" />

              {activeJob?.tasks.map((task, idx) => (
                <div key={task.id} className="relative mb-4 sm:mb-6">
                  <div className={`absolute left-[-22px] sm:left-[-24px] top-1 w-3 h-3 rounded-full z-10 flex items-center justify-center ${
                    task.status === "completed" ? "bg-primary-container shadow-[0_0_8px_rgba(0,229,255,0.5)]" :
                    task.status === "running" ? "bg-surface-container border-2 border-primary-container animate-pulse" :
                    "bg-surface-container border border-outline-variant"
                  }`}>
                    {task.status === "completed" && <span className="material-symbols-outlined text-[10px] text-on-primary-container font-bold">check</span>}
                  </div>
                  <div className={`rounded p-2.5 sm:p-3 border ${
                    task.status === "completed" ? "bg-surface-container-low border-white/5 opacity-80" :
                    task.status === "running" ? "bg-surface-container border-primary/30" :
                    "bg-surface-container-lowest border-white/5 opacity-50"
                  }`}>
                    <div className="flex justify-between items-center mb-1 flex-wrap gap-1">
                      <span className="font-body-sm text-[11px] sm:text-xs font-semibold text-on-surface">Step {idx + 1}: {task.agent_role}</span>
                      <span className="font-micro-label text-[9px] text-primary-container uppercase">{task.status}</span>
                    </div>
                    <p className="font-code-block text-[10px] sm:text-xs text-on-surface-variant leading-snug">{task.title}</p>
                    {renderStructuredOutput(task)}
                  </div>
                </div>
              )) ?? (
                <div className="text-xs text-outline-variant italic">No active workflow running. Generate a plan to begin execution.</div>
              )}
            </div>
          </div>

          {/* Live Terminal Logs */}
          <div className="glass-panel rounded-lg flex flex-col overflow-hidden h-[180px] sm:h-[200px] shrink-0">
            <div className="bg-surface-container-high px-3 py-1.5 border-b border-white/5 flex justify-between items-center">
              <div className="flex items-center gap-2">
                <span className="material-symbols-outlined text-xs sm:text-sm text-on-surface-variant">terminal</span>
                <span className="font-micro-label text-[9px] sm:text-micro-label text-outline uppercase">Live Terminal Logs</span>
              </div>
              <span className="w-1.5 h-1.5 rounded-full bg-[#00ff00] animate-pulse" />
            </div>
            <div className="p-2.5 sm:p-4 font-code-block text-[10px] sm:text-[11px] leading-relaxed text-on-surface-variant overflow-y-auto flex-1 bg-surface-container-lowest font-mono">

              {activeJob?.logs.map((log, i) => (
                <div key={i} className="mb-1">{log}</div>
              )) ?? (
                <div className="text-outline-variant">[00:00:00] System initialized. Waiting for task...</div>
              )}
              <div ref={logsEndRef} />
            </div>
          </div>
        </div>
      </div>
    </main>
  );
}
