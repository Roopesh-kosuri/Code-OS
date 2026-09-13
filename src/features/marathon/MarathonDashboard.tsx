// Marathon Autopilot — Live Dashboard with Kanban board, budget gauges & live log
import { useEffect, useRef } from "react";
import {
  Rocket, Pause, Play, XCircle, CheckCircle2, Clock,
  Zap, DollarSign, AlertTriangle, GitCommit, Loader2, Plus
} from "lucide-react";
import { useMarathonStore } from "./marathonStore";
import { MarathonModal } from "./MarathonModal";
import { useWorkspaceStore } from "../../stores/workspaceStore";
import type { MarathonSubTask, SubTaskStatus } from "./types";

// ── Complexity badge ──────────────────────────────────────────────────────────
const COMPLEXITY_COLOR: Record<string, string> = {
  trivial: "text-slate-400 border-slate-600",
  low: "text-emerald-400 border-emerald-600/50",
  medium: "text-amber-400 border-amber-600/50",
  high: "text-orange-400 border-orange-600/50",
  epic: "text-red-400 border-red-600/50",
};

function ComplexityBadge({ c }: { c: string }) {
  return (
    <span className={`text-[10px] border rounded px-1 py-0.5 font-mono uppercase ${COMPLEXITY_COLOR[c] ?? COMPLEXITY_COLOR.medium}`}>
      {c}
    </span>
  );
}

// ── Status icon ───────────────────────────────────────────────────────────────
function StatusIcon({ status }: { status: SubTaskStatus }) {
  if (status === "completed") return <CheckCircle2 size={14} className="text-emerald-400 flex-shrink-0" />;
  if (status === "blocked") return <AlertTriangle size={14} className="text-red-400 flex-shrink-0" />;
  if (status === "in_progress") return <Loader2 size={14} className="text-violet-400 animate-spin flex-shrink-0" />;
  if (status === "skipped") return <XCircle size={14} className="text-slate-500 flex-shrink-0" />;
  return <div className="w-3.5 h-3.5 rounded-full border border-slate-600 flex-shrink-0" />;
}

// ── Task card ─────────────────────────────────────────────────────────────────
function TaskCard({ task }: { task: MarathonSubTask }) {
  return (
    <div
      data-testid={`task-card-${task.id}`}
      className="group bg-[#12151f] border border-slate-700/50 rounded-xl p-3 space-y-1.5 hover:border-violet-500/40 hover:shadow-md transition-all"
    >
      <div className="flex items-start gap-2">
        <StatusIcon status={task.status} />
        <span className="text-xs font-medium text-slate-200 leading-snug flex-1">{task.title}</span>
      </div>
      <div className="flex items-center gap-2 flex-wrap">
        <ComplexityBadge c={task.complexity} />
        {task.git_commit_hash && (
          <span className="flex items-center gap-1 text-[10px] text-slate-500 font-mono">
            <GitCommit size={10} />
            {task.git_commit_hash.slice(0, 7)}
          </span>
        )}
        {task.retry_count > 0 && (
          <span className="text-[10px] text-amber-400 font-mono">retry×{task.retry_count}</span>
        )}
      </div>
      {task.error_log.length > 0 && (
        <p className="text-[10px] text-red-400 font-mono truncate" title={task.error_log[task.error_log.length - 1]}>
          {task.error_log[task.error_log.length - 1]}
        </p>
      )}
    </div>
  );
}

// ── Kanban column ─────────────────────────────────────────────────────────────
function KanbanColumn({ title, tasks, accent }: { title: string; tasks: MarathonSubTask[]; accent: string }) {
  return (
    <div className="flex flex-col min-w-[200px] flex-1">
      <div className={`flex items-center justify-between mb-3 pb-2 border-b ${accent}`}>
        <span className="text-xs font-bold text-slate-300 uppercase tracking-widest">{title}</span>
        <span className="text-xs text-slate-500 font-mono">{tasks.length}</span>
      </div>
      <div className="flex flex-col gap-2 overflow-y-auto flex-1 pr-1" style={{ maxHeight: "40vh" }}>
        {tasks.map((t) => <TaskCard key={t.id} task={t} />)}
        {tasks.length === 0 && (
          <div className="text-center text-xs text-slate-600 py-6 italic">Empty</div>
        )}
      </div>
    </div>
  );
}

// ── Radial gauge ──────────────────────────────────────────────────────────────
function RadialGauge({ value, max, label, color, icon }: {
  value: number; max: number; label: string; color: string; icon: React.ReactNode;
}) {
  const pct = Math.min(1, max > 0 ? value / max : 0);
  const r = 28;
  const circ = 2 * Math.PI * r;
  const dash = circ * (1 - pct);
  const isWarning = pct >= 0.9;

  return (
    <div className="flex flex-col items-center gap-1.5">
      <div className="relative w-16 h-16">
        <svg viewBox="0 0 72 72" className="w-full h-full -rotate-90">
          <circle cx="36" cy="36" r={r} fill="none" stroke="#1e2130" strokeWidth="7" />
          <circle
            cx="36" cy="36" r={r} fill="none"
            stroke={isWarning ? "#ef4444" : color}
            strokeWidth="7"
            strokeDasharray={circ}
            strokeDashoffset={dash}
            strokeLinecap="round"
            style={{ transition: "stroke-dashoffset 0.5s ease" }}
          />
        </svg>
        <div className="absolute inset-0 flex items-center justify-center">
          <span className={`text-[10px] font-bold ${isWarning ? "text-red-400" : "text-slate-300"}`}>
            {Math.round(pct * 100)}%
          </span>
        </div>
      </div>
      <div className="flex items-center gap-1 text-[11px] text-slate-400">
        {icon}
        {label}
      </div>
    </div>
  );
}

// ── Main Dashboard ────────────────────────────────────────────────────────────
export function MarathonDashboard() {
  const marathon = useMarathonStore((s) => s.activeMarathon);
  const liveLog = useMarathonStore((s) => s.liveLog);
  const showModal = useMarathonStore((s) => s.showModal);
  const isLoading = useMarathonStore((s) => s.isLoading);
  const { setShowModal, pauseMarathon, resumeMarathon, abortMarathon } = useMarathonStore();
  const workspace = useWorkspaceStore((s) => s.currentWorkspace?.path ?? ".");
  const logRef = useRef<HTMLDivElement>(null);

  // Auto-scroll live log
  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [liveLog]);

  const tasks = marathon?.tasks ?? [];
  const todo = tasks.filter((t) => t.status === "todo");
  const inProgress = tasks.filter((t) => t.status === "in_progress");
  const blocked = tasks.filter((t) => t.status === "blocked");
  const done = tasks.filter((t) => t.status === "completed");

  const isRunning = marathon?.status === "running";
  const isPaused = marathon?.status === "paused";
  const isCompleted = marathon?.status === "completed";
  const isAborted = marathon?.status === "aborted";

  return (
    <div
      id="marathon-dashboard"
      data-testid="marathon-dashboard"
      className="flex flex-col h-full bg-[#0a0c14] text-slate-200 overflow-hidden"
    >
      {/* Header */}
      <div className="flex items-center gap-3 px-5 py-3.5 border-b border-violet-500/20 bg-gradient-to-r from-violet-950/40 to-indigo-950/40 flex-shrink-0">
        <div className="w-8 h-8 rounded-xl bg-violet-500/20 border border-violet-500/30 flex items-center justify-center">
          <Rocket size={16} className={`text-violet-400 ${isRunning ? "animate-pulse" : ""}`} />
        </div>
        <div className="flex-1 min-w-0">
          <h2 className="text-sm font-bold text-slate-100 truncate">
            {marathon ? "Marathon Autopilot" : "Marathon Autopilot"}
          </h2>
          {marathon && (
            <p className="text-[11px] text-slate-400 truncate" title={marathon.goal}>{marathon.goal}</p>
          )}
        </div>

        {/* Controls */}
        <div className="flex items-center gap-2 flex-shrink-0">
          {!marathon && (
            <button
              id="marathon-open-modal-btn"
              onClick={() => setShowModal(true)}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-violet-600 hover:bg-violet-500 text-white text-xs font-semibold transition-all shadow-md shadow-violet-500/20 active:scale-95"
            >
              <Plus size={13} />
              New Marathon
            </button>
          )}
          {isRunning && (
            <button
              id="marathon-pause-btn"
              onClick={() => void pauseMarathon(workspace)}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-amber-500/20 hover:bg-amber-500/30 border border-amber-500/40 text-amber-300 text-xs font-semibold transition-all"
            >
              <Pause size={13} />
              Pause
            </button>
          )}
          {isPaused && (
            <button
              id="marathon-resume-btn"
              onClick={() => void resumeMarathon(workspace)}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-emerald-500/20 hover:bg-emerald-500/30 border border-emerald-500/40 text-emerald-300 text-xs font-semibold transition-all"
            >
              <Play size={13} />
              Resume
            </button>
          )}
          {(isRunning || isPaused) && (
            <button
              id="marathon-abort-btn"
              onClick={() => void abortMarathon(workspace)}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-red-500/20 hover:bg-red-500/30 border border-red-500/40 text-red-300 text-xs font-semibold transition-all"
            >
              <XCircle size={13} />
              Abort
            </button>
          )}
          {(isCompleted || isAborted) && (
            <button
              id="marathon-new-btn"
              onClick={() => setShowModal(true)}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-violet-600/20 hover:bg-violet-600/30 border border-violet-500/40 text-violet-300 text-xs font-semibold transition-all"
            >
              <Plus size={13} />
              New Marathon
            </button>
          )}
        </div>
      </div>

      {!marathon ? (
        /* Empty state */
        <div className="flex flex-col items-center justify-center flex-1 gap-4 p-8">
          <div className="w-16 h-16 rounded-2xl bg-violet-500/10 border border-violet-500/20 flex items-center justify-center">
            <Rocket size={28} className="text-violet-400/60" />
          </div>
          <p className="text-sm text-slate-400 text-center max-w-xs">
            Start a Marathon to autonomously execute large multi-day projects with the AI agent team.
          </p>
          <button
            id="marathon-empty-start-btn"
            onClick={() => setShowModal(true)}
            className="px-5 py-2.5 rounded-xl bg-violet-600 hover:bg-violet-500 text-white font-semibold text-sm transition-all shadow-lg shadow-violet-500/25 active:scale-95"
          >
            Start Marathon
          </button>
        </div>
      ) : (
        <div className="flex flex-col flex-1 min-h-0 overflow-hidden">
          {/* Progress + budget row */}
          <div className="flex items-center gap-6 px-5 py-3 border-b border-slate-800/60 flex-shrink-0">
            {/* Progress bar */}
            <div className="flex-1">
              <div className="flex items-center justify-between mb-1">
                <span className="text-xs text-slate-400 font-semibold">
                  {marathon.progress_completed}/{marathon.progress_total} tasks
                </span>
                <span
                  className={`text-xs font-bold px-2 py-0.5 rounded-full ${
                    isRunning ? "bg-violet-500/20 text-violet-300" :
                    isPaused ? "bg-amber-500/20 text-amber-300" :
                    isCompleted ? "bg-emerald-500/20 text-emerald-300" :
                    "bg-red-500/20 text-red-300"
                  }`}
                >
                  {marathon.status.toUpperCase()}
                </span>
              </div>
              <div
                data-testid="marathon-progress-bar"
                className="w-full h-2 bg-slate-800 rounded-full overflow-hidden"
              >
                <div
                  className="h-full bg-gradient-to-r from-violet-500 to-indigo-500 rounded-full transition-all duration-700"
                  style={{
                    width: `${marathon.progress_total > 0 ? (marathon.progress_completed / marathon.progress_total) * 100 : 0}%`,
                  }}
                />
              </div>
            </div>

            {/* Budget gauges */}
            <div className="flex items-center gap-4 flex-shrink-0">
              <RadialGauge
                value={marathon.usage.tokens_used}
                max={marathon.budget.token_budget}
                label="Tokens"
                color="#8b5cf6"
                icon={<Zap size={10} />}
              />
              <RadialGauge
                value={marathon.usage.elapsed_seconds}
                max={marathon.budget.time_budget_seconds}
                label="Time"
                color="#f59e0b"
                icon={<Clock size={10} />}
              />
              <RadialGauge
                value={marathon.usage.cost_usd}
                max={marathon.budget.cost_budget_usd}
                label="Cost"
                color="#10b981"
                icon={<DollarSign size={10} />}
              />
            </div>
          </div>

          {/* Kanban board */}
          <div className="flex gap-3 p-4 flex-1 min-h-0 overflow-x-auto">
            <KanbanColumn title="To Do" tasks={todo} accent="border-slate-700" />
            <KanbanColumn title="In Progress" tasks={inProgress} accent="border-violet-500/50" />
            <KanbanColumn title="Blocked" tasks={blocked} accent="border-red-500/50" />
            <KanbanColumn title="Done" tasks={done} accent="border-emerald-500/50" />
          </div>

          {/* Handoff report */}
          {marathon.handoff_report && (
            <div className="mx-4 mb-3 p-3 rounded-xl bg-amber-900/20 border border-amber-500/30 text-amber-200 text-xs font-mono whitespace-pre-wrap flex-shrink-0 max-h-32 overflow-y-auto">
              {marathon.handoff_report}
            </div>
          )}

          {/* Live log */}
          <div
            ref={logRef}
            data-testid="marathon-live-log"
            className="mx-4 mb-4 h-28 rounded-xl bg-[#080a0f] border border-slate-800 p-3 overflow-y-auto font-mono text-[10px] text-slate-400 flex-shrink-0"
          >
            {liveLog.length === 0 ? (
              <span className="text-slate-600">Waiting for events…</span>
            ) : (
              liveLog.map((line, i) => (
                <div key={i} className="leading-relaxed">{line}</div>
              ))
            )}
          </div>
        </div>
      )}

      {/* Modal */}
      {showModal && <MarathonModal />}
    </div>
  );
}
