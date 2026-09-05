import React, { useState, useEffect } from "react";
import {
  Play,
  Pause,
  RotateCcw,
  Square,
  Sliders,
  Sparkles,
  Layers,
  AlertCircle,
  Clock,
  Radio,
  Folder,
  Plus,
  CheckCircle2,
  Download,
} from "lucide-react";
import { useTeamStore } from "./teamStore";
import { AgentRoster } from "./AgentRoster";
import { DAGBoard } from "./DAGBoard";
import { TeamChatPanel } from "./TeamChatPanel";
import { useWorkspaceStore } from "../../../stores/workspaceStore";

export const TeamConsole: React.FC = () => {
  const currentWorkspace = useWorkspaceStore((state) => state.currentWorkspace);
  const {
    activeJobId,
    jobStatus,
    sseStatus,
    error,
    teamConfig,
    updateTeamConfig,
    submitTeamJob,
    pauseJob,
    resumeJob,
    cancelJob,
    reset,
    finalReport,
    agentMetrics,
    saveFinalReport,
    exportReportMarkdown,
  } = useTeamStore();

  const [instruction, setInstruction] = useState("");
  const [showConfig, setShowConfig] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);

  useEffect(() => {
    if (jobStatus === "completed" && finalReport && activeJobId) {
      saveFinalReport(finalReport);
    }
  }, [jobStatus, finalReport, activeJobId, saveFinalReport]);

  const handleExportReport = async () => {
    try {
      const md = await exportReportMarkdown();
      const blob = new Blob([md], { type: "text/markdown;charset=utf-8" });
      if (typeof window !== "undefined" && typeof document !== "undefined") {
        const url = window.URL?.createObjectURL ? window.URL.createObjectURL(blob) : "blob:dummy";
        const a = document.createElement("a");
        a.href = url;
        a.download = `team-job-${activeJobId || "report"}.md`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        if (window.URL?.revokeObjectURL && url !== "blob:dummy") {
          window.URL.revokeObjectURL(url);
        }
      }
    } catch (err) {
      console.error("Export report error:", err);
    }
  };

  const isRunning = jobStatus === "running" || jobStatus === "queued";
  const isPaused = jobStatus === "paused";

  const handleLaunch = async () => {
    if (!instruction.trim()) {
      setLocalError("Please enter a task instruction for the autonomous team.");
      return;
    }
    if (!currentWorkspace?.path) {
      setLocalError("Please select a workspace for the team to operate in.");
      return;
    }

    setSubmitting(true);
    setLocalError(null);
    try {
      await submitTeamJob(currentWorkspace.path, instruction.trim());
    } catch (err: any) {
      setLocalError(err?.message || "Failed to submit team job");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div
      data-testid="team-console"
      className="flex-1 flex flex-col h-full overflow-hidden bg-background text-on-surface font-ui-label-reg text-ui-label-reg"
    >
      {/* Top Bar: Job Status & Global Controls */}
      <div className="flex items-center justify-between px-6 py-3 border-b border-white/5 bg-surface-container-lowest shrink-0">
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2">
            <span className="text-xs font-bold uppercase tracking-wider text-on-surface">
              Autonomous Team Engine
            </span>
            <span className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-primary-container/10 text-primary-container border border-primary-container/30">
              v4.0 DAG Mode
            </span>
          </div>

          {activeJobId && (
            <div className="flex items-center gap-2 pl-3 border-l border-white/10">
              <span className="text-[10px] font-mono text-on-surface-variant">
                ID: {activeJobId.slice(0, 12)}
              </span>
              <span
                className={`px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider flex items-center gap-1.5 ${
                  isRunning
                    ? "bg-primary-container/15 text-primary-container border border-primary-container/40"
                    : isPaused
                    ? "bg-amber-500/15 text-amber-300 border border-amber-500/40"
                    : jobStatus === "completed"
                    ? "bg-emerald-500/15 text-emerald-300 border border-emerald-500/40"
                    : jobStatus === "failed"
                    ? "bg-error/15 text-error border border-error/40"
                    : "bg-surface-variant text-on-surface-variant"
                }`}
              >
                <span
                  className={`w-1.5 h-1.5 rounded-full ${
                    isRunning
                      ? "bg-primary-container animate-ping"
                      : isPaused
                      ? "bg-amber-400"
                      : jobStatus === "completed"
                      ? "bg-emerald-400"
                      : "bg-outline"
                  }`}
                />
                {jobStatus}
              </span>

              {/* SSE Status Pill */}
              <div
                className="flex items-center gap-1 text-[10px] font-mono text-on-surface-variant"
                title={`SSE Stream: ${sseStatus}`}
              >
                <Radio
                  size={11}
                  className={
                    sseStatus === "connected"
                      ? "text-emerald-400 animate-pulse"
                      : sseStatus === "connecting"
                      ? "text-amber-400 animate-spin"
                      : "text-on-surface-variant/40"
                  }
                />
                <span className="capitalize">{sseStatus}</span>
              </div>
            </div>
          )}
        </div>

        {/* Global Action Buttons */}
        <div className="flex items-center gap-2">
          {activeJobId && (
            <>
              {isPaused ? (
                <button
                  onClick={() => resumeJob()}
                  className="flex items-center gap-1.5 px-3 py-1 rounded-lg text-xs font-semibold bg-emerald-500/20 hover:bg-emerald-500/30 text-emerald-300 border border-emerald-500/40 cursor-pointer transition-colors"
                >
                  <Play size={13} />
                  <span>Resume</span>
                </button>
              ) : isRunning ? (
                <button
                  onClick={() => pauseJob()}
                  className="flex items-center gap-1.5 px-3 py-1 rounded-lg text-xs font-semibold bg-amber-500/20 hover:bg-amber-500/30 text-amber-300 border border-amber-500/40 cursor-pointer transition-colors"
                >
                  <Pause size={13} />
                  <span>Pause</span>
                </button>
              ) : null}

              {(isRunning || isPaused) && (
                <button
                  onClick={() => cancelJob()}
                  className="flex items-center gap-1.5 px-3 py-1 rounded-lg text-xs font-semibold bg-error/20 hover:bg-error/30 text-error border border-error/40 cursor-pointer transition-colors"
                >
                  <Square size={13} />
                  <span>Cancel</span>
                </button>
              )}

              <button
                onClick={() => reset()}
                className="flex items-center gap-1.5 px-3 py-1 rounded-lg text-xs bg-surface-container hover:bg-surface-variant text-on-surface-variant hover:text-on-surface border border-white/10 cursor-pointer transition-colors"
                title="Reset to New Task Intake"
              >
                <RotateCcw size={13} />
                <span>New Job</span>
              </button>
            </>
          )}
        </div>
      </div>

      {/* Error Banner */}
      {(error || localError) && (
        <div className="mx-6 mt-3 rounded-lg border border-error/40 bg-error/10 p-2.5 text-xs text-error flex items-center justify-between shrink-0">
          <div className="flex items-center gap-2">
            <AlertCircle size={15} />
            <span>{error || localError}</span>
          </div>
          <button
            onClick={() => setLocalError(null)}
            className="text-error hover:opacity-80 cursor-pointer"
          >
            ×
          </button>
        </div>
      )}

      {/* Final Verification Report Card */}
      {jobStatus === "completed" && finalReport && (
        <div
          data-testid="final-report-card"
          className="mx-6 mt-4 p-4 rounded-xl bg-gradient-to-r from-emerald-500/10 via-surface-container to-purple-500/10 border border-emerald-500/30 shadow-lg shrink-0 flex flex-col gap-3"
        >
          <div className="flex items-center justify-between border-b border-white/5 pb-2">
            <div className="flex items-center gap-2">
              <span className="p-1 rounded bg-emerald-500/20 text-emerald-400">
                <CheckCircle2 size={16} />
              </span>
              <span className="font-bold text-xs uppercase tracking-wider text-emerald-300">
                Job Verification Passed — Final Report
              </span>
            </div>
            <div className="flex items-center gap-2">
              <button
                data-testid="export-report-btn"
                onClick={handleExportReport}
                className="flex items-center gap-1.5 px-3 py-1 rounded-lg text-[11px] font-semibold bg-emerald-500/20 hover:bg-emerald-500/30 text-emerald-300 border border-emerald-500/40 cursor-pointer transition-colors shadow-sm"
                title="Export Report as Markdown"
              >
                <Download size={13} />
                <span>Export Report</span>
              </button>
              <span className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-emerald-500/20 text-emerald-300 border border-emerald-500/30">
                VERIFIED
              </span>
            </div>
          </div>

          <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
            <div className="flex flex-col gap-0.5 bg-surface-container-low/60 p-2.5 rounded-lg border border-white/5">
              <span className="text-[10px] text-on-surface-variant font-medium">Files Changed</span>
              <span className="text-sm font-bold font-mono text-on-surface">
                {finalReport.files_changed}
              </span>
            </div>

            <div className="flex flex-col gap-0.5 bg-surface-container-low/60 p-2.5 rounded-lg border border-white/5">
              <span className="text-[10px] text-on-surface-variant font-medium">Tests Run</span>
              <div className="flex items-baseline gap-1 text-sm font-bold font-mono text-on-surface">
                <span>{finalReport.tests_run}</span>
                <span className="text-[10px] font-normal text-on-surface-variant font-mono">
                  (passed: {finalReport.tests_passed}, failed: {finalReport.tests_failed})
                </span>
              </div>
            </div>

            <div className="flex flex-col gap-0.5 bg-surface-container-low/60 p-2.5 rounded-lg border border-white/5">
              <span className="text-[10px] text-on-surface-variant font-medium">Review Notes</span>
              <span className="text-sm font-bold font-mono text-on-surface">
                {finalReport.review_notes} blockers found
              </span>
            </div>

            <div className="flex flex-col gap-0.5 bg-surface-container-low/60 p-2.5 rounded-lg border border-white/5">
              <span className="text-[10px] text-on-surface-variant font-medium">Repair Rounds</span>
              <span className="text-sm font-bold font-mono text-on-surface">
                {finalReport.repair_rounds}
              </span>
            </div>

            <div className="flex flex-col gap-0.5 bg-surface-container-low/60 p-2.5 rounded-lg border border-white/5">
              <span className="text-[10px] text-on-surface-variant font-medium">Total Cost</span>
              <span className="text-sm font-bold font-mono text-emerald-400">
                ${Number(finalReport.total_cost || 0).toFixed(2)}
              </span>
            </div>
          </div>

          {/* Per-Role Cost Breakdown */}
          <div className="pt-2 border-t border-white/5 flex flex-col gap-2">
            <span className="text-[10px] font-bold text-on-surface-variant uppercase tracking-wider">
              Per-Role Cost Breakdown
            </span>
            <div className="grid grid-cols-2 sm:grid-cols-5 gap-2">
              {(["architect", "coder", "reviewer", "tester", "devops"] as const).map((role) => {
                const m = agentMetrics[role] || { total_tokens: 0, total_cost: 0, input_tokens: 0, output_tokens: 0 };
                return (
                  <div
                    key={role}
                    data-testid={`final-cost-${role}`}
                    className="bg-surface-container-low/70 p-2 rounded-lg border border-white/5 flex flex-col gap-0.5"
                  >
                    <div className="flex items-center justify-between">
                      <span className="text-[10px] font-bold capitalize text-on-surface">{role}</span>
                      <span className="text-[9px] font-mono text-on-surface-variant">
                        {Number(m.total_tokens || 0).toLocaleString()} tok
                      </span>
                    </div>
                    <span className="text-xs font-mono font-bold text-emerald-400">
                      ${Number(m.total_cost || 0).toFixed(2)}
                    </span>
                    <div className="text-[9px] font-mono text-on-surface-variant/80 flex justify-between">
                      <span>In: {Number(m.input_tokens || 0).toLocaleString()}</span>
                      <span>Out: {Number(m.output_tokens || 0).toLocaleString()}</span>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      )}

      {/* Main Content Area */}
      <div className="flex-1 flex flex-col p-6 min-h-0 overflow-hidden gap-4">
        {/* Task Intake Form (collapsed when job active, or visible for new job) */}
        {!activeJobId && (
          <div className="bg-surface-container-low rounded-xl border border-white/10 p-5 flex flex-col gap-4 shadow-xl shrink-0">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2 text-on-surface font-bold text-sm">
                <Sparkles size={16} className="text-primary-container" />
                <span>Multi-Agent Task Intake</span>
              </div>
              <button
                onClick={() => setShowConfig(!showConfig)}
                className={`flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs border transition-colors cursor-pointer ${
                  showConfig
                    ? "bg-primary-container/20 border-primary-container/40 text-primary-container"
                    : "bg-surface-container border-white/10 text-on-surface-variant hover:text-on-surface"
                }`}
              >
                <Sliders size={13} />
                <span>Team Roster Config</span>
              </button>
            </div>

            {/* Workspace & Prompt */}
            <div className="flex flex-col gap-3">
              <div className="flex items-center gap-3">
                <div className="flex items-center gap-2 text-xs text-on-surface-variant shrink-0">
                  <Folder size={14} />
                  <span>Workspace:</span>
                </div>
                <div className="flex-1 font-mono text-xs text-on-surface bg-surface-container border border-white/10 rounded-lg px-3 py-1.5">
                  {currentWorkspace?.path || "No workspace opened"}
                </div>
              </div>

              <textarea
                value={instruction}
                onChange={(e) => setInstruction(e.target.value)}
                placeholder="Describe your large project or high-stakes feature (e.g. Build an authentication service with JWT and SQLite, write unit tests, verify build)..."
                rows={3}
                disabled={submitting}
                className="w-full bg-[#131315] border border-white/10 rounded-xl p-3 text-xs text-on-surface placeholder:text-on-surface-variant/40 focus:border-primary-container focus:outline-none font-mono resize-none"
              />
            </div>

            {/* Team Config Panel Accordion */}
            {showConfig && (
              <div className="bg-[#101013] border border-white/5 rounded-xl p-4 flex flex-col gap-3">
                <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-xs">
                  <div>
                    <label className="text-on-surface-variant text-[11px] block mb-1">
                      Max Parallel Agents: {teamConfig.max_concurrency}
                    </label>
                    <input
                      type="range"
                      min={1}
                      max={5}
                      value={teamConfig.max_concurrency}
                      onChange={(e) =>
                        updateTeamConfig({ max_concurrency: parseInt(e.target.value, 10) })
                      }
                      className="w-full cursor-pointer"
                    />
                  </div>
                  <div>
                    <label className="text-on-surface-variant text-[11px] block mb-1">
                      Max Self-Repair Rounds: {teamConfig.max_repair_rounds}
                    </label>
                    <input
                      type="range"
                      min={1}
                      max={5}
                      value={teamConfig.max_repair_rounds}
                      onChange={(e) =>
                        updateTeamConfig({ max_repair_rounds: parseInt(e.target.value, 10) })
                      }
                      className="w-full cursor-pointer"
                    />
                  </div>
                  <div className="flex items-center gap-2 pt-4">
                    <input
                      type="checkbox"
                      id="auto-verify-toggle"
                      checked={teamConfig.auto_verify}
                      onChange={(e) => updateTeamConfig({ auto_verify: e.target.checked })}
                      className="rounded border-white/20 text-primary-container cursor-pointer"
                    />
                    <label htmlFor="auto-verify-toggle" className="text-xs text-on-surface cursor-pointer">
                      Auto-Verify Web Scaffolding
                    </label>
                  </div>
                </div>
              </div>
            )}

            {/* Submit Action */}
            <div className="flex justify-end">
              <button
                onClick={handleLaunch}
                disabled={submitting || !instruction.trim()}
                className="flex items-center gap-2 px-5 py-2 rounded-xl text-xs font-bold bg-primary-container text-on-primary-container hover:opacity-90 disabled:opacity-50 transition-all cursor-pointer shadow-lg shadow-primary-container/20"
              >
                <Play size={14} fill="currentColor" />
                <span>{submitting ? "Orchestrating..." : "Plan & Execute Team Job"}</span>
              </button>
            </div>
          </div>
        )}

        {/* 3-Column Core Layout: Roster | DAGBoard | Comms Feed */}
        <div className="flex-1 grid grid-cols-12 gap-4 min-h-0 overflow-hidden">
          {/* Left Column: Agent Roster */}
          <div className="col-span-3 h-full overflow-hidden">
            <AgentRoster />
          </div>

          {/* Center Column: Visual 2D DAG Graph */}
          <div className="col-span-6 h-full overflow-hidden">
            <DAGBoard />
          </div>

          {/* Right Column: Team Comms Feed */}
          <div className="col-span-3 h-full overflow-hidden">
            <TeamChatPanel />
          </div>
        </div>
      </div>
    </div>
  );
};
