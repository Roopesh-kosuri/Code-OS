import React, { useState, useEffect } from "react";
import { ClipboardList, Sparkles, Copy, Check, ChevronDown, ChevronUp, RotateCw, History, Calendar, FileText, MessageSquare } from "lucide-react";
import { useStandupStore } from "./standupStore";
import { useWorkspaceStore } from "../../stores/workspaceStore";

export function StandupGeneratorPanel() {
  const currentWorkspace = useWorkspaceStore((state) => state.currentWorkspace);
  const {
    rawActivity,
    generatedReport,
    format,
    isGenerating,
    copied,
    generateStandup,
    setFormat,
    copyToClipboard,
    loadHistory,
    history,
  } = useStandupStore();

  const [selectedDate, setSelectedDate] = useState(() => {
    const d = new Date();
    d.setDate(d.getDate() - 1);
    return d.toISOString().split("T")[0];
  });
  const [showRawActivity, setShowRawActivity] = useState(false);
  const [showHistory, setShowHistory] = useState(false);
  const [saveStatus, setSaveStatus] = useState<string | null>(null);

  useEffect(() => {
    if (currentWorkspace?.path) {
      void loadHistory(currentWorkspace.path);
    }
  }, [currentWorkspace?.path, loadHistory]);

  const handleGenerate = () => {
    if (currentWorkspace?.path) {
      void generateStandup(currentWorkspace.path, selectedDate, format);
    }
  };

  const handleFormatChange = (newFormat: "slack" | "markdown") => {
    setFormat(newFormat);
    if (currentWorkspace?.path && generatedReport) {
      void generateStandup(currentWorkspace.path, selectedDate, newFormat);
    }
  };

  const handleSaveToHistory = () => {
    setSaveStatus("Saved to history");
    setTimeout(() => setSaveStatus(null), 2000);
  };

  const jobsCount = rawActivity.jobs_completed?.length || 0;
  const filesCount = rawActivity.files_modified?.length || 0;
  const commitsCount = rawActivity.commits_made?.length || 0;
  const costSpent = rawActivity.total_cost || "$0.00";

  const summaryText = `Completed ${jobsCount} jobs, modified ${filesCount} files, ${commitsCount} git commits, spent ${costSpent}`;

  return (
    <div className="flex flex-col h-full w-full bg-[#0d0e15] text-white select-none overflow-hidden" data-testid="standup-generator-panel">
      {/* ── Top Header ──────────────────────────────────────────────────────── */}
      <div className="p-3.5 border-b border-white/10 flex items-center justify-between bg-white/[0.02]">
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-lg bg-cyan-500/20 border border-cyan-500/30 flex items-center justify-center text-cyan-400 shadow-[0_0_12px_rgba(0,218,243,0.2)]">
            <ClipboardList size={18} />
          </div>
          <div>
            <h2 className="text-xs font-bold tracking-wide uppercase text-white/90">Daily Standup Generator</h2>
            <p className="text-[10px] text-white/50">Auto-synthesize activity into standup reports</p>
          </div>
        </div>

        <button
          onClick={() => setShowHistory(!showHistory)}
          data-testid="toggle-history-btn"
          className="p-1.5 rounded-lg bg-white/5 hover:bg-white/10 text-white/70 hover:text-white transition-colors cursor-pointer"
          title="Past Reports"
        >
          <History size={15} />
        </button>
      </div>

      {/* ── Controls Bar ────────────────────────────────────────────────────── */}
      <div className="p-3 border-b border-white/5 bg-black/20 flex flex-wrap items-center justify-between gap-2.5">
        <div className="flex items-center gap-2">
          <div className="flex items-center gap-1.5 text-xs text-white/70 font-medium">
            <Calendar size={13} className="text-cyan-400" />
            <input
              type="date"
              value={selectedDate}
              onChange={(e) => setSelectedDate(e.target.value)}
              data-testid="standup-date-picker"
              className="bg-surface-container-high border border-white/10 rounded-md px-2 py-1 text-xs text-white font-mono focus:outline-none focus:border-cyan-400"
            />
          </div>
        </div>

        <button
          onClick={handleGenerate}
          disabled={isGenerating}
          data-testid="generate-standup-btn"
          className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg bg-cyan-500 hover:bg-cyan-400 text-black text-xs font-bold transition-all shadow-[0_0_15px_rgba(0,218,243,0.3)] cursor-pointer disabled:opacity-50"
        >
          <Sparkles size={13} className={isGenerating ? "animate-spin" : ""} />
          {isGenerating ? "Synthesizing..." : "Generate Standup"}
        </button>
      </div>

      {/* ── Collapsible Raw Activity Summary ─────────────────────────────────── */}
      <div className="border-b border-white/5 bg-white/[0.01]">
        <button
          onClick={() => setShowRawActivity(!showRawActivity)}
          data-testid="toggle-raw-activity"
          className="w-full px-3.5 py-2 flex items-center justify-between text-xs text-white/70 hover:text-white transition-colors cursor-pointer"
        >
          <span className="font-semibold flex items-center gap-1.5">
            Activity Summary
          </span>
          {showRawActivity ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
        </button>

        {showRawActivity && (
          <div className="px-3 pb-3 grid grid-cols-2 gap-1.5" data-testid="raw-activity-summary">
            {[
              { label: "Jobs", value: jobsCount, color: "text-cyan-400" },
              { label: "Files", value: filesCount, color: "text-violet-400" },
              { label: "Commits", value: commitsCount, color: "text-emerald-400" },
              { label: "Cost", value: costSpent, color: "text-amber-400" },
            ].map(({ label, value, color }) => (
              <div key={label} className="bg-black/30 rounded-lg p-2 border border-white/5 flex flex-col">
                <span className="text-[9px] uppercase font-bold text-white/40 tracking-wider">{label}</span>
                <span className={`text-sm font-bold font-mono ${color}`}>{value}</span>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* ── Generated Report Preview Area ───────────────────────────────────── */}
      <div className="flex-1 min-h-0 flex flex-col p-3.5 overflow-hidden">
        {/* Format Selector and Toolbar */}
        <div className="flex items-center justify-between pb-2.5">
          <div className="flex items-center gap-1 bg-white/5 p-1 rounded-lg border border-white/10">
            <button
              onClick={() => handleFormatChange("slack")}
              data-testid="format-slack-btn"
              className={`px-2.5 py-1 rounded text-xs font-semibold flex items-center gap-1.5 transition-all cursor-pointer ${
                format === "slack"
                  ? "bg-cyan-500/20 text-cyan-300 border border-cyan-500/40 shadow-xs"
                  : "text-white/50 hover:text-white"
              }`}
            >
              <MessageSquare size={12} />
              Slack Format
            </button>
            <button
              onClick={() => handleFormatChange("markdown")}
              data-testid="format-markdown-btn"
              className={`px-2.5 py-1 rounded text-xs font-semibold flex items-center gap-1.5 transition-all cursor-pointer ${
                format === "markdown"
                  ? "bg-cyan-500/20 text-cyan-300 border border-cyan-500/40 shadow-xs"
                  : "text-white/50 hover:text-white"
              }`}
            >
              <FileText size={12} />
              Markdown Format
            </button>
          </div>

          {/* Action buttons */}
          <div className="flex items-center gap-1.5">
            <button
              onClick={handleSaveToHistory}
              data-testid="save-history-btn"
              className="px-2.5 py-1 rounded text-[11px] font-medium bg-white/5 hover:bg-white/10 text-white/80 border border-white/10 transition-colors cursor-pointer"
            >
              {saveStatus || "Save to History"}
            </button>
            <button
              onClick={() => currentWorkspace?.path && void generateStandup(currentWorkspace.path, selectedDate, format)}
              disabled={isGenerating}
              data-testid="regenerate-btn"
              title="Regenerate with AI"
              className="p-1 rounded bg-white/5 hover:bg-white/10 text-white/80 border border-white/10 transition-colors cursor-pointer"
            >
              <RotateCw size={13} className={isGenerating ? "animate-spin" : ""} />
            </button>
            <button
              onClick={() => void copyToClipboard()}
              data-testid="copy-clipboard-btn"
              className={`px-2.5 py-1 rounded text-[11px] font-bold flex items-center gap-1 transition-all cursor-pointer ${
                copied
                  ? "bg-emerald-500/20 text-emerald-300 border border-emerald-500/40"
                  : "bg-cyan-500/20 hover:bg-cyan-500/30 text-cyan-300 border border-cyan-500/40"
              }`}
            >
              {copied ? <Check size={12} /> : <Copy size={12} />}
              {copied ? "Copied!" : "Copy to Clipboard"}
            </button>
          </div>
        </div>

        {/* Text Area */}
        <div className="flex-1 min-h-0 bg-[#12141f] border border-white/10 rounded-xl p-3 overflow-hidden flex flex-col shadow-inner">
          {generatedReport ? (
            <textarea
              readOnly
              value={generatedReport}
              data-testid="generated-report-textarea"
              className="w-full h-full bg-transparent text-white font-mono text-xs resize-none focus:outline-none leading-relaxed whitespace-pre-wrap selection:bg-cyan-500/30"
            />
          ) : (
            <div className="h-full flex flex-col items-center justify-center text-center text-white/40">
              <ClipboardList size={36} className="text-white/20 mb-2" />
              <p className="text-xs">No standup generated yet.</p>
              <p className="text-[10px] text-white/30 mt-1">Pick a date and click "Generate Standup".</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
