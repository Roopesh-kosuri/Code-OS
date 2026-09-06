import React, { useState } from "react";
import {
  X,
  Copy,
  Check,
  FileCode,
  FlaskConical,
  ShieldCheck,
  Server,
  Layers,
  Terminal,
  ArrowRight,
  Code2,
  Info,
  CheckCircle2,
  XCircle,
  type LucideIcon,
} from "lucide-react";
import type { HandoffArtifact, TeamRole } from "./teamStore";

export interface HandoffInspectorProps {
  artifact: HandoffArtifact | any | null;
  isOpen: boolean;
  onClose: () => void;
}

const ROLE_ICONS: Record<string, LucideIcon> = {
  architect: Layers,
  coder: Terminal,
  reviewer: ShieldCheck,
  tester: FlaskConical,
  devops: Server,
};

const ROLE_COLORS: Record<string, string> = {
  architect: "bg-blue-500/20 text-blue-400 border-blue-500/30",
  coder: "bg-emerald-500/20 text-emerald-400 border-emerald-500/30",
  reviewer: "bg-amber-500/20 text-amber-400 border-amber-500/30",
  tester: "bg-purple-500/20 text-purple-400 border-purple-500/30",
  devops: "bg-rose-500/20 text-rose-400 border-rose-500/30",
  operator: "bg-yellow-500/20 text-yellow-300 border-yellow-500/40",
  system: "bg-zinc-500/20 text-zinc-400 border-zinc-500/30",
};

export const HandoffInspector: React.FC<HandoffInspectorProps> = ({
  artifact,
  isOpen,
  onClose,
}) => {
  const [activeTab, setActiveTab] = useState<"preview" | "meta" | "json">("preview");
  const [copied, setCopied] = useState(false);

  if (!isOpen || !artifact) return null;

  const handleCopy = async () => {
    try {
      const jsonStr = JSON.stringify(artifact, null, 2);
      if (navigator?.clipboard?.writeText) {
        await navigator.clipboard.writeText(jsonStr);
      }
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Fallback
    }
  };

  const payload = artifact.payload || artifact;
  const artifactType = artifact.type || "files";
  const fromRole = artifact.from_role || "system";
  const toRole = artifact.to_role || "all";
  const summary = artifact.summary || "Inter-agent artifact transfer";
  const timestamp = artifact.created_at || artifact.timestamp;

  const FromIcon = ROLE_ICONS[fromRole] || Terminal;
  const ToIcon = ROLE_ICONS[toRole] || Terminal;

  return (
    <div
      data-testid="handoff-inspector-modal"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4 animate-in fade-in duration-150"
    >
      <div className="relative w-full max-w-2xl max-h-[85vh] bg-surface-container-low border border-white/10 rounded-2xl shadow-2xl flex flex-col overflow-hidden text-on-surface">
        {/* Header */}
        <div className="p-4 border-b border-white/10 flex items-center justify-between bg-surface-container-low">
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-xl bg-primary-container/20 text-primary-container border border-primary-container/30">
              <FileCode size={18} />
            </div>
            <div>
              <h3 className="text-sm font-bold text-on-surface flex items-center gap-2">
                Handoff Inspector
                <span className="text-[10px] uppercase font-mono px-2 py-0.5 rounded-full bg-white/5 border border-white/10 text-on-surface-variant">
                  {artifactType}
                </span>
              </h3>
              <p className="text-xs text-on-surface-variant font-mono truncate max-w-md">
                {summary}
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={handleCopy}
              className="flex items-center gap-1.5 px-2.5 py-1 text-xs font-mono rounded-lg bg-white/5 hover:bg-white/10 border border-white/10 text-on-surface transition-colors cursor-pointer"
              title="Copy Artifact JSON"
            >
              {copied ? (
                <>
                  <Check size={13} className="text-emerald-400" />
                  <span className="text-emerald-400">Copied!</span>
                </>
              ) : (
                <>
                  <Copy size={13} />
                  <span>Copy JSON</span>
                </>
              )}
            </button>
            <button
              onClick={onClose}
              data-testid="close-handoff-inspector"
              className="p-1.5 rounded-lg text-on-surface-variant hover:text-on-surface hover:bg-white/5 transition-colors cursor-pointer"
              aria-label="Close"
            >
              <X size={16} />
            </button>
          </div>
        </div>

        {/* Navigation Tabs */}
        <div className="flex items-center border-b border-white/5 px-4 bg-surface-container-lowest">
          <button
            onClick={() => setActiveTab("preview")}
            data-testid="tab-preview"
            className={`flex items-center gap-2 px-3 py-2.5 text-xs font-medium border-b-2 transition-colors cursor-pointer ${
              activeTab === "preview"
                ? "border-primary-container text-primary-container"
                : "border-transparent text-on-surface-variant hover:text-on-surface"
            }`}
          >
            <FileCode size={13} />
            Artifact Preview
          </button>
          <button
            onClick={() => setActiveTab("meta")}
            data-testid="tab-meta"
            className={`flex items-center gap-2 px-3 py-2.5 text-xs font-medium border-b-2 transition-colors cursor-pointer ${
              activeTab === "meta"
                ? "border-primary-container text-primary-container"
                : "border-transparent text-on-surface-variant hover:text-on-surface"
            }`}
          >
            <Info size={13} />
            Agent Info
          </button>
          <button
            onClick={() => setActiveTab("json")}
            data-testid="tab-json"
            className={`flex items-center gap-2 px-3 py-2.5 text-xs font-medium border-b-2 transition-colors cursor-pointer ${
              activeTab === "json"
                ? "border-primary-container text-primary-container"
                : "border-transparent text-on-surface-variant hover:text-on-surface"
            }`}
          >
            <Code2 size={13} />
            Raw JSON
          </button>
        </div>

        {/* Tab Content */}
        <div className="flex-1 overflow-y-auto p-4 select-text">
          {/* 1. Artifact Preview */}
          {activeTab === "preview" && (
            <div className="flex flex-col gap-4">
              {/* Type: Diffs */}
              {artifactType === "diffs" && (
                <div className="flex flex-col gap-3">
                  {payload.modified_files && payload.modified_files.length > 0 && (
                    <div className="flex flex-col gap-1.5">
                      <span className="text-[11px] font-mono uppercase text-on-surface-variant">
                        Modified Files ({payload.modified_files.length})
                      </span>
                      <div className="flex flex-wrap gap-1.5">
                        {payload.modified_files.map((f: string, i: number) => (
                          <span
                            key={i}
                            className="px-2 py-0.5 rounded text-[11px] font-mono bg-white/5 border border-white/10 text-on-surface"
                          >
                            {f}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}

                  {payload.diffs && Array.isArray(payload.diffs) ? (
                    <div className="flex flex-col gap-2">
                      {payload.diffs.map((diffItem: any, i: number) => (
                        <div
                          key={i}
                          className="bg-black/40 border border-white/10 rounded-xl overflow-hidden"
                        >
                          <div className="p-2 px-3 bg-white/5 border-b border-white/5 text-xs font-mono text-on-surface flex items-center justify-between">
                            <span>{diffItem.path || `Diff #${i + 1}`}</span>
                            {diffItem.action && (
                              <span className="text-[10px] uppercase text-on-surface-variant">
                                {diffItem.action}
                              </span>
                            )}
                          </div>
                          <pre className="p-3 text-[11px] font-mono overflow-x-auto text-emerald-300">
                            {diffItem.diff || JSON.stringify(diffItem, null, 2)}
                          </pre>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <pre className="p-3 bg-black/40 border border-white/10 rounded-xl text-[11px] font-mono text-emerald-300 overflow-x-auto">
                      {typeof payload === "string" ? payload : JSON.stringify(payload, null, 2)}
                    </pre>
                  )}
                </div>
              )}

              {/* Type: Test Output */}
              {artifactType === "test_output" && (
                <div className="flex flex-col gap-3">
                  <div className="flex items-center gap-2">
                    {payload.passed !== false ? (
                      <span className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 text-xs font-mono font-bold">
                        <CheckCircle2 size={13} />
                        TESTS PASSED
                      </span>
                    ) : (
                      <span className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-rose-500/20 text-rose-400 border border-rose-500/30 text-xs font-mono font-bold">
                        <XCircle size={13} />
                        TESTS FAILED
                      </span>
                    )}
                  </div>
                  <div className="bg-black/60 border border-white/10 rounded-xl p-3 font-mono text-xs text-on-surface overflow-x-auto whitespace-pre-wrap">
                    {payload.test_output || payload.output || (typeof payload === "string" ? payload : JSON.stringify(payload, null, 2))}
                  </div>
                </div>
              )}

              {/* Type: Review Notes */}
              {artifactType === "review_notes" && (
                <div className="flex flex-col gap-3">
                  <div className="flex items-center gap-2">
                    {payload.approved !== false ? (
                      <span className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-amber-500/20 text-amber-300 border border-amber-500/30 text-xs font-mono font-bold">
                        <ShieldCheck size={13} />
                        AUDIT APPROVED
                      </span>
                    ) : (
                      <span className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-rose-500/20 text-rose-400 border border-rose-500/30 text-xs font-mono font-bold">
                        <XCircle size={13} />
                        CHANGES REQUESTED
                      </span>
                    )}
                  </div>
                  <div className="bg-surface-container border border-white/10 rounded-xl p-3.5 text-xs text-on-surface leading-relaxed whitespace-pre-wrap">
                    {payload.notes || (typeof payload === "string" ? payload : JSON.stringify(payload, null, 2))}
                  </div>
                </div>
              )}

              {/* Type: Files or Stack Traces or Fallback */}
              {artifactType !== "diffs" &&
                artifactType !== "test_output" &&
                artifactType !== "review_notes" && (
                  <div className="flex flex-col gap-2">
                    <div className="bg-black/40 border border-white/10 rounded-xl p-3 font-mono text-xs text-on-surface overflow-x-auto whitespace-pre-wrap">
                      {typeof payload === "string"
                        ? payload
                        : JSON.stringify(payload, null, 2)}
                    </div>
                  </div>
                )}
            </div>
          )}

          {/* 2. Source / Target Info */}
          {activeTab === "meta" && (
            <div className="flex flex-col gap-4">
              <div className="grid grid-cols-2 gap-3">
                {/* Source Role */}
                <div className="p-3 rounded-xl bg-surface-container border border-white/5 flex flex-col gap-1.5">
                  <span className="text-[10px] font-mono uppercase text-on-surface-variant">
                    Source Agent
                  </span>
                  <div className="flex items-center gap-2">
                    <span
                      className={`flex items-center gap-1.5 px-2 py-0.5 rounded-md border text-xs font-mono font-bold ${
                        ROLE_COLORS[fromRole] || "border-white/10 text-on-surface"
                      }`}
                    >
                      <FromIcon size={12} />
                      @{fromRole}
                    </span>
                  </div>
                </div>

                {/* Target Role */}
                <div className="p-3 rounded-xl bg-surface-container border border-white/5 flex flex-col gap-1.5">
                  <span className="text-[10px] font-mono uppercase text-on-surface-variant">
                    Target Agent
                  </span>
                  <div className="flex items-center gap-2">
                    <span
                      className={`flex items-center gap-1.5 px-2 py-0.5 rounded-md border text-xs font-mono font-bold ${
                        ROLE_COLORS[toRole] || "border-white/10 text-on-surface"
                      }`}
                    >
                      <ToIcon size={12} />
                      @{toRole}
                    </span>
                  </div>
                </div>
              </div>

              {/* Task Details */}
              <div className="p-3 rounded-xl bg-surface-container border border-white/5 flex flex-col gap-2 text-xs">
                <div className="flex items-center justify-between border-b border-white/5 pb-2">
                  <span className="text-on-surface-variant">Associated Task ID</span>
                  <span className="font-mono text-on-surface font-semibold">
                    {artifact.task_id || "N/A"}
                  </span>
                </div>
                <div className="flex items-center justify-between border-b border-white/5 pb-2">
                  <span className="text-on-surface-variant">Artifact Protocol Type</span>
                  <span className="font-mono uppercase text-primary-container font-semibold">
                    {artifactType}
                  </span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-on-surface-variant">Handoff Timestamp</span>
                  <span className="font-mono text-on-surface">
                    {timestamp ? new Date(timestamp * 1000).toLocaleString() : "N/A"}
                  </span>
                </div>
              </div>
            </div>
          )}

          {/* 3. Raw JSON */}
          {activeTab === "json" && (
            <div className="flex flex-col gap-2">
              <pre
                data-testid="handoff-json-view"
                className="p-3 bg-black/60 border border-white/10 rounded-xl text-xs font-mono text-emerald-300 overflow-x-auto whitespace-pre leading-relaxed"
              >
                {JSON.stringify(artifact, null, 2)}
              </pre>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
