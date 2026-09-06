import React, { useState, useRef, useEffect } from "react";
import {
  MessageSquare,
  Send,
  Sparkles,
  Bot,
  ArrowRight,
  ShieldCheck,
  Terminal,
  Layers,
  FlaskConical,
  Server,
  ChevronDown,
  ChevronRight,
  FileCode,
  AlertTriangle,
  CheckCircle2,
  XCircle,
  Clock,
  Filter,
  ArrowDown,
  Zap,
  Check,
  X,
  Database,
  Paperclip,
  Brain,
  type LucideIcon,
} from "lucide-react";
import { useTeamStore, type TeamMessage, type HandoffArtifact } from "./teamStore";
import { HandoffInspector } from "./HandoffInspector";
import { useRAGStore } from "../../rag/ragStore";
import { useWorkspaceStore } from "../../../stores/workspaceStore";
import { useFileUploadStore } from "../../files/fileUploadStore";
import { useMemoryStore } from "../../memory/memoryStore";

const ROLE_ICONS: Record<string, LucideIcon> = {
  architect: Layers,
  coder: Terminal,
  reviewer: ShieldCheck,
  tester: FlaskConical,
  devops: Server,
  operator: Bot,
  system: Sparkles,
};

const ROLE_BADGE_CLASSES: Record<string, string> = {
  architect: "bg-blue-500/20 text-blue-400 border-blue-500/30",
  coder: "bg-emerald-500/20 text-emerald-400 border-emerald-500/30",
  reviewer: "bg-amber-500/20 text-amber-400 border-amber-500/30",
  tester: "bg-purple-500/20 text-purple-400 border-purple-500/30",
  devops: "bg-rose-500/20 text-rose-400 border-rose-500/30",
  operator: "bg-yellow-500/20 text-yellow-300 border-yellow-500/40",
  system: "bg-zinc-500/20 text-zinc-400 border-zinc-500/30",
};

interface RoleFilterDropdownProps {
  value: string;
  onChange: (val: string) => void;
}

const ROLE_FILTER_OPTIONS = [
  { value: "all", label: "All Roles", dot: "bg-zinc-400" },
  { value: "architect", label: "Architect", dot: "bg-blue-400" },
  { value: "coder", label: "Coder", dot: "bg-emerald-400" },
  { value: "reviewer", label: "Reviewer", dot: "bg-amber-400" },
  { value: "tester", label: "Tester", dot: "bg-purple-400" },
  { value: "devops", label: "DevOps", dot: "bg-rose-400" },
  { value: "operator", label: "Operator", dot: "bg-yellow-300" },
];

const RoleFilterDropdown: React.FC<RoleFilterDropdownProps> = ({ value, onChange }) => {
  const [isOpen, setIsOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setIsOpen(false);
      }
    };
    if (isOpen) {
      document.addEventListener("mousedown", handleClickOutside);
    }
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
    };
  }, [isOpen]);

  const currentOption =
    ROLE_FILTER_OPTIONS.find((opt) => opt.value.toLowerCase() === value.toLowerCase()) ||
    ROLE_FILTER_OPTIONS[0];

  return (
    <div ref={containerRef} className="relative shrink-0">
      {/* Hidden native select for test automation & accessibility */}
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        data-testid="role-filter"
        className="sr-only"
        tabIndex={-1}
        aria-hidden="true"
      >
        {ROLE_FILTER_OPTIONS.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>

      <button
        type="button"
        data-testid="role-filter-button"
        onClick={() => setIsOpen(!isOpen)}
        className="flex items-center gap-1.5 bg-surface-container hover:bg-surface-container-high border border-white/10 hover:border-white/20 rounded-lg px-2.5 py-1 text-[10px] font-mono text-on-surface transition-all cursor-pointer shadow-xs"
      >
        <Filter size={10} className="text-on-surface-variant shrink-0" />
        <span className="flex items-center gap-1">
          <span className={`w-1.5 h-1.5 rounded-full ${currentOption.dot} shrink-0`} />
          <span className="whitespace-nowrap">{currentOption.label}</span>
        </span>
        <ChevronDown
          size={10}
          className={`text-on-surface-variant shrink-0 transition-transform ${isOpen ? "rotate-180" : ""}`}
        />
      </button>

      {isOpen && (
        <div className="absolute right-0 top-full mt-1 w-36 bg-[#16171b] border border-white/15 rounded-xl shadow-2xl p-1 z-50 flex flex-col gap-0.5 backdrop-blur-md animate-in fade-in zoom-in-95 duration-100">
          {ROLE_FILTER_OPTIONS.map((opt) => {
            const isSelected = opt.value.toLowerCase() === value.toLowerCase();
            return (
              <button
                key={opt.value}
                type="button"
                onClick={() => {
                  onChange(opt.value);
                  setIsOpen(false);
                }}
                className={`flex items-center justify-between px-2 py-1.5 rounded-lg text-[11px] font-mono transition-colors text-left cursor-pointer ${
                  isSelected
                    ? "bg-primary-container/20 text-primary-container font-semibold"
                    : "text-on-surface-variant hover:text-on-surface hover:bg-white/5"
                }`}
              >
                <div className="flex items-center gap-1.5 truncate">
                  <span className={`w-1.5 h-1.5 rounded-full ${opt.dot} shrink-0`} />
                  <span className="truncate">{opt.label}</span>
                </div>
                {isSelected && <Check size={11} className="text-primary-container shrink-0 ml-1" />}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
};

interface TargetRoleDropdownProps {
  value: string;
  onChange: (val: string) => void;
  disabled?: boolean;
}

const TARGET_ROLE_OPTIONS = [
  { value: "all", label: "@all (Broadcast to Entire Team)", shortLabel: "@all (Team)", dot: "bg-zinc-400" },
  { value: "architect", label: "@architect", shortLabel: "@architect", dot: "bg-blue-400" },
  { value: "coder", label: "@coder", shortLabel: "@coder", dot: "bg-emerald-400" },
  { value: "reviewer", label: "@reviewer", shortLabel: "@reviewer", dot: "bg-amber-400" },
  { value: "tester", label: "@tester", shortLabel: "@tester", dot: "bg-purple-400" },
  { value: "devops", label: "@devops", shortLabel: "@devops", dot: "bg-rose-400" },
];

const TargetRoleDropdown: React.FC<TargetRoleDropdownProps> = ({ value, onChange, disabled }) => {
  const [isOpen, setIsOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setIsOpen(false);
      }
    };
    if (isOpen) {
      document.addEventListener("mousedown", handleClickOutside);
    }
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
    };
  }, [isOpen]);

  const currentOption =
    TARGET_ROLE_OPTIONS.find((opt) => opt.value.toLowerCase() === value.toLowerCase()) ||
    TARGET_ROLE_OPTIONS[0];

  return (
    <div ref={containerRef} className="relative flex-1 min-w-0">
      {/* Hidden native select for test automation & accessibility */}
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
        data-testid="operator-target-select"
        className="sr-only"
        tabIndex={-1}
        aria-hidden="true"
      >
        {TARGET_ROLE_OPTIONS.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>

      <button
        type="button"
        disabled={disabled}
        onClick={() => setIsOpen(!isOpen)}
        className="w-full flex items-center justify-between gap-1.5 bg-surface-container hover:bg-surface-container-high border border-white/10 hover:border-white/20 rounded-lg px-2.5 py-1.5 text-[11px] font-mono text-on-surface transition-all cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed shadow-xs"
        title="Select directive recipient role"
      >
        <div className="flex items-center gap-1.5 truncate">
          <span className={`w-1.5 h-1.5 rounded-full ${currentOption.dot} shrink-0`} />
          <span className="truncate text-on-surface">{currentOption.shortLabel || currentOption.label}</span>
        </div>
        <ChevronDown
          size={11}
          className={`text-on-surface-variant shrink-0 transition-transform ${isOpen ? "rotate-180" : ""}`}
        />
      </button>

      {isOpen && !disabled && (
        <div className="absolute left-0 bottom-full mb-1 min-w-[210px] w-full bg-[#16171b] border border-white/15 rounded-xl shadow-2xl p-1 z-50 flex flex-col gap-0.5 backdrop-blur-md animate-in fade-in zoom-in-95 duration-100">
          {TARGET_ROLE_OPTIONS.map((opt) => {
            const isSelected = opt.value.toLowerCase() === value.toLowerCase();
            return (
              <button
                key={opt.value}
                type="button"
                onClick={() => {
                  onChange(opt.value);
                  setIsOpen(false);
                }}
                className={`flex items-center justify-between px-2.5 py-1.5 rounded-lg text-[11px] font-mono transition-colors text-left cursor-pointer ${
                  isSelected
                    ? "bg-primary-container/20 text-primary-container font-semibold"
                    : "text-on-surface-variant hover:text-on-surface hover:bg-white/5"
                }`}
              >
                <div className="flex items-center gap-2 truncate">
                  <span className={`w-1.5 h-1.5 rounded-full ${opt.dot} shrink-0`} />
                  <span className="truncate">{opt.label}</span>
                </div>
                {isSelected && <Check size={11} className="text-primary-container shrink-0 ml-1" />}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
};

export const TeamChatPanel: React.FC = () => {
  const { teamMessages, injectPrompt, activeJobId, jobStatus, activeRepair } = useTeamStore();
  const { uploadedFiles, openPreview } = useFileUploadStore();
  const { useRagInChat, toggleUseRagInChat, indexStatus } = useRAGStore();
  const currentWorkspace = useWorkspaceStore((state) => state?.currentWorkspace);
  const memories = useMemoryStore((state) => state.memories);
  const [prompt, setPrompt] = useState("");
  const [targetRole, setTargetRole] = useState<string>("all");
  const [isUrgent, setIsUrgent] = useState(false);
  const [injecting, setInjecting] = useState(false);

  // Filters & Toggles
  const [roleFilter, setRoleFilter] = useState<string>("all");
  const [autoScroll, setAutoScroll] = useState(true);

  // Expanded rationales for decision messages: id -> boolean
  const [expandedDecisions, setExpandedDecisions] = useState<Record<string | number, boolean>>({});

  // Approvals status map: message_id -> 'approved' | 'rejected'
  const [approvalStatuses, setApprovalStatuses] = useState<Record<string | number, string>>({});

  // Active handoff inspector modal state
  const [inspectedHandoff, setInspectedHandoff] = useState<HandoffArtifact | null>(null);

  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Auto-scroll handler
  useEffect(() => {
    if (autoScroll) {
      messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [teamMessages, autoScroll]);

  const toggleDecision = (id: string | number) => {
    setExpandedDecisions((prev) => ({ ...prev, [id]: !prev[id] }));
  };

  const handleApprove = (id: string | number) => {
    setApprovalStatuses((prev) => ({ ...prev, [id]: "approved" }));
  };

  const handleReject = (id: string | number) => {
    setApprovalStatuses((prev) => ({ ...prev, [id]: "rejected" }));
  };

  const handleInject = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!prompt.trim() || !activeJobId) return;

    setInjecting(true);
    try {
      let finalPrompt = prompt.trim();
      if (useRagInChat && currentWorkspace?.path) {
        try {
          const results = await useRAGStore.getState().search(currentWorkspace.path, prompt.trim(), 5);
          if (results && results.length > 0) {
            const contextText = results
              .map((r) => `--- ${r.file_path} (${r.line_range}) ---\n${r.chunk_text}`)
              .join("\n\n");
            finalPrompt = `${prompt.trim()}\n\nRelevant files from codebase:\n${contextText}`;
          }
        } catch {
          // If RAG search fails, proceed with base prompt
        }
      }
      await injectPrompt(finalPrompt, targetRole, isUrgent);
      setPrompt("");
      setIsUrgent(false);
    } catch {
      // Handled by store
    } finally {
      setInjecting(false);
    }
  };

  // Filter messages by role if filter is active
  const filteredMessages = teamMessages.filter((msg) => {
    if (roleFilter === "all") return true;
    return (
      msg.sender_role?.toLowerCase() === roleFilter.toLowerCase() ||
      msg.recipient_role?.toLowerCase() === roleFilter.toLowerCase()
    );
  });

  return (
    <div
      data-testid="team-chat-panel"
      className="flex flex-col h-full bg-surface-container-low rounded-xl border border-white/5 overflow-hidden select-none"
    >
      {/* Header */}
      <div className="p-2.5 px-3 border-b border-white/5 flex flex-col gap-2 bg-surface-container-lowest shrink-0">
        {/* Row 1: Title, Count, Auto-scroll */}
        <div className="flex items-center justify-between gap-2 min-w-0">
          <div className="flex items-center gap-2 min-w-0">
            <MessageSquare size={14} className="text-primary-container shrink-0" />
            <h3 className="text-xs font-bold uppercase tracking-wider text-on-surface whitespace-nowrap">
              Team Comms
            </h3>
            <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-surface-container text-on-surface-variant font-mono whitespace-nowrap">
              {filteredMessages.length} / {teamMessages.length}
            </span>
            {memories.length > 0 && (
              <div
                data-testid="team-chat-memory-indicator"
                className="flex items-center gap-1 px-1.5 py-0.5 rounded-full bg-cyan-950/60 border border-cyan-800/60 text-[10px] font-mono text-cyan-300 whitespace-nowrap"
                title={`${memories.length} lessons learned from past mistakes active in agent context`}
              >
                <Brain size={10} className="text-cyan-400 shrink-0" />
                <span>{memories.length} memory</span>
              </div>
            )}
          </div>

          {/* Auto-scroll toggle button */}
          <button
            onClick={() => setAutoScroll((prev) => !prev)}
            data-testid="autoscroll-toggle"
            className={`flex items-center gap-1.5 px-2 py-1 rounded-lg text-[10px] font-mono border transition-colors cursor-pointer shrink-0 whitespace-nowrap ${
              autoScroll
                ? "bg-primary-container/20 text-primary-container border-primary-container/30"
                : "bg-surface-container text-on-surface-variant border-white/10 hover:text-on-surface"
            }`}
          >
            <ArrowDown size={11} className={autoScroll ? "animate-bounce text-primary-container" : "opacity-50"} />
            <span>Auto-scroll: {autoScroll ? "ON" : "OFF"}</span>
          </button>
        </div>

        {/* Row 2: Role Filter selector */}
        <div className="flex items-center justify-between gap-2 pt-1.5 border-t border-white/5 min-w-0">
          <span className="text-[10px] font-mono text-on-surface-variant flex items-center gap-1.5 shrink-0">
            <Filter size={10} className="text-on-surface-variant/80" />
            <span>Feed Role:</span>
          </span>
          <RoleFilterDropdown value={roleFilter} onChange={setRoleFilter} />
        </div>
      </div>

      {/* Active Repair Warning Banner */}
      {activeRepair && (
        <div className="px-3 pt-2.5 shrink-0 bg-surface-container-low">
          <div
            data-testid="repair-banner"
            className="p-2.5 rounded-lg bg-amber-500/15 border border-amber-500/30 text-amber-300 text-xs flex items-center justify-between shadow-sm animate-pulse"
          >
            <div className="flex items-center gap-2 min-w-0">
              <span className="text-sm shrink-0">🔄</span>
              <span className="font-semibold truncate">
                Repair Round {activeRepair.round}/{activeRepair.max_rounds}: Coder fixing {activeRepair.failures?.length || 1} test failure{(activeRepair.failures?.length || 1) === 1 ? "" : "s"}
              </span>
            </div>
            {activeRepair.failures && activeRepair.failures.length > 0 && (
              <span className="text-[10px] font-mono opacity-80 max-w-[200px] truncate shrink-0">
                {activeRepair.failures[0]}
              </span>
            )}
          </div>
        </div>
      )}

      {/* Attached Files Bar in Team Chat Feed */}
      {uploadedFiles.length > 0 && (
        <div className="px-3 pt-2 shrink-0">
          <button
            type="button"
            data-testid="team-attached-files-bar"
            onClick={() => {
              if (uploadedFiles[0]) void openPreview(uploadedFiles[0]);
            }}
            className="w-full flex items-center justify-between p-2 rounded-lg bg-surface-container border border-white/10 hover:border-primary/40 text-xs text-on-surface transition-colors cursor-pointer shadow-xs"
            title="View attached files in this job"
          >
            <div className="flex items-center gap-2 truncate min-w-0">
              <Paperclip size={13} className="text-primary-container shrink-0" />
              <span className="font-semibold text-[11px] truncate shrink-0">
                Attached Files ({uploadedFiles.length})
              </span>
              <div className="flex items-center gap-1 truncate">
                {uploadedFiles.slice(0, 3).map((f) => (
                  <span
                    key={f.file_id}
                    className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-surface-variant text-on-surface-variant truncate max-w-[90px]"
                  >
                    {f.filename}
                  </span>
                ))}
              </div>
            </div>
            <span className="text-[10px] text-primary-container font-mono shrink-0 ml-2">
              View All
            </span>
          </button>
        </div>
      )}

      {/* Messages Feed */}
      <div className="flex-1 overflow-y-auto p-3 flex flex-col gap-2.5">
        {filteredMessages.length === 0 ? (
          <div className="h-full flex flex-col items-center justify-center text-center text-on-surface-variant/50 p-6 gap-2">
            <MessageSquare size={28} className="opacity-30" />
            <p className="text-xs">No communications to display.</p>
            <p className="text-[11px] text-on-surface-variant/40 max-w-xs">
              {roleFilter !== "all"
                ? `No messages found for role '${roleFilter}'. Switch filter to All Roles to view full feed.`
                : "Real-time inter-agent decisions, code handoffs, and verification reports will appear here."}
            </p>
          </div>
        ) : (
          filteredMessages.map((msg, i) => {
            const msgId = msg.id || i;
            const sender = (msg.sender_role || "system").toLowerCase();
            const recipient = (msg.recipient_role || "all").toLowerCase();
            const Icon = ROLE_ICONS[sender] || Bot;
            const badgeClass =
              ROLE_BADGE_CLASSES[sender] || "bg-zinc-500/20 text-zinc-400 border-zinc-500/30";
            const mType = msg.message_type || "chat";

            // 1. System Centered Notice
            if (mType === "system" || sender === "system") {
              return (
                <div
                  key={msgId}
                  data-testid="system-message"
                  className="flex items-center justify-center my-1"
                >
                  <div className="flex items-center gap-1.5 px-3 py-1 rounded-full bg-white/5 border border-white/5 text-[10px] font-mono text-on-surface-variant max-w-md text-center">
                    <Sparkles size={11} className="text-on-surface-variant shrink-0" />
                    <span>{msg.content}</span>
                  </div>
                </div>
              );
            }

            // 2. Decision Message with Expandable Rationale
            if (mType === "decision") {
              const isExpanded = Boolean(expandedDecisions[msgId]);
              const rationaleText =
                msg.details?.rationale ||
                (msg.artifact && typeof msg.artifact === "object" ? msg.artifact.rationale : "") ||
                "Architectural rationale: Optimized module dependency tree for deterministic builds and zero circular imports.";

              return (
                <div
                  key={msgId}
                  data-testid="decision-message"
                  className="rounded-xl p-3 text-xs flex flex-col gap-2 bg-surface-container border border-blue-500/20 shadow-sm"
                >
                  <div className="flex items-center justify-between text-[10px] font-mono">
                    <div className="flex items-center gap-1.5">
                      <span
                        data-testid={`badge-${sender}`}
                        className={`flex items-center gap-1 px-2 py-0.5 rounded-full border font-bold ${badgeClass}`}
                      >
                        <Icon size={11} />
                        @{sender}
                      </span>
                      {recipient !== "all" && (
                        <>
                          <ArrowRight size={10} className="text-on-surface-variant/40" />
                          <span className="text-on-surface-variant">@{recipient}</span>
                        </>
                      )}
                    </div>
                    <span className="text-[9px] uppercase px-1.5 py-0.5 rounded bg-blue-500/10 text-blue-400 border border-blue-500/20 font-bold">
                      Decision
                    </span>
                  </div>

                  <p className="text-on-surface leading-relaxed text-xs font-medium select-text">
                    {msg.content}
                  </p>

                  <div className="border-t border-white/5 pt-2 flex flex-col gap-1.5">
                    <button
                      onClick={() => toggleDecision(msgId)}
                      data-testid="decision-toggle"
                      className="flex items-center gap-1 text-[11px] font-mono text-blue-400 hover:text-blue-300 transition-colors cursor-pointer w-fit"
                    >
                      {isExpanded ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
                      <span>{isExpanded ? "Collapse Rationale" : "Expand Rationale"}</span>
                    </button>

                    {isExpanded && (
                      <div
                        data-testid="decision-rationale"
                        className="p-2.5 rounded-lg bg-surface-container-lowest border border-white/5 text-[11px] font-mono text-on-surface-variant leading-relaxed select-text"
                      >
                        {rationaleText}
                      </div>
                    )}
                  </div>
                </div>
              );
            }

            // 3. Handoff Clickable Card -> Opens Modal
            if (mType === "handoff" || msg.artifact) {
              const handoffData: HandoffArtifact = msg.artifact || {
                type: "diffs",
                from_role: sender,
                to_role: recipient,
                summary: msg.content,
                payload: msg.details || {},
                created_at: msg.timestamp,
              };

              return (
                <div
                  key={msgId}
                  onClick={() => setInspectedHandoff(handoffData)}
                  data-testid="handoff-card"
                  role="button"
                  tabIndex={0}
                  className="rounded-xl p-3 text-xs flex flex-col gap-2 bg-surface-container border border-primary-container/30 hover:border-primary-container/60 hover:bg-surface-container-high transition-all cursor-pointer group shadow-sm"
                >
                  <div className="flex items-center justify-between text-[10px] font-mono">
                    <div className="flex items-center gap-1.5">
                      <span
                        data-testid={`badge-${sender}`}
                        className={`flex items-center gap-1 px-2 py-0.5 rounded-full border font-bold ${badgeClass}`}
                      >
                        <Icon size={11} />
                        @{sender}
                      </span>
                      <ArrowRight size={10} className="text-primary-container" />
                      <span className="text-on-surface-variant">@{recipient}</span>
                    </div>

                    <span className="flex items-center gap-1 text-[9px] uppercase font-mono px-2 py-0.5 rounded bg-primary-container/20 text-primary-container border border-primary-container/30 font-bold group-hover:bg-primary-container group-hover:text-on-primary-container transition-colors">
                      <FileCode size={10} />
                      Inspect Artifact
                    </span>
                  </div>

                  <div className="flex items-start justify-between gap-2">
                    <p className="text-on-surface font-mono text-xs leading-relaxed select-text">
                      {msg.content}
                    </p>
                  </div>

                  <div className="flex items-center gap-2 text-[10px] text-on-surface-variant font-mono">
                    <span className="px-1.5 py-0.2 rounded bg-white/5 border border-white/5">
                      Type: {handoffData.type || "files"}
                    </span>
                    <span>Click card to inspect full diff & verify</span>
                  </div>
                </div>
              );
            }

            // 4. Approval Request Block
            if (mType === "approval_request") {
              const status = approvalStatuses[msgId];

              return (
                <div
                  key={msgId}
                  data-testid="approval-request-message"
                  className="rounded-xl p-3 text-xs flex flex-col gap-2 bg-amber-500/10 border border-amber-500/30 shadow-sm"
                >
                  <div className="flex items-center justify-between text-[10px] font-mono">
                    <div className="flex items-center gap-1.5">
                      <span
                        data-testid={`badge-${sender}`}
                        className={`flex items-center gap-1 px-2 py-0.5 rounded-full border font-bold ${badgeClass}`}
                      >
                        <Icon size={11} />
                        @{sender}
                      </span>
                    </div>
                    <span className="text-[9px] uppercase font-bold px-2 py-0.5 rounded bg-amber-500/20 text-amber-300 border border-amber-500/30">
                      Approval Request
                    </span>
                  </div>

                  <p className="text-on-surface font-mono text-xs select-text">{msg.content}</p>

                  <div className="flex items-center gap-2 pt-1 border-t border-white/5">
                    {status === "approved" ? (
                      <span className="flex items-center gap-1 text-xs font-mono text-emerald-400 font-bold">
                        <CheckCircle2 size={13} /> Approved by Operator
                      </span>
                    ) : status === "rejected" ? (
                      <span className="flex items-center gap-1 text-xs font-mono text-rose-400 font-bold">
                        <XCircle size={13} /> Rejected by Operator
                      </span>
                    ) : (
                      <>
                        <button
                          onClick={() => handleApprove(msgId)}
                          data-testid="approve-btn"
                          className="flex items-center gap-1 px-3 py-1 rounded-lg bg-emerald-500/20 text-emerald-400 hover:bg-emerald-500/30 border border-emerald-500/30 text-xs font-mono font-medium transition-colors cursor-pointer"
                        >
                          <Check size={12} /> Approve
                        </button>
                        <button
                          onClick={() => handleReject(msgId)}
                          data-testid="reject-btn"
                          className="flex items-center gap-1 px-3 py-1 rounded-lg bg-rose-500/20 text-rose-400 hover:bg-rose-500/30 border border-rose-500/30 text-xs font-mono font-medium transition-colors cursor-pointer"
                        >
                          <X size={12} /> Reject
                        </button>
                      </>
                    )}
                  </div>
                </div>
              );
            }

            // 5. Repair Request / Warning Block
            if (mType === "repair_request" || mType === "repair") {
              return (
                <div
                  key={msgId}
                  data-testid="repair-request-message"
                  className="rounded-xl p-3 text-xs flex flex-col gap-2 bg-rose-500/10 border border-rose-500/30 shadow-sm"
                >
                  <div className="flex items-center justify-between text-[10px] font-mono">
                    <div className="flex items-center gap-1.5 font-bold text-rose-400">
                      <AlertTriangle size={13} />
                      <span>AUTONOMOUS REPAIR REQUIRED</span>
                    </div>
                    <span className="text-[9px] uppercase font-bold px-1.5 py-0.5 rounded bg-rose-500/20 text-rose-300">
                      Fix Target
                    </span>
                  </div>

                  <p className="text-on-surface font-mono text-xs leading-relaxed select-text">
                    {msg.content}
                  </p>
                </div>
              );
            }

            // 6. Operator Injection or Standard Chat Message
            const isOperator = sender === "operator" || mType === "injection";
            const isAcknowledged = Boolean(msg.acknowledged) || msg.content.includes("Acknowledged by");

            return (
              <div
                key={msgId}
                data-testid={isOperator ? "operator-message" : "chat-message"}
                className={`rounded-xl p-3 text-xs flex flex-col gap-1.5 border shadow-sm transition-all ${
                  isOperator
                    ? "bg-yellow-500/10 border-yellow-500/30"
                    : isAcknowledged
                    ? "bg-emerald-500/5 border-emerald-500/20"
                    : "bg-surface-container border-white/5"
                }`}
              >
                <div className="flex items-center justify-between text-[10px] font-mono text-on-surface-variant">
                  <div className="flex items-center gap-1.5">
                    <span
                      data-testid={`badge-${sender}`}
                      className={`flex items-center gap-1 px-2 py-0.5 rounded-full border font-bold ${badgeClass}`}
                    >
                      <Icon size={11} />
                      @{sender}
                    </span>
                    {recipient && recipient !== "all" && (
                      <>
                        <ArrowRight size={10} className="text-on-surface-variant/40" />
                        <span className="text-on-surface-variant lowercase">@{recipient}</span>
                      </>
                    )}
                  </div>

                  <div className="flex items-center gap-1.5">
                    {msg.details?.urgent && (
                      <span className="flex items-center gap-0.5 px-1.5 py-0.5 rounded bg-rose-500/20 text-rose-400 border border-rose-500/30 text-[9px] font-mono font-bold uppercase">
                        <Zap size={9} /> Urgent
                      </span>
                    )}
                    {isAcknowledged && (
                      <span className="flex items-center gap-0.5 px-1.5 py-0.5 rounded bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 text-[9px] font-mono font-bold">
                        <Check size={9} /> Acknowledged
                      </span>
                    )}
                    <span className="text-[9px] uppercase px-1.5 py-0.2 rounded bg-white/5 font-mono">
                      {mType}
                    </span>
                  </div>
                </div>

                <p className="text-on-surface leading-relaxed text-xs font-ui-label-reg select-text">
                  {msg.content}
                </p>
              </div>
            );
          })
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Operator Prompt Injection Input (B4.3) */}
      <form
        onSubmit={handleInject}
        data-testid="operator-injection-form"
        className="p-3 border-t border-white/5 flex flex-col gap-2 bg-surface-container-lowest shrink-0"
      >
        {/* Row 1: Target Selector (Left) + RAG Toggle (Right) */}
        <div className="flex items-center justify-between gap-2 text-[11px] text-on-surface-variant font-mono min-w-0">
          <div className="flex items-center gap-1.5 flex-1 min-w-0">
            <span className="shrink-0 text-on-surface-variant font-medium text-[10px]">Target:</span>
            <TargetRoleDropdown
              value={targetRole}
              onChange={setTargetRole}
              disabled={!activeJobId || jobStatus === "completed" || jobStatus === "cancelled"}
            />
          </div>

          <button
            type="button"
            onClick={toggleUseRagInChat}
            data-testid="rag-chat-toggle"
            className={`flex items-center gap-1.5 px-2 py-1 rounded-lg text-[10px] font-mono border transition-all cursor-pointer shrink-0 ${
              useRagInChat
                ? "bg-primary-container/20 text-primary border-primary/30 font-semibold shadow-xs"
                : "bg-surface-container text-on-surface-variant border-white/10 hover:text-on-surface"
            }`}
            title="Toggle Semantic RAG codebase context"
          >
            <Database size={11} className={useRagInChat ? "text-primary fill-primary/20" : ""} />
            <span>RAG: {useRagInChat ? "ON" : "OFF"}</span>
          </button>
        </div>

        {/* Row 2: RAG Context Status Strip (when RAG is active) */}
        {useRagInChat && (
          <div
            data-testid="rag-context-badge"
            className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-primary-container/15 text-primary border border-primary-container/25 text-[10px] font-mono min-w-0 shadow-xs"
            title="Semantic RAG is providing relevant codebase snippets to agents"
          >
            <Database size={10} className="shrink-0 text-primary" />
            <span className="truncate">
              Using {indexStatus.indexed_files > 0 ? Math.min(5, indexStatus.indexed_files) : 5} relevant files from codebase
            </span>
          </div>
        )}

        {/* Row 2: Priority Toggle + Prompt Input + Inject Button */}
        <div className="flex items-center gap-2 min-w-0">
          {/* Priority Toggle: Normal vs Urgent */}
          <button
            type="button"
            onClick={() => setIsUrgent((prev) => !prev)}
            data-testid="operator-urgent-toggle"
            className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-[10px] font-mono border transition-all cursor-pointer shrink-0 whitespace-nowrap ${
              isUrgent
                ? "bg-rose-500/20 text-rose-400 border-rose-500/40 font-bold shadow-sm"
                : "bg-surface-container text-on-surface-variant border-white/10 hover:text-on-surface"
            }`}
            title="Toggle priority (Urgent pauses running cycles)"
          >
            <Zap size={11} className={isUrgent ? "text-rose-400 fill-rose-400" : ""} />
            <span>{isUrgent ? "⚡ Urgent (Pause)" : "Normal"}</span>
          </button>

          {/* Prompt Input */}
          <input
            type="text"
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            disabled={!activeJobId || injecting || jobStatus === "completed" || jobStatus === "cancelled"}
            data-testid="operator-prompt-input"
            placeholder={
              activeJobId
                ? isUrgent
                  ? "Urgent instruction (pauses)..."
                  : "Direct team or inject..."
                : "Enter steering directive..."
            }
            className="flex-1 min-w-0 bg-surface-container border border-white/10 rounded-lg px-2.5 py-1.5 text-xs text-on-surface placeholder:text-on-surface-variant/40 focus:outline-none focus:border-primary-container font-mono disabled:opacity-50"
          />

          {/* Inject Button */}
          <button
            type="submit"
            disabled={!prompt.trim() || !activeJobId || injecting}
            data-testid="operator-submit-btn"
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg font-ui-label-bold text-xs transition-all cursor-pointer disabled:opacity-40 shrink-0 whitespace-nowrap ${
              isUrgent
                ? "bg-rose-500 text-white hover:bg-rose-600 shadow-sm"
                : "bg-primary-container text-on-primary-container hover:opacity-90 shadow-sm"
            }`}
            title="Inject Directive"
          >
            <Send size={12} />
            <span>Inject</span>
          </button>
        </div>
      </form>

      {/* Handoff Inspector Modal */}
      <HandoffInspector
        artifact={inspectedHandoff}
        isOpen={Boolean(inspectedHandoff)}
        onClose={() => setInspectedHandoff(null)}
      />
    </div>
  );
};
