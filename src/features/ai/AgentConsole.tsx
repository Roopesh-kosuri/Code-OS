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
                <FileCode size={10} className="text-slate-400 shrink-0" />
                <span className="text-[9px] uppercase font-bold tracking-wider text-slate-500">Files targeted</span>
              </div>
              <div className="flex flex-wrap gap-1">
                {plan.files_to_touch.map((f, i) => (
                  <span
                    key={i}
                    className="text-[9px] font-mono text-slate-300 bg-surface-800 border border-surface-700 px-1.5 py-0.5 rounded truncate max-w-[150px]"
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
                <Shield size={10} className="text-amber-400 shrink-0" />
                <span className="text-[9px] uppercase font-bold tracking-wider text-amber-600">Risks</span>
              </div>
              <ul className="space-y-0.5">
                {plan.risks.map((r, i) => (
                  <li key={i} className="text-[9px] text-amber-200/70 flex items-start gap-1">
                    <span className="text-amber-600 mt-0.5 shrink-0">▸</span>
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
                <FlaskConical size={10} className="text-emerald-400 shrink-0" />
                <span className="text-[9px] uppercase font-bold tracking-wider text-emerald-600">Verification</span>
              </div>
              <p className="text-[9px] text-emerald-200/60 leading-snug">{plan.verification}</p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export function AgentConsole() {
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
    return {
      provider: providerConfig.preset,
      model: providerConfig.model,
      base_url: providerConfig.base_url,
      api_key_provider: providerConfig.api_key_provider,
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

  // 7. Recover pending action (LLM failure)
  const handleRecoverAction = async (jobId: string, taskId: string, action: "retry" | "switch_to_api" | "cancel") => {
    try {
      await api.post(`/api/agents/jobs/${jobId}/tasks/${taskId}/recover`, { action });
      await fetchJobDetails(jobId);
    } catch (err) {
      alert("Failed to recover action: " + (err instanceof Error ? err.message : String(err)));
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

  return (
    <section className="grid h-full min-h-0 w-full min-w-0 grid-cols-1 grid-rows-[38px_minmax(0,1fr)] border-b border-surface-700">
      {/* Header */}
      <div className="flex items-center gap-2 border-b border-surface-700 px-3 py-1">
        <Cpu size={15} className="text-accent-400" />
        <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">Agent Command Console</span>
        {activeJob && !["completed", "failed", "cancelled"].includes(activeJob.status) && phaseBadge(activeJob.logs)}
      </div>

      <div className="overflow-auto p-3 text-xs space-y-4 min-h-0 flex flex-col justify-between">
        <div className="space-y-4">

          {/* ── Instructions Input ─────────────────────────────────────────── */}
          {!activeJob && planTasks.length === 0 && (
            <div className="space-y-3">
              <div className="flex items-center gap-2">
                <Brain size={13} className="text-violet-400" />
                <span className="font-semibold text-slate-300">New Autonomous Request</span>
              </div>
              
              <ProviderSelector
                value={providerConfig}
                onChange={setProviderConfig}
                configuredKeys={configuredKeys}
                models={models}
                compact
              />

              <textarea
                className="w-full h-20 rounded-lg border border-surface-700 bg-surface-950 text-slate-200 text-xs p-3 focus:outline-none focus:border-violet-600/60 focus:ring-1 focus:ring-violet-600/20 resize-none placeholder-slate-600 transition-all"
                placeholder="e.g. Add a rate-limiting middleware to the FastAPI auth routes with unit tests..."
                value={requestText}
                onChange={(e) => setRequestText(e.target.value)}
                disabled={loading}
                onKeyDown={(e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) void handleGeneratePlan(); }}
              />

              <div className="flex items-center gap-2 select-none">
                <input
                  type="checkbox"
                  id="quick-edit-mode"
                  checked={quickMode}
                  onChange={(e) => setQuickMode(e.target.checked)}
                  disabled={loading}
                  className="rounded border-surface-700 bg-surface-950 text-violet-600 focus:ring-violet-500 w-3 h-3 cursor-pointer disabled:opacity-50"
                />
                <label htmlFor="quick-edit-mode" className="text-[10px] text-slate-400 cursor-pointer font-medium hover:text-slate-200 transition-colors flex items-center gap-1 disabled:opacity-50">
                  ⚡ Quick Edit Mode <span className="text-slate-600">(skips planning, reviews, and testing)</span>
                </label>
              </div>

              {/* Premium Plan Button */}
              <button
                id="plan-autonomous-workflow-btn"
                className={`
                  w-full relative overflow-hidden rounded-lg px-4 py-2.5
                  flex items-center justify-center gap-2
                  font-semibold text-xs tracking-wide
                  transition-all duration-200
                  ${loading || !requestText.trim()
                    ? "opacity-50 cursor-not-allowed bg-surface-800 text-slate-500 border border-surface-700"
                    : "bg-gradient-to-r from-violet-600 via-accent-600 to-violet-600 bg-size-200 bg-pos-0 hover:bg-pos-100 text-white shadow-lg shadow-violet-500/20 hover:shadow-violet-500/40 border border-violet-500/30 active:scale-[0.98]"
                  }
                `}
                onClick={() => void handleGeneratePlan()}
                disabled={loading || !requestText.trim()}
              >
                {/* Animated shimmer overlay */}
                {!loading && requestText.trim() && (
                  <span className="absolute inset-0 bg-gradient-to-r from-transparent via-white/5 to-transparent translate-x-[-100%] hover:translate-x-[100%] transition-transform duration-700 pointer-events-none" />
                )}
                {loading
                  ? <Loader2 size={13} className="animate-spin shrink-0" />
                  : <Sparkles size={13} className="shrink-0" />
                }
                <span>{loading ? "Planning agent workflow…" : "Plan Autonomous Agent Workflow"}</span>
              </button>
              <p className="text-[9px] text-slate-600 text-center">⌘+Enter to plan · Plans are reviewed before execution</p>
            </div>
          )}

          {/* ── Checklist Plan Review ──────────────────────────────────────── */}
          {planTasks.length > 0 && (
            <div className="space-y-3 bg-surface-900/40 border border-violet-800/30 p-3 rounded-lg">
              <div className="flex justify-between items-center">
                <div className="flex items-center gap-2">
                  <Brain size={13} className="text-violet-400" />
                  <span className="font-semibold text-slate-200">Review Proposed Task Graph</span>
                </div>
                <span className="text-[10px] text-slate-500 font-semibold bg-surface-800 px-1.5 py-0.5 rounded border border-surface-700">
                  {planTasks.length} tasks
                </span>
              </div>
              <div className="space-y-1.5 max-h-40 overflow-auto pr-1">
                {planTasks.map((task, idx) => (
                  <div key={task.id} className="flex gap-2 items-start border border-surface-800 bg-surface-900/60 rounded p-2 text-[11px]">
                    <div className="flex items-center justify-center w-4 h-4 rounded-full bg-violet-950/60 border border-violet-800/40 text-[8px] font-bold text-violet-400 shrink-0 mt-0.5">
                      {idx + 1}
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="text-slate-300 truncate font-semibold">{task.title}</div>
                      <div className="text-[9px] text-slate-500 font-mono mt-0.5 flex gap-2">
                        <span className="text-violet-500">{task.agent_role}</span>
                        <span className="text-slate-600">·</span>
                        <span>{task.estimated_effort || "~"}</span>
                        {task.dependencies.length > 0 && (
                          <span className="text-slate-600">deps: {task.dependencies.length}</span>
                        )}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
              <div className="flex gap-2 pt-1">
                <button
                  className="flex-1 flex items-center justify-center gap-1.5 bg-gradient-to-r from-emerald-600 to-emerald-500 hover:from-emerald-500 hover:to-emerald-400 text-white font-semibold text-xs py-2 px-3 rounded-lg shadow-md shadow-emerald-500/20 hover:shadow-emerald-500/30 transition-all active:scale-[0.98] border border-emerald-500/30"
                  onClick={() => void handleStartWorkflow()}
                >
                  <Play size={12} className="shrink-0" /> Approve & Execute Graph
                </button>
                <button
                  className="px-3 py-2 text-xs text-slate-400 hover:text-slate-200 border border-surface-700 hover:border-surface-600 rounded-lg transition-colors"
                  onClick={() => setPlanTasks([])}
                >
                  Cancel
                </button>
              </div>
            </div>
          )}

          {/* ── Active Job Timeline & Console ──────────────────────────────── */}
          {activeJob && (
            <div className="space-y-3">

              {/* Overall Progress */}
              <div className="space-y-1">
                <div className="flex justify-between items-center text-[10px] text-slate-400 font-semibold">
                  <span className="truncate max-w-[160px] font-mono">
                    Job: {activeJob.id.slice(0, 8)}…
                    <span className={`ml-1.5 px-1 rounded text-[8px] font-bold uppercase ${
                      activeJob.status === "completed" ? "text-emerald-400 bg-emerald-950/40" :
                      activeJob.status === "failed" ? "text-rose-400 bg-rose-950/40" :
                      activeJob.status === "cancelled" ? "text-slate-500 bg-surface-800" :
                      "text-blue-400 bg-blue-950/40 animate-pulse"
                    }`}>
                      {activeJob.status}
                    </span>
                  </span>
                  <span>{activeJob.progress}%</span>
                </div>
                <div className="w-full bg-surface-800 h-1.5 rounded-full overflow-hidden">
                  <div
                    className={`h-full rounded-full transition-all duration-700 ${
                      activeJob.status === "completed" ? "bg-emerald-500" :
                      activeJob.status === "failed" ? "bg-rose-500" :
                      "bg-gradient-to-r from-violet-500 to-accent-500"
                    }`}
                    style={{ width: `${activeJob.progress}%` }}
                  />
                </div>
              </div>

              {/* ── Live Plan Card (appears when plan is emitted) ───────────── */}
              {livePlan && (
                <LivePlanCard plan={livePlan} />
              )}

              {/* Task Nodes */}
              <div className="space-y-1">
                <span className="font-semibold text-slate-300 text-[10px] uppercase tracking-wider flex items-center gap-1.5">
                  <Cpu size={10} className="text-slate-500" /> DAG Task Checklist
                </span>
                <div className="space-y-1 max-h-40 overflow-auto pr-1 border border-surface-800 p-1.5 rounded-lg bg-surface-900/30">
                  {activeJob.tasks.map((task) => (
                    <div key={task.id} className="p-2 rounded border border-surface-800/80 bg-surface-900/60 space-y-1.5">
                      <div className="flex justify-between items-start gap-2">
                        <span className="font-semibold text-slate-200 truncate pr-2 max-w-[200px] text-[11px]">{task.title}</span>
                        <div className="flex items-center gap-1.5 shrink-0">
                          {task.structured_data?.model && (
                            <span className="rounded bg-surface-800 border border-surface-700/65 px-1 py-0.5 text-[8px] font-mono text-slate-400 font-semibold uppercase">
                              {task.structured_data.model}
                            </span>
                          )}
                          <span className={`text-[9px] font-mono uppercase px-1.5 py-0.5 rounded font-bold shrink-0 border ${
                            task.status === "completed" ? "bg-emerald-950/40 text-emerald-400 border-emerald-900/30" :
                            task.status === "running" ? "bg-blue-950/40 text-blue-400 border-blue-900/30 animate-pulse" :
                            task.status === "waiting" ? "bg-amber-950/40 text-amber-400 border-amber-900/30 animate-pulse" :
                            task.status === "failed" ? "bg-rose-950/40 text-rose-400 border-rose-900/30" :
                            "bg-surface-800 text-slate-500 border-surface-700"
                          }`}>{task.status}</span>
                        </div>
                      </div>

                      {/* Granular Active Status Line */}
                      {task.status === "running" && (
                        <div className="text-[10px] text-blue-350 font-mono animate-pulse flex items-center gap-1.5 mt-0.5">
                          {(() => {
                            const statusInfo = getCurrentStatusLine(activeJob.logs);
                            if (statusInfo) {
                              return (
                                <>
                                  <span className="shrink-0">{statusInfo.icon}</span>
                                  <span className="truncate">{statusInfo.text}</span>
                                </>
                              );
                            }
                            return <span>⏳ Executing task...</span>;
                          })()}
                        </div>
                      )}

                      {/* File Modification checklist */}
                      {task.status === "running" && livePlan && livePlan.files_to_touch && livePlan.files_to_touch.length > 0 && (
                        <div className="mt-1.5 pl-2.5 border-l-2 border-violet-850 bg-violet-950/5 p-1 rounded space-y-1">
                          <div className="text-[8px] uppercase tracking-wider text-slate-500 font-bold select-none">Planned files checklist:</div>
                          {livePlan.files_to_touch.map((file) => {
                            const isEdited = activeJob.logs.some(l => l.includes(`✓ [EDITED] ${file}`));
                            const isEditing = !isEdited && activeJob.logs.some(l => l.includes(`✍️ [EDITING] ${file}`));
                            return (
                              <div key={file} className="flex items-center gap-1.5 text-[9px] font-mono select-none">
                                {isEdited ? (
                                  <CheckCircle2 size={8} className="text-emerald-400 shrink-0" />
                                ) : isEditing ? (
                                  <Loader2 size={8} className="text-blue-400 animate-spin shrink-0" />
                                ) : (
                                  <Circle size={8} className="text-slate-600 shrink-0" />
                                )}
                                <span className={`${isEdited ? "text-slate-500 line-through decoration-slate-700" : isEditing ? "text-blue-300 font-semibold" : "text-slate-600"} truncate`}>
                                  {file.split(/[/\\]/).pop()}
                                </span>
                              </div>
                            );
                          })}
                        </div>
                      )}

                      {/* Duo loop escalation info */}
                      {task.structured_data?.duo_escalation && (
                        <div className="mt-1 bg-surface-950/20 p-1.5 rounded border border-violet-900/10 text-[9px] flex items-center gap-1.5 font-mono text-violet-300">
                          <Brain size={10} className="text-violet-400 shrink-0 animate-pulse" />
                          <span>Escalated to Duo Loop ({task.structured_data.duo_escalation.rounds} rounds, {task.structured_data.duo_escalation.status})</span>
                        </div>
                      )}

                      {/* Permission Gate Prompt or LLM Failure */}
                      {task.status === "waiting" && task.pending_action && (
                        <div className="mt-2 border-t border-surface-800 pt-2">
                          {(task.pending_action.type as string) === "llm_failure" ? (
                            <div className="rounded-md border border-danger/40 bg-danger/5 p-2 text-[10px] text-danger space-y-2">
                              <div className="flex items-center gap-1.5 font-bold uppercase tracking-wider">
                                <Brain size={12} className="shrink-0" /> LLM Execution Failed
                              </div>
                              <p className="font-mono text-danger/80 leading-relaxed max-h-16 overflow-y-auto">{task.pending_action.details}</p>
                              <div className="flex gap-2 pt-1">
                                <button type="button" onClick={() => void handleRecoverAction(activeJob.id, task.id, "retry")} className="rounded border border-danger/40 px-2 py-1.5 font-semibold hover:bg-danger/10 transition-colors flex-1">Retry Task</button>
                                <button type="button" onClick={() => void handleRecoverAction(activeJob.id, task.id, "switch_to_api")} className="rounded border border-danger/40 px-2 py-1.5 font-semibold hover:bg-danger/10 transition-colors flex-1">Switch to API</button>
                                <button type="button" onClick={() => void handleRecoverAction(activeJob.id, task.id, "cancel")} className="rounded border border-danger/40 px-2 py-1.5 font-semibold hover:bg-danger/10 transition-colors flex-1">Cancel Job</button>
                              </div>
                            </div>
                          ) : (
                            <div className="space-y-2">
                              {/* Permission gate — show what the agent wants to do */}
                              <div className="rounded-md border border-amber-700/50 bg-amber-950/20 p-2 space-y-1.5">
                                <div className="flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-wider text-amber-400">
                                  <ShieldCheck size={11} className="shrink-0" />
                                  Agent Permission Request
                                </div>
                                <p className="text-[10px] text-amber-200/80 font-mono leading-relaxed max-h-20 overflow-y-auto whitespace-pre-wrap">
                                  {task.pending_action.details || "Agent is requesting approval to proceed."}
                                </p>
                                {task.pending_action.command && (
                                  <div className="text-[9px] font-mono text-slate-500 bg-surface-950 px-1.5 py-1 rounded border border-surface-800 truncate">
                                    ref: {task.pending_action.command}
                                  </div>
                                )}
                              </div>
                              <div className="flex gap-2">
                                <button type="button" onClick={() => void handleApproveAction(activeJob.id, task.id)} className="rounded bg-emerald-600 hover:bg-emerald-500 px-3 py-1.5 font-semibold text-white text-xs transition-colors flex-1 flex items-center justify-center gap-1.5">
                                  <ShieldCheck size={11} /> Approve & Apply
                                </button>
                                <button type="button" onClick={() => void handleRejectAction(activeJob.id, task.id)} className="rounded border border-rose-800/50 px-3 py-1.5 font-semibold text-rose-400 hover:bg-rose-950/30 text-xs transition-colors flex-1">Reject</button>
                              </div>
                            </div>
                          )}
                        </div>
                      )}

                      {/* Structured Agent Output */}
                      {task.status === "completed" && renderStructuredOutput(task)}
                    </div>
                  ))}
                </div>
              </div>

              {/* Observability Inspector */}
              {activeJob && (
                <div className="bg-surface-850 p-3 rounded-lg border border-surface-700 space-y-2">
                  <div className="flex justify-between items-center text-[10px] uppercase font-bold text-slate-500 border-b border-surface-700 pb-1.5">
                    <span className="flex items-center gap-1"><Terminal size={9} /> Inspector</span>
                    {activeTask ? (
                      <span className="text-accent-400 animate-pulse flex items-center gap-1">
                        <Loader2 size={9} className="animate-spin" /> {activeTask.agent_role}
                      </span>
                    ) : (
                      <span className="text-slate-600">Idle</span>
                    )}
                  </div>
                  <div className="grid grid-cols-2 gap-x-3 gap-y-1.5 text-[10px]">
                    <div>
                      <span className="text-slate-600 block text-[9px] uppercase font-semibold">Runtime</span>
                      <span className="font-mono text-slate-200">{activeJob.duration.toFixed(1)}s</span>
                    </div>
                    <div>
                      <span className="text-slate-600 block text-[9px] uppercase font-semibold">Tokens</span>
                      <span className="font-mono text-slate-200">{activeJob.token_usage.toLocaleString()}</span>
                    </div>
                    <div>
                      <span className="text-slate-600 block text-[9px] uppercase font-semibold">Files</span>
                      <span className="font-mono text-slate-200">{activeJob.files_modified?.length || 0}</span>
                    </div>
                    <div>
                      <span className="text-slate-600 block text-[9px] uppercase font-semibold">Est. Cost</span>
                      <span className="font-mono text-emerald-400">${((activeJob.token_usage / 1_000_000) * 15.0).toFixed(4)}</span>
                    </div>
                  </div>
                </div>
              )}

              {/* Execution Logs */}
              <div className="space-y-1">
                <span className="font-semibold text-slate-400 text-[10px] uppercase tracking-wider flex items-center gap-1.5">
                  <Terminal size={10} /> Execution Logs
                </span>
                <div className="h-28 overflow-auto font-mono text-[9px] p-2 bg-surface-950 text-slate-400 rounded-lg border border-surface-800 space-y-0.5">
                  {(activeJob.logs || []).filter(l => !l.includes("[PLAN_EMITTED]")).map((log, idx) => (
                    <div
                      key={idx}
                      className={`leading-relaxed ${
                        log.includes("failed") || log.includes("Failed") ? "text-rose-400" :
                        log.includes("passed") || log.includes("approved") ? "text-emerald-400" :
                        log.includes("Phase") || log.includes("Grounding") ? "text-violet-300 font-semibold" :
                        log.includes("Permission") ? "text-amber-300" :
                        "text-slate-400"
                      }`}
                    >
                      {log}
                    </div>
                  ))}
                  {(!activeJob.logs || activeJob.logs.length === 0) && (
                    <div className="text-slate-600">No logs emitted.</div>
                  )}
                  <div ref={logsEndRef} />
                </div>
              </div>

              {/* Cancel */}
              {!["completed", "failed", "cancelled"].includes(activeJob.status) && (
                <button
                  className="w-full flex items-center justify-center gap-1.5 bg-rose-950/30 hover:bg-rose-900/40 text-rose-300 border border-rose-900/30 hover:border-rose-800/50 py-2 rounded-lg text-xs font-semibold transition-all"
                  onClick={() => void handleCancelJob(activeJob.id)}
                >
                  <Square size={12} /> Terminate Agent Execution
                </button>
              )}

              {["completed", "failed", "cancelled"].includes(activeJob.status) && (
                <button
                  className="w-full py-2 text-xs text-slate-400 hover:text-slate-200 border border-surface-700 hover:border-surface-600 rounded-lg transition-colors font-semibold"
                  onClick={() => { setActiveJob(null); setPlanTasks([]); }}
                >
                  Clear & Start New Request
                </button>
              )}
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
