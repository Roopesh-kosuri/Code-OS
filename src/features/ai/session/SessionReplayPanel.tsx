import React, { useEffect, useState } from "react";
import {
  History,
  GitFork,
  Download,
  FileText,
  Code2,
  Terminal,
  Brain,
  Clock,
  DollarSign,
  CheckCircle,
  AlertCircle,
  RefreshCw,
  X,
  ChevronRight,
  Layers,
  FileCode,
  ArrowRight,
  Play,
  Maximize2,
  ArrowLeft,
  ExternalLink,
} from "lucide-react";
import { useSessionStore, TimelineStep, SessionItem } from "./sessionStore";
import { useWorkspaceStore } from "../../../stores/workspaceStore";

export interface SessionReplayPanelProps {
  compact?: boolean;
  onOpenFullView?: () => void;
  onBackToMain?: () => void;
}

export function SessionReplayPanel({
  compact = false,
  onOpenFullView,
  onBackToMain,
}: SessionReplayPanelProps = {}) {
  const currentWorkspace = useWorkspaceStore((s) => s.currentWorkspace);

  const sessions = useSessionStore((s) => s.sessions);
  const activeSessionId = useSessionStore((s) => s.activeSessionId);
  const activeSession = useSessionStore((s) => s.activeSession);
  const timeline = useSessionStore((s) => s.timeline);
  const activeStepId = useSessionStore((s) => s.activeStepId);
  const activeSnapshot = useSessionStore((s) => s.activeSnapshot);
  const isLoadingSessions = useSessionStore((s) => s.isLoadingSessions);
  const isLoadingTimeline = useSessionStore((s) => s.isLoadingTimeline);
  const isForkModalOpen = useSessionStore((s) => s.isForkModalOpen);
  const forkTargetStepId = useSessionStore((s) => s.forkTargetStepId);
  const isForking = useSessionStore((s) => s.isForking);

  const fetchSessions = useSessionStore((s) => s.fetchSessions);
  const selectSession = useSessionStore((s) => s.selectSession);
  const selectStep = useSessionStore((s) => s.selectStep);
  const openForkModal = useSessionStore((s) => s.openForkModal);
  const closeForkModal = useSessionStore((s) => s.closeForkModal);
  const forkSession = useSessionStore((s) => s.forkSession);
  const exportSession = useSessionStore((s) => s.exportSession);

  const [forkPrompt, setForkPrompt] = useState("");
  const [showSessionDrawer, setShowSessionDrawer] = useState(false);
  const [activeTab, setActiveTab] = useState<"detail" | "manifest">("detail");
  const [compactView, setCompactView] = useState<"list" | "timeline">("list");

  useEffect(() => {
    void fetchSessions(currentWorkspace?.path);
  }, [currentWorkspace?.path, fetchSessions]);

  const currentStep: TimelineStep | undefined = timeline.find((s) => s.step_id === activeStepId) || timeline[0];

  const handleForkSubmit = async () => {
    if (!forkPrompt.trim() || !activeSessionId || !forkTargetStepId) return;
    try {
      await forkSession(activeSessionId, forkTargetStepId, forkPrompt.trim());
      setForkPrompt("");
    } catch {
      // Error handled by store
    }
  };

  const getRoleBadgeClass = (role: string) => {
    const r = (role || "").toLowerCase();
    if (r.includes("architect")) return "bg-purple-500/15 text-purple-300 border-purple-500/30";
    if (r.includes("coder")) return "bg-cyan-500/15 text-cyan-300 border-cyan-500/30";
    if (r.includes("tester")) return "bg-emerald-500/15 text-emerald-300 border-emerald-500/30";
    if (r.includes("reviewer")) return "bg-amber-500/15 text-amber-300 border-amber-500/30";
    if (r.includes("devops")) return "bg-sky-500/15 text-sky-300 border-sky-500/30";
    return "bg-primary/15 text-primary border-primary/30";
  };

  const getStatusBadge = (status: string) => {
    const s = (status || "").toLowerCase();
    if (s === "completed") {
      return (
        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold bg-emerald-500/15 text-emerald-300 border border-emerald-500/30">
          <CheckCircle size={10} /> Completed
        </span>
      );
    }
    if (s === "running") {
      return (
        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold bg-cyan-500/15 text-cyan-300 border border-cyan-500/30 animate-pulse">
          <RefreshCw size={10} className="animate-spin" /> Running
        </span>
      );
    }
    if (s === "failed") {
      return (
        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold bg-rose-500/15 text-rose-300 border border-rose-500/30">
          <AlertCircle size={10} /> Failed
        </span>
      );
    }
    return (
      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold bg-white/10 text-white/70 border border-white/20">
        {status}
      </span>
    );
  };

  const renderForkModal = () => {
    if (!isForkModalOpen) return null;
    return (
      <div
        id="fork-session-modal"
        className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-md p-6"
      >
        <div className="w-full max-w-lg bg-[#141624] rounded-2xl border border-white/20 p-6 space-y-4 shadow-2xl animate-in zoom-in-95 duration-150">
          <div className="flex items-center justify-between pb-3 border-b border-white/10">
            <div className="flex items-center gap-2">
              <GitFork size={18} className="text-amber-400" />
              <h3 className="font-bold text-sm text-white">Fork Session Timeline</h3>
            </div>
            <button
              onClick={closeForkModal}
              className="p-1 text-white/50 hover:text-white rounded transition-colors cursor-pointer"
            >
              <X size={16} />
            </button>
          </div>

          <div className="space-y-1">
            <div className="text-xs font-semibold text-white/80">
              Forking from step {currentStep?.step_num || 1} of {timeline.length}
            </div>
            <p className="text-[11px] text-white/50">
              Clones all previous completed steps and manifest history up to this step. Enter a new directive to guide the branched timeline.
            </p>
          </div>

          <div className="space-y-1.5">
            <label className="text-xs font-bold text-white/80 block">
              New Directive / Instruction
            </label>
            <textarea
              id="fork-prompt-input"
              rows={4}
              value={forkPrompt}
              onChange={(e) => setForkPrompt(e.target.value)}
              placeholder="What if I had said X instead? e.g. 'Use async SQLite instead of raw sqlite3 and add benchmark script'"
              className="w-full bg-black/40 border border-white/15 rounded-xl p-3 text-xs text-white placeholder:text-white/30 focus:border-amber-400 focus:outline-none resize-none font-sans"
            />
          </div>

          <div className="pt-3 border-t border-white/10 flex items-center justify-end gap-2">
            <button
              type="button"
              onClick={closeForkModal}
              className="px-4 py-2 rounded-xl bg-white/5 hover:bg-white/10 text-white/70 text-xs font-bold transition-all cursor-pointer"
            >
              Cancel
            </button>
            <button
              type="button"
              id="btn-confirm-fork"
              disabled={!forkPrompt.trim() || isForking}
              onClick={handleForkSubmit}
              className="flex items-center gap-2 px-4 py-2 rounded-xl bg-amber-500 hover:bg-amber-400 text-black font-bold text-xs transition-all cursor-pointer shadow-lg disabled:opacity-40"
            >
              {isForking ? <RefreshCw size={13} className="animate-spin" /> : <Play size={13} />}
              <span>Fork &amp; Execute</span>
            </button>
          </div>
        </div>
      </div>
    );
  };

  /* ──────────────────────────────────────────────────────────────────────────
     COMPACT SIDEBAR MODE
     ────────────────────────────────────────────────────────────────────────── */
  if (compact) {
    return (
      <div
        id="session-replay-sidebar-panel"
        className="flex flex-col h-full bg-[#0d0f17] text-white select-none font-sans overflow-hidden border-r border-white/5"
      >
        {/* Sidebar Header */}
        <div className="px-3 py-2.5 border-b border-white/10 flex justify-between items-center bg-[#12141f] shrink-0">
          <div className="flex items-center gap-2 min-w-0">
            <History size={15} className="text-primary shrink-0" />
            <h2 className="font-bold text-white uppercase tracking-wider text-[11px] truncate">
              Sessions
            </h2>
            <span className="text-[10px] font-mono px-1.5 py-0.5 rounded-full bg-white/10 text-white/70">
              {sessions.length}
            </span>
          </div>
          <div className="flex items-center gap-1">
            <button
              id="btn-sidebar-refresh-sessions"
              onClick={() => void fetchSessions(currentWorkspace?.path)}
              className="p-1 text-white/60 hover:text-white hover:bg-white/5 rounded transition-colors cursor-pointer"
              title="Refresh Sessions"
            >
              <RefreshCw size={13} className={isLoadingSessions ? "animate-spin" : ""} />
            </button>
            {onOpenFullView && (
              <button
                id="btn-sidebar-expand-sessions"
                onClick={onOpenFullView}
                className="p-1 text-white/60 hover:text-white hover:bg-white/5 rounded transition-colors cursor-pointer"
                title="Open Full Replay Screen"
              >
                <Maximize2 size={13} />
              </button>
            )}
          </div>
        </div>

        {/* View Switcher if a session is selected */}
        {activeSession && (
          <div className="px-2 pt-2 pb-1.5 flex items-center gap-1 bg-black/30 border-b border-white/5 text-[11px] shrink-0">
            <button
              onClick={() => setCompactView("list")}
              className={`flex-1 py-1 text-center rounded-lg transition-all cursor-pointer font-bold ${
                compactView === "list"
                  ? "bg-primary/20 text-primary border border-primary/30"
                  : "text-white/60 hover:text-white"
              }`}
            >
              Past Jobs ({sessions.length})
            </button>
            <button
              onClick={() => setCompactView("timeline")}
              className={`flex-1 py-1 text-center rounded-lg transition-all cursor-pointer font-bold truncate px-1 ${
                compactView === "timeline"
                  ? "bg-primary/20 text-primary border border-primary/30"
                  : "text-white/60 hover:text-white"
              }`}
            >
              Timeline ({timeline.length})
            </button>
          </div>
        )}

        {/* Content: List of Sessions or Timeline Scrubber */}
        {compactView === "list" ? (
          <div className="flex-1 min-h-0 overflow-y-auto p-2 space-y-2 custom-scrollbar">
            {isLoadingSessions ? (
              <div className="p-8 flex flex-col items-center justify-center text-xs text-white/40 gap-2">
                <RefreshCw size={16} className="animate-spin text-primary" />
                <span>Loading sessions...</span>
              </div>
            ) : sessions.length === 0 ? (
              <div className="p-8 text-center text-xs text-white/40 space-y-1">
                <History size={20} className="mx-auto text-white/20 mb-2" />
                <p>No past sessions recorded.</p>
              </div>
            ) : (
              sessions.map((s) => {
                const isSelected = s.job_id === activeSessionId;
                return (
                  <div
                    key={s.job_id}
                    onClick={() => {
                      void selectSession(s.job_id);
                      setCompactView("timeline");
                    }}
                    onDoubleClick={onOpenFullView}
                    className={`p-2.5 rounded-xl border text-xs transition-all cursor-pointer space-y-1.5 group ${
                      isSelected
                        ? "bg-primary/15 border-primary/50 shadow-sm ring-1 ring-primary/30"
                        : "bg-white/[0.02] border-white/5 hover:bg-white/5 hover:border-white/15"
                    }`}
                  >
                    <div className="flex items-start justify-between gap-1.5">
                      <span className="font-bold text-white leading-tight line-clamp-2 group-hover:text-primary transition-colors">
                        {s.title}
                      </span>
                      {getStatusBadge(s.status)}
                    </div>
                    <div className="flex items-center justify-between text-[10px] text-white/50 font-mono pt-1 border-t border-white/5">
                      <span>{s.step_count} steps</span>
                      <span>{s.duration}s</span>
                      <span className="text-cyan-300 font-bold">${s.cost_usd.toFixed(4)}</span>
                    </div>
                  </div>
                );
              })
            )}
          </div>
        ) : (
          /* Timeline view in compact mode */
          <div className="flex-1 min-h-0 flex flex-col overflow-hidden">
            <div className="p-2 border-b border-white/10 bg-black/30 flex items-center justify-between text-[11px] shrink-0">
              <span className="font-bold text-white truncate max-w-[160px]" title={activeSession?.title}>
                {activeSession?.title}
              </span>
              {onOpenFullView && (
                <button
                  onClick={onOpenFullView}
                  className="text-[10px] text-cyan-400 hover:text-cyan-300 flex items-center gap-1 font-semibold cursor-pointer"
                  title="Open full 2-pane view"
                >
                  <span>Full View</span>
                  <Maximize2 size={10} />
                </button>
              )}
            </div>

            <div className="flex-1 overflow-y-auto p-2 space-y-2 custom-scrollbar">
              {isLoadingTimeline ? (
                <div className="p-8 flex flex-col items-center justify-center text-xs text-white/40 gap-2">
                  <RefreshCw size={16} className="animate-spin text-primary" />
                  <span>Loading timeline...</span>
                </div>
              ) : timeline.length === 0 ? (
                <div className="p-6 text-center text-xs text-white/40">
                  No steps recorded for this session.
                </div>
              ) : (
                timeline.map((step, idx) => {
                  const isSelected = step.step_id === activeStepId;
                  return (
                    <div
                      key={step.step_id || idx}
                      onClick={() => void selectStep(step.step_id)}
                      className={`p-2 rounded-lg border text-xs transition-all cursor-pointer space-y-1.5 ${
                        isSelected
                          ? "bg-primary/15 border-primary/40 shadow-sm"
                          : "bg-white/[0.02] border-white/5 hover:bg-white/5"
                      }`}
                    >
                      <div className="flex items-center justify-between gap-1">
                        <div className="flex items-center gap-1">
                          <span className="text-[9px] font-mono font-bold px-1 rounded bg-white/10 text-white/70">
                            #{step.step_num || idx + 1}
                          </span>
                          <span className={`text-[8.5px] font-bold uppercase px-1 rounded border ${getRoleBadgeClass(step.agent_role)}`}>
                            {step.agent_role}
                          </span>
                        </div>
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            openForkModal(step.step_id);
                          }}
                          className="px-1.5 py-0.5 rounded text-[9px] font-bold bg-amber-500/15 text-amber-300 border border-amber-500/30 hover:bg-amber-500/25 cursor-pointer"
                          title="Rewind & Fork"
                        >
                          Rewind
                        </button>
                      </div>
                      <div className="text-[10px] font-mono text-white/80 truncate">
                        {step.tool_name || step.action_type}
                      </div>
                    </div>
                  );
                })
              )}
            </div>

            {/* Compact Bottom Actions */}
            <div className="p-2 border-t border-white/10 bg-[#12141f]/90 flex items-center justify-between gap-2 shrink-0">
              <button
                id="btn-sidebar-fork"
                disabled={!activeSessionId || !currentStep}
                onClick={() => openForkModal(currentStep?.step_id)}
                className="flex-1 flex items-center justify-center gap-1 py-1.5 rounded-lg bg-amber-500/20 hover:bg-amber-500/30 text-amber-300 border border-amber-500/40 text-[10px] font-bold transition-all disabled:opacity-40 cursor-pointer"
              >
                <GitFork size={11} />
                <span>Fork</span>
              </button>
              <button
                id="btn-sidebar-export-md"
                disabled={!activeSessionId}
                onClick={() => void exportSession(activeSessionId!, "markdown")}
                className="p-1.5 rounded-lg bg-white/5 hover:bg-white/10 text-white/80 text-[10px] border border-white/10 cursor-pointer"
                title="Export Markdown"
              >
                <FileText size={12} />
              </button>
              <button
                id="btn-sidebar-export-json"
                disabled={!activeSessionId}
                onClick={() => void exportSession(activeSessionId!, "json")}
                className="p-1.5 rounded-lg bg-white/5 hover:bg-white/10 text-white/80 text-[10px] border border-white/10 cursor-pointer"
                title="Export JSON"
              >
                <Download size={12} />
              </button>
            </div>
          </div>
        )}

        {renderForkModal()}
      </div>
    );
  }

  /* ──────────────────────────────────────────────────────────────────────────
     FULL REPLAY VIEW (2 Columns)
     ────────────────────────────────────────────────────────────────────────── */
  return (
    <div id="session-replay-panel" className="flex-1 min-h-0 overflow-hidden flex flex-col h-full bg-[#0d0f17] text-white font-sans">
      {/* ── Top Bar: Active Session Info & Controls ─────────────────────────── */}
      <div className="h-14 border-b border-white/10 bg-[#12141f]/80 backdrop-blur-md px-6 flex items-center justify-between gap-4 flex-shrink-0">
        <div className="flex items-center gap-3 min-w-0">
          {onBackToMain && (
            <button
              id="btn-back-to-editor"
              onClick={onBackToMain}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-white/5 hover:bg-white/10 border border-white/10 text-xs font-bold transition-all cursor-pointer text-white/80 hover:text-white shrink-0 mr-1"
              title="Return to Main Editor"
            >
              <ArrowLeft size={13} />
              <span>Back to Editor</span>
            </button>
          )}

          <button
            id="btn-toggle-session-drawer"
            onClick={() => setShowSessionDrawer((v) => !v)}
            className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-white/5 hover:bg-white/10 border border-white/10 text-xs font-bold transition-all cursor-pointer text-white/90 hover:text-white shrink-0"
            title="Switch Session"
          >
            <History size={14} className="text-primary" />
            <span>Sessions ({sessions.length})</span>
            <ChevronRight size={13} className={`transition-transform ${showSessionDrawer ? "rotate-90" : ""}`} />
          </button>

          <div className="h-4 w-[1px] bg-white/10" />

          {activeSession ? (
            <div className="flex items-center gap-3 min-w-0 truncate">
              <span className="font-bold text-sm text-white truncate max-w-md" title={activeSession.title}>
                {activeSession.title}
              </span>
              {getStatusBadge(activeSession.status)}
              <span className="text-[11px] text-white/50 font-mono flex items-center gap-1">
                <Clock size={11} /> {activeSession.duration}s
              </span>
              <span className="text-[11px] text-cyan-300 font-mono font-bold flex items-center gap-0.5 bg-cyan-500/10 px-2 py-0.5 rounded border border-cyan-500/20">
                <DollarSign size={10} /> {activeSession.cost_usd.toFixed(4)}
              </span>
              <span className="text-[11px] text-white/50 font-mono bg-white/5 px-2 py-0.5 rounded">
                {timeline.length || activeSession.step_count} steps
              </span>
            </div>
          ) : (
            <span className="text-xs text-white/50">No session selected</span>
          )}
        </div>

        <div className="flex items-center gap-2">
          <button
            id="btn-refresh-sessions"
            onClick={() => void fetchSessions(currentWorkspace?.path)}
            className="p-2 rounded-lg bg-white/5 hover:bg-white/10 text-white/70 hover:text-white transition-colors cursor-pointer border border-white/5"
            title="Refresh Sessions"
          >
            <RefreshCw size={13} className={isLoadingSessions ? "animate-spin" : ""} />
          </button>
        </div>
      </div>

      {/* ── Main Workspace: Scrubber (Left) + Detail Inspector (Right) ──────── */}
      <div className="flex-1 min-h-0 flex relative overflow-hidden">
        {/* ── Optional Slide-over Sessions Drawer ───────────────────────────── */}
        {showSessionDrawer && (
          <div
            id="sessions-list-drawer"
            className="absolute left-0 top-0 bottom-0 w-80 bg-[#141624] border-r border-white/10 z-30 shadow-2xl flex flex-col animate-in slide-in-from-left duration-200"
          >
            <div className="p-3 border-b border-white/10 flex items-center justify-between">
              <span className="text-xs font-bold uppercase tracking-wider text-white/60">Select Past Session</span>
              <button
                onClick={() => setShowSessionDrawer(false)}
                className="p-1 rounded text-white/50 hover:text-white transition-colors cursor-pointer"
              >
                <X size={14} />
              </button>
            </div>
            <div className="flex-1 overflow-y-auto p-2 space-y-1.5 custom-scrollbar">
              {sessions.map((s) => (
                <div
                  key={s.job_id}
                  onClick={() => {
                    void selectSession(s.job_id);
                    setShowSessionDrawer(false);
                  }}
                  className={`p-3 rounded-xl border text-xs transition-all cursor-pointer space-y-1.5 ${
                    s.job_id === activeSessionId
                      ? "bg-primary/10 border-primary/40 shadow-sm"
                      : "bg-white/[0.02] border-white/5 hover:bg-white/5 hover:border-white/15"
                  }`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-bold text-white truncate max-w-[180px]">{s.title}</span>
                    {getStatusBadge(s.status)}
                  </div>
                  <div className="flex items-center justify-between text-[10px] text-white/50 font-mono">
                    <span>{s.step_count} steps</span>
                    <span>{s.duration}s</span>
                    <span className="text-cyan-300 font-bold">${s.cost_usd.toFixed(4)}</span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* ── Left Column: Timeline Scrubber (300px) ────────────────────────── */}
        <div id="timeline-scrubber" className="w-[300px] border-r border-white/10 bg-[#0f111a] flex flex-col flex-shrink-0 h-full select-none">
          <div className="p-3 border-b border-white/10 flex items-center justify-between bg-black/20">
            <div className="flex items-center gap-1.5 text-xs font-bold text-white/80">
              <Clock size={13} className="text-primary" />
              <span>Timeline Scrubber</span>
            </div>
            <span className="text-[10px] text-white/40 font-mono">
              {timeline.length} {timeline.length === 1 ? "step" : "steps"}
            </span>
          </div>

          {isLoadingTimeline ? (
            <div className="flex-1 flex flex-col items-center justify-center text-xs text-white/40 gap-2">
              <RefreshCw size={18} className="animate-spin text-primary" />
              <span>Loading timeline...</span>
            </div>
          ) : timeline.length === 0 ? (
            <div className="flex-1 p-6 flex flex-col items-center justify-center text-center text-xs text-white/40 gap-2">
              <History size={24} className="text-white/20" />
              <span>No execution steps recorded for this session.</span>
            </div>
          ) : (
            <div className="flex-1 overflow-y-auto p-2 space-y-2 custom-scrollbar">
              {timeline.map((step, idx) => {
                const isSelected = step.step_id === activeStepId || (!activeStepId && idx === 0);
                const roleBadge = getRoleBadgeClass(step.agent_role);

                return (
                  <div
                    key={step.step_id || idx}
                    onClick={() => void selectStep(step.step_id)}
                    className={`p-2.5 rounded-xl border transition-all cursor-pointer relative group text-xs ${
                      isSelected
                        ? "bg-primary/15 border-primary/50 shadow-md ring-1 ring-primary/30"
                        : "bg-white/[0.02] border-white/5 hover:bg-white/5 hover:border-white/15"
                    }`}
                  >
                    {/* Header: Step Number, Role & Timestamp */}
                    <div className="flex items-center justify-between gap-1.5 mb-1.5">
                      <div className="flex items-center gap-1.5">
                        <span className="text-[10px] font-mono font-bold px-1.5 py-0.5 rounded bg-white/10 text-white/70">
                          #{step.step_num || idx + 1}
                        </span>
                        <span className={`text-[9px] font-bold uppercase px-1.5 py-0.5 rounded border ${roleBadge}`}>
                          {step.agent_role}
                        </span>
                      </div>
                      <span className="text-[9px] text-white/40 font-mono">
                        {step.timestamp ? new Date(step.timestamp * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : ""}
                      </span>
                    </div>

                    {/* Action & Tool */}
                    <div className="flex items-center gap-1.5 text-white/90 font-mono text-[11px] truncate">
                      {step.action_type === "file_edit" ? (
                        <FileCode size={12} className="text-cyan-400 shrink-0" />
                      ) : step.action_type === "test_run" ? (
                        <Terminal size={12} className="text-emerald-400 shrink-0" />
                      ) : (
                        <Code2 size={12} className="text-primary shrink-0" />
                      )}
                      <span className="truncate">{step.tool_name || step.action_type}</span>
                    </div>

                    {/* Rewind to here button on hover / active */}
                    <div className="mt-2 pt-2 border-t border-white/5 flex items-center justify-between">
                      <span className="text-[9px] text-white/40 truncate max-w-[140px]">
                        {step.thinking ? step.thinking.slice(0, 35) + "..." : step.status}
                      </span>
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          openForkModal(step.step_id);
                        }}
                        className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[9.5px] font-bold bg-amber-500/15 hover:bg-amber-500/25 text-amber-300 border border-amber-500/30 transition-all cursor-pointer"
                        title="Rewind execution and branch a new timeline from this step"
                      >
                        <GitFork size={9} />
                        <span>Rewind</span>
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* ── Right Column: Step Detail View ─────────────────────────────────── */}
        <div id="step-detail-view" className="flex-1 min-h-0 flex flex-col bg-[#0b0d14] overflow-hidden">
          {currentStep ? (
            <div className="flex-1 flex flex-col min-h-0">
              {/* Detail Header */}
              <div className="p-4 border-b border-white/10 bg-[#12141f]/60 flex items-center justify-between gap-4 flex-shrink-0">
                <div className="flex items-center gap-3">
                  <span className="font-mono font-bold text-base text-white">
                    Step {currentStep.step_num || 1}
                  </span>
                  <span className={`text-[10px] font-bold uppercase px-2 py-0.5 rounded border ${getRoleBadgeClass(currentStep.agent_role)}`}>
                    {currentStep.agent_role}
                  </span>
                  <span className="text-xs font-mono text-white/70 bg-white/5 px-2.5 py-1 rounded-md border border-white/10">
                    {currentStep.tool_name || currentStep.action_type}
                  </span>
                  {getStatusBadge(currentStep.status)}
                </div>

                <div className="flex items-center gap-2">
                  <div className="flex bg-black/40 p-1 rounded-lg border border-white/5 text-xs font-medium">
                    <button
                      onClick={() => setActiveTab("detail")}
                      className={`px-3 py-1 rounded-md transition-all cursor-pointer ${
                        activeTab === "detail" ? "bg-primary/20 text-primary border border-primary/30" : "text-white/60 hover:text-white"
                      }`}
                    >
                      Step Details
                    </button>
                    <button
                      onClick={() => setActiveTab("manifest")}
                      className={`px-3 py-1 rounded-md transition-all cursor-pointer ${
                        activeTab === "manifest" ? "bg-primary/20 text-primary border border-primary/30" : "text-white/60 hover:text-white"
                      }`}
                    >
                      Snapshot Manifest
                    </button>
                  </div>
                </div>
              </div>

              {/* Scrollable Content */}
              <div className="flex-1 overflow-y-auto p-6 space-y-6 custom-scrollbar">
                {activeTab === "detail" ? (
                  <>
                    {/* 1. Agent Thought / Reasoning */}
                    {currentStep.thinking && (
                      <div className="bg-[#151724] rounded-xl border border-white/10 p-4 space-y-2 shadow-sm">
                        <div className="flex items-center gap-2 text-xs font-bold text-purple-300">
                          <Brain size={14} />
                          <span>Agent Thought &amp; Reasoning</span>
                        </div>
                        <p className="text-xs text-white/80 leading-relaxed whitespace-pre-wrap font-sans bg-black/20 p-3 rounded-lg border border-white/5">
                          {currentStep.thinking}
                        </p>
                      </div>
                    )}

                    {/* 2. Tool Call Input & Parameters */}
                    <div className="bg-[#151724] rounded-xl border border-white/10 p-4 space-y-2 shadow-sm">
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2 text-xs font-bold text-primary">
                          <Code2 size={14} />
                          <span>Tool Call &amp; Parameters</span>
                        </div>
                        <span className="text-[10px] font-mono text-white/40">
                          {currentStep.tool_name || "tool_call"}
                        </span>
                      </div>
                      <pre className="text-[11px] font-mono bg-black/40 p-3 rounded-lg border border-white/5 text-cyan-200 overflow-x-auto max-h-60 custom-scrollbar">
                        {typeof currentStep.input === "object"
                          ? JSON.stringify(currentStep.input, null, 2)
                          : String(currentStep.input || "{}")}
                      </pre>
                    </div>

                    {/* 3. File Changes & Diffs */}
                    {currentStep.file_changes && currentStep.file_changes.length > 0 && (
                      <div className="bg-[#151724] rounded-xl border border-white/10 p-4 space-y-3 shadow-sm">
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-2 text-xs font-bold text-cyan-300">
                            <FileCode size={14} />
                            <span>File Changes ({currentStep.file_changes.length})</span>
                          </div>
                        </div>
                        <div className="space-y-3">
                          {currentStep.file_changes.map((fc, i) => (
                            <div key={i} className="rounded-lg border border-white/10 overflow-hidden bg-black/30">
                              <div className="px-3 py-1.5 bg-white/5 border-b border-white/10 flex items-center justify-between text-xs font-mono text-white/80">
                                <span>{fc.path}</span>
                              </div>
                              {fc.updated && (
                                <pre className="p-3 text-[11px] font-mono overflow-x-auto max-h-48 text-emerald-300 custom-scrollbar whitespace-pre">
                                  {fc.updated}
                                </pre>
                              )}
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* 4. Output Result / Terminal Execution */}
                    <div className="bg-[#151724] rounded-xl border border-white/10 p-4 space-y-2 shadow-sm">
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2 text-xs font-bold text-emerald-300">
                          <Terminal size={14} />
                          <span>Execution Output &amp; Result</span>
                        </div>
                      </div>
                      <pre className="text-[11px] font-mono bg-black/50 p-3 rounded-lg border border-white/5 text-emerald-200/90 overflow-x-auto max-h-72 custom-scrollbar whitespace-pre-wrap">
                        {typeof currentStep.output === "object"
                          ? JSON.stringify(currentStep.output, null, 2)
                          : String(currentStep.output || "No output")}
                      </pre>
                    </div>
                  </>
                ) : (
                  /* ── Snapshot Manifest View ───────────────────────────────── */
                  <div className="space-y-4">
                    <div className="bg-[#151724] rounded-xl border border-white/10 p-4 space-y-3 shadow-sm">
                      <div className="flex items-center gap-2 text-xs font-bold text-primary">
                        <Layers size={14} />
                        <span>Workspace Manifest at Step {currentStep.step_num}</span>
                      </div>
                      <p className="text-xs text-white/60">
                        Tracks all files generated or modified up to this point in time across DAG tasks.
                      </p>

                      {activeSnapshot?.workspace_manifest && Object.keys(activeSnapshot.workspace_manifest).length > 0 ? (
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-3 pt-2">
                          {Object.entries(activeSnapshot.workspace_manifest).map(([p, info]: [string, any]) => (
                            <div key={p} className="p-3 rounded-lg bg-black/30 border border-white/5 text-xs space-y-1">
                              <div className="font-mono font-bold text-white truncate">{p}</div>
                              <div className="text-[10px] text-white/50">{info.purpose || "Generated artifact"}</div>
                              <span className="inline-block text-[9px] px-1.5 py-0.5 rounded bg-white/5 text-white/70 font-mono">
                                Role: {info.agent_role || "agent"}
                              </span>
                            </div>
                          ))}
                        </div>
                      ) : (
                        <div className="py-8 text-center text-xs text-white/40">
                          No manifest entries recorded prior to this step.
                        </div>
                      )}
                    </div>
                  </div>
                )}
              </div>
            </div>
          ) : (
            <div className="flex-1 flex flex-col items-center justify-center text-xs text-white/40 gap-2">
              <History size={24} className="text-white/20" />
              <span>Select a step from the timeline scrubber to inspect details.</span>
            </div>
          )}

          {/* ── Bottom Action Bar ────────────────────────────────────────────── */}
          <div className="h-14 border-t border-white/10 bg-[#12141f]/80 px-6 flex items-center justify-between gap-4 flex-shrink-0">
            <div className="flex items-center gap-2">
              <button
                id="btn-fork-from-step"
                disabled={!activeSessionId || !currentStep}
                onClick={() => openForkModal(currentStep?.step_id)}
                className="flex items-center gap-2 px-4 py-2 rounded-xl bg-amber-500/20 hover:bg-amber-500/30 text-amber-300 border border-amber-500/40 text-xs font-bold transition-all cursor-pointer shadow-sm hover:shadow-[0_0_12px_rgba(245,158,11,0.2)] disabled:opacity-40"
                title="Fork timeline from this step"
              >
                <GitFork size={14} />
                <span>Fork from this step</span>
              </button>
            </div>

            <div className="flex items-center gap-2">
              <button
                id="btn-export-markdown"
                disabled={!activeSessionId}
                onClick={() => void exportSession(activeSessionId!, "markdown")}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-white/5 hover:bg-white/10 text-white/80 hover:text-white border border-white/10 text-xs font-bold transition-all cursor-pointer disabled:opacity-40"
                title="Export session transcript as Markdown"
              >
                <FileText size={13} />
                <span>Export Markdown</span>
              </button>

              <button
                id="btn-export-json"
                disabled={!activeSessionId}
                onClick={() => void exportSession(activeSessionId!, "json")}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-white/5 hover:bg-white/10 text-white/80 hover:text-white border border-white/10 text-xs font-bold transition-all cursor-pointer disabled:opacity-40"
                title="Export session transcript as JSON"
              >
                <Download size={13} />
                <span>Export JSON</span>
              </button>
            </div>
          </div>
        </div>
      </div>

      {renderForkModal()}
    </div>
  );
}
