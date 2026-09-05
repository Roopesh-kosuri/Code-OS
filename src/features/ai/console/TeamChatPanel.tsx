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
  type LucideIcon,
} from "lucide-react";
import { useTeamStore, type TeamMessage, type HandoffArtifact } from "./teamStore";
import { HandoffInspector } from "./HandoffInspector";

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

export const TeamChatPanel: React.FC = () => {
  const { teamMessages, injectPrompt, activeJobId, jobStatus, activeRepair } = useTeamStore();
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
      await injectPrompt(prompt.trim(), targetRole, isUrgent);
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
      <div className="p-3 border-b border-white/5 flex items-center justify-between bg-[#121216]">
        <div className="flex items-center gap-2">
          <MessageSquare size={15} className="text-primary-container" />
          <h3 className="text-xs font-bold uppercase tracking-wider text-on-surface">
            Team Comms Feed
          </h3>
          <span className="text-[10px] px-2 py-0.5 rounded-full bg-white/5 text-on-surface-variant font-mono">
            {filteredMessages.length} / {teamMessages.length}
          </span>
        </div>

        <div className="flex items-center gap-2">
          {/* Role Filter Selector */}
          <div className="flex items-center gap-1 bg-surface-container border border-white/10 rounded-lg px-2 py-1">
            <Filter size={11} className="text-on-surface-variant" />
            <select
              value={roleFilter}
              onChange={(e) => setRoleFilter(e.target.value)}
              data-testid="role-filter"
              className="bg-transparent text-[10px] font-mono text-on-surface focus:outline-none cursor-pointer"
              title="Filter messages by role"
            >
              <option value="all">All Roles</option>
              <option value="architect">Architect</option>
              <option value="coder">Coder</option>
              <option value="reviewer">Reviewer</option>
              <option value="tester">Tester</option>
              <option value="devops">DevOps</option>
              <option value="operator">Operator</option>
            </select>
          </div>

          {/* Auto-scroll toggle button */}
          <button
            onClick={() => setAutoScroll((prev) => !prev)}
            data-testid="autoscroll-toggle"
            className={`flex items-center gap-1 px-2 py-1 rounded-lg text-[10px] font-mono border transition-colors cursor-pointer ${
              autoScroll
                ? "bg-primary-container/20 text-primary-container border-primary-container/30"
                : "bg-white/5 text-on-surface-variant border-white/10 hover:text-on-surface"
            }`}
            title="Toggle automatic scrolling to latest message"
          >
            <ArrowDown size={11} className={autoScroll ? "animate-bounce" : "opacity-50"} />
            <span>Auto-scroll: {autoScroll ? "ON" : "OFF"}</span>
          </button>
        </div>
      </div>

      {/* Active Repair Warning Banner */}
      {activeRepair && (
        <div
          data-testid="repair-banner"
          className="mx-3 mt-2.5 p-2.5 rounded-lg bg-amber-500/15 border border-amber-500/30 text-amber-300 text-xs flex items-center justify-between shadow-sm animate-pulse"
        >
          <div className="flex items-center gap-2">
            <span className="text-sm">🔄</span>
            <span className="font-semibold">
              Repair Round {activeRepair.round}/{activeRepair.max_rounds}: Coder fixing {activeRepair.failures?.length || 1} test failure{(activeRepair.failures?.length || 1) === 1 ? "" : "s"}
            </span>
          </div>
          {activeRepair.failures && activeRepair.failures.length > 0 && (
            <span className="text-[10px] font-mono opacity-80 max-w-[200px] truncate">
              {activeRepair.failures[0]}
            </span>
          )}
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
                  className="rounded-xl p-3 text-xs flex flex-col gap-2 bg-[#141820] border border-blue-500/20 shadow-sm"
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
                        className="p-2.5 rounded-lg bg-black/40 border border-white/5 text-[11px] font-mono text-on-surface-variant leading-relaxed select-text"
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
                  className="rounded-xl p-3 text-xs flex flex-col gap-2 bg-gradient-to-br from-primary-container/10 via-surface-container to-surface-container border border-primary-container/30 hover:border-primary-container/60 hover:bg-primary-container/15 transition-all cursor-pointer group shadow-sm"
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
        className="p-3 border-t border-white/5 flex flex-col gap-2.5 bg-[#101014]"
      >
        <div className="flex items-center justify-between text-[11px] text-on-surface-variant font-mono">
          <div className="flex items-center gap-2">
            <span>Target:</span>
            <select
              value={targetRole}
              onChange={(e) => setTargetRole(e.target.value)}
              disabled={!activeJobId || jobStatus === "completed" || jobStatus === "cancelled"}
              data-testid="operator-target-select"
              className="bg-surface-container border border-white/10 rounded px-2 py-0.5 text-[10px] font-mono text-on-surface focus:outline-none focus:border-primary-container cursor-pointer"
            >
              <option value="all">@all (Broadcast to Entire Team)</option>
              <option value="architect">@architect</option>
              <option value="coder">@coder</option>
              <option value="reviewer">@reviewer</option>
              <option value="tester">@tester</option>
              <option value="devops">@devops</option>
            </select>
          </div>

          {/* Priority Toggle: Normal vs Urgent */}
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setIsUrgent((prev) => !prev)}
              data-testid="operator-urgent-toggle"
              className={`flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-mono border transition-all cursor-pointer ${
                isUrgent
                  ? "bg-rose-500/20 text-rose-400 border-rose-500/40 font-bold"
                  : "bg-white/5 text-on-surface-variant border-white/10 hover:text-on-surface"
              }`}
            >
              <Zap size={11} className={isUrgent ? "text-rose-400 fill-rose-400" : ""} />
              <span>Priority: {isUrgent ? "Urgent (Pause)" : "Normal"}</span>
            </button>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <input
            type="text"
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            disabled={!activeJobId || injecting || jobStatus === "completed" || jobStatus === "cancelled"}
            data-testid="operator-prompt-input"
            placeholder={
              activeJobId
                ? isUrgent
                  ? "Urgent instruction (will pause current cycle)..."
                  : "Inject directive into running team..."
                : "Launch a team workflow to inject directives..."
            }
            className="flex-1 bg-surface-container border border-white/10 rounded-lg px-3 py-2 text-xs text-on-surface placeholder:text-on-surface-variant/40 focus:outline-none focus:border-primary-container font-mono disabled:opacity-50"
          />
          <button
            type="submit"
            disabled={!prompt.trim() || !activeJobId || injecting}
            data-testid="operator-submit-btn"
            className={`p-2 rounded-lg font-mono text-xs flex items-center gap-1.5 transition-all cursor-pointer disabled:opacity-40 ${
              isUrgent
                ? "bg-rose-500 text-white hover:bg-rose-600"
                : "bg-primary-container text-on-primary-container hover:opacity-90"
            }`}
            title="Inject Directive"
          >
            <Send size={13} />
            <span className="hidden sm:inline">Inject</span>
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
