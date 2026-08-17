import React, { useState, useEffect } from "react";
import {
  Bot,
  ChevronDown,
  Loader2,
  Terminal,
  FileCode,
  Search,
  CheckCircle2,
  Circle,
  AlertCircle,
  ShieldAlert,
  Sparkles,
  RefreshCw,
  ListChecks,
  BookmarkCheck,
  Check,
  Zap,
  Brain,
  Layers,
  Ban,
  HelpCircle,
} from "lucide-react";
import {
  useAIStore,
  type AgentStatus,
  type AgentPlan,
  type ToolEvent,
  type DAGPlanStep,
} from "../../stores/aiStore";

interface AgentStatusIndicatorProps {
  status: AgentStatus | null;
  plan: AgentPlan | null;
  toolHistory: ToolEvent[];
  streaming?: boolean;
}

export function AgentStatusIndicator({
  status,
  plan,
  toolHistory,
  streaming = false,
}: AgentStatusIndicatorProps) {
  const [expanded, setExpanded] = useState(false);
  const pendingApproval = useAIStore((s) => s.pendingApproval);
  const currentTier = useAIStore((s) => s.currentTier);
  const currentTierLabel = useAIStore((s) => s.currentTierLabel);

  // Auto-expand when user approval or replanning occurs
  useEffect(() => {
    if (pendingApproval || status?.type === "approval_required" || status?.type === "replan") {
      setExpanded(true);
    }
  }, [pendingApproval, status?.type]);

  if (!status && (!plan || plan.steps.length === 0) && toolHistory.length === 0 && !pendingApproval) {
    return null;
  }

  // Derive display icon and label based on status type
  const getStatusDisplay = () => {
    if (pendingApproval || status?.type === "approval_required") {
      const isEdit = pendingApproval?.action_type === "edit";
      return {
        icon: isEdit ? (
          <FileCode size={14} className="text-primary animate-pulse" />
        ) : (
          <ShieldAlert size={14} className="text-amber-400 animate-pulse" />
        ),
        text: isEdit ? "Awaiting edit approval..." : "Awaiting approval...",
        colorClass: isEdit
          ? "border-primary/40 bg-primary/10 text-primary"
          : "border-amber-500/40 bg-amber-500/10 text-amber-300",
      };
    }

    if (!status) {
      return {
        icon: <Loader2 size={13} className="animate-spin text-primary" />,
        text: "Reasoning...",
        colorClass: "border-primary/30 bg-primary/10 text-primary",
      };
    }

    switch (status.type) {
      case "tier_routing":
        return {
          icon: status.tier === 2 ? <Brain size={13} className="text-purple-400" /> : <Zap size={13} className="text-emerald-400" />,
          text: status.message || `Routing: ${status.label || "Adaptive path"}`,
          colorClass: status.tier === 2 ? "border-purple-500/30 bg-purple-500/10 text-purple-300" : "border-emerald-500/30 bg-emerald-500/10 text-emerald-300",
        };
      case "memory_updated":
        return {
          icon: <BookmarkCheck size={13} className="text-cyan-400" />,
          text: status.message || "Saved to project memory (RONY.md)",
          colorClass: "border-cyan-500/30 bg-cyan-500/10 text-cyan-300",
        };
      case "verified_disk":
        return {
          icon: <CheckCircle2 size={13} className="text-emerald-400" />,
          text: status.message || "Post-apply read-back confirmed on disk",
          colorClass: "border-emerald-500/30 bg-emerald-500/10 text-emerald-300",
        };
      case "self_critique":
        return {
          icon: <Sparkles size={13} className="text-primary" />,
          text: status.message || "Running self-critique pass...",
          colorClass: "border-primary/30 bg-primary/10 text-primary",
        };
      case "replan":
        return {
          icon: <RefreshCw size={13} className="animate-spin text-amber-400" />,
          text: status.message || "Re-planning step...",
          colorClass: "border-amber-500/30 bg-amber-500/10 text-amber-300",
        };
      case "tool_skipped":
        return {
          icon: <Ban size={13} className="text-amber-400" />,
          text: status.message || "Skipped repeated failure",
          colorClass: "border-amber-500/30 bg-amber-500/10 text-amber-300",
        };
      case "thinking":
        return {
          icon: <Loader2 size={13} className="animate-spin text-primary" />,
          text: status.message || "Reasoning...",
          colorClass: "border-primary/30 bg-primary/10 text-primary",
        };
      case "tool": {
        let toolIcon = <Terminal size={13} className="text-secondary" />;
        if (status.tool === "read_file" || status.tool === "edit_file" || status.tool === "append_file") {
          toolIcon = <FileCode size={13} className="text-amber-400" />;
        } else if (status.tool === "search_code" || status.tool === "semantic_search") {
          toolIcon = <Search size={13} className="text-cyan-400" />;
        } else if (status.tool === "memory_write") {
          toolIcon = <BookmarkCheck size={13} className="text-cyan-400" />;
        } else if (status.tool === "ask_user") {
          toolIcon = <HelpCircle size={13} className="text-primary" />;
        }
        const desc = status.detail
          ? `${status.tool || "Working"}: ${status.detail}`
          : status.message || `Running ${status.tool}...`;
        return {
          icon: toolIcon,
          text: desc,
          colorClass: "border-amber-500/30 bg-amber-500/10 text-amber-300",
        };
      }
      case "step_complete":
        return {
          icon: <CheckCircle2 size={13} className="text-emerald-400" />,
          text: status.message || `Step ${(status.step ?? 0) + 1}/${status.total || "?"} complete`,
          colorClass: "border-emerald-500/30 bg-emerald-500/10 text-emerald-300",
        };
      case "duo_escalation":
        return {
          icon: <RefreshCw size={13} className="animate-spin text-purple-400" />,
          text: status.message || "Duo Loop refinement active...",
          colorClass: "border-purple-500/30 bg-purple-500/10 text-purple-300",
        };
      case "proposal_created":
        return {
          icon: <Sparkles size={13} className="text-primary" />,
          text: status.message || "Edit proposal ready for review in Diff Inspector",
          colorClass: "border-primary/40 bg-primary/10 text-primary",
        };
      case "done":
        return {
          icon: <CheckCircle2 size={13} className="text-emerald-400" />,
          text: status.message || "Task completed",
          colorClass: "border-emerald-500/30 bg-emerald-500/5 text-emerald-400",
        };
      case "error":
        return {
          icon: <AlertCircle size={13} className="text-rose-400" />,
          text: status.message || "Error occurred",
          colorClass: "border-rose-500/40 bg-rose-500/10 text-rose-300",
        };
      default:
        return {
          icon: <Bot size={13} className="text-primary" />,
          text: status.message || "Rony Agent working...",
          colorClass: "border-primary/30 bg-primary/10 text-primary",
        };
    }
  };

  const { icon, text } = getStatusDisplay();
  const hasPlan = !!(plan && plan.steps && plan.steps.length > 0);
  const hasDetails = hasPlan || (toolHistory && toolHistory.length > 0);
  const isAwaitingApproval = !!(pendingApproval || status?.type === "approval_required");
  const isReasoning = status?.type === "thinking" || (!status && streaming);

  return (
    <div
      className={`w-full my-2 flex flex-col rounded-xl border bg-[#16171b] shadow-sm overflow-hidden text-xs transition-all duration-300 ${
        isAwaitingApproval
          ? "border-amber-500/50 animate-amber-glow"
          : isReasoning
          ? "border-primary/40 animate-pulse-glow"
          : "border-outline-variant/30"
      }`}
    >
      {/* ── Collapsed Pill Header (Always Visible) ───────────────────────── */}
      <button
        type="button"
        onClick={() => hasDetails && setExpanded(!expanded)}
        className={`w-full px-3 py-2 flex items-center justify-between gap-2 text-left transition-all duration-200 select-none ${
          hasDetails ? "cursor-pointer hover:bg-surface-variant/40" : "cursor-default"
        } ${expanded && hasDetails ? "border-b border-surface-variant/50 bg-[#1a1b20]" : ""}`}
      >
        <div className="flex items-center gap-2 min-w-0 flex-1">
          <div className="shrink-0 flex items-center justify-center">{icon}</div>
          <span className={`truncate font-ui-label-reg text-ui-label-reg font-medium ${isReasoning ? "shimmer-text" : ""}`}>
            {text}
          </span>
          {currentTier !== null && (
            <span className={`shrink-0 text-[9.5px] px-2 py-0.5 rounded-full font-mono font-bold flex items-center gap-1 ${
              currentTier === 2
                ? "bg-purple-500/20 text-purple-300 border border-purple-500/30"
                : currentTier === 1
                ? "bg-amber-500/20 text-amber-300 border border-amber-500/30"
                : "bg-emerald-500/20 text-emerald-300 border border-emerald-500/30"
            }`}>
              {currentTier === 2 ? <Brain size={10} /> : <Zap size={10} />}
              {currentTierLabel || (currentTier === 0 ? "Fast path" : (currentTier === 1 ? "Quick task" : "Deep think"))}
            </span>
          )}
          {hasPlan && (
            <span className="shrink-0 text-[10px] px-1.5 py-0.5 rounded-full bg-surface-variant text-on-surface-variant font-mono">
              Step {plan.current + 1}/{plan.steps.length}
            </span>
          )}
        </div>

        {hasDetails && (
          <div className="flex items-center gap-1 text-on-surface-variant shrink-0">
            <span className="text-[10px] opacity-75">
              {expanded ? "Hide details" : "Show details"}
            </span>
            <div className={`transition-transform duration-200 ${expanded ? "rotate-180" : ""}`}>
              <ChevronDown size={14} />
            </div>
          </div>
        )}
      </button>

      {/* ── Expanded Drawer (Plan & Tool Activity) ─────────────────────────── */}
      {expanded && (
        <div className="p-3 space-y-3 bg-[#111215] text-[11px] leading-relaxed max-h-72 overflow-y-auto animate-in fade-in slide-in-from-top-1 duration-200">
          {/* Dependency-Aware DAG Plan Checklist */}
          {hasPlan && (
            <div className="space-y-1.5">
              <div className="flex items-center justify-between font-bold uppercase text-[10px] text-on-surface-variant tracking-wider">
                <div className="flex items-center gap-1.5">
                  <ListChecks size={12} className="text-primary" />
                  <span>Execution Plan (DAG)</span>
                </div>
                <span className="text-[9px] font-mono opacity-60">
                  {plan.current + 1} of {plan.steps.length}
                </span>
              </div>
              <div className="space-y-1 pl-1">
                {plan.steps.map((stepItem, idx) => {
                  const isObj = typeof stepItem === "object" && stepItem !== null;
                  const title = isObj ? (stepItem as DAGPlanStep).title : String(stepItem);
                  const statusVal = isObj ? (stepItem as DAGPlanStep).status : (idx < plan.current ? "done" : (idx === plan.current ? "running" : "pending"));
                  const deps = isObj && (stepItem as DAGPlanStep).depends_on ? (stepItem as DAGPlanStep).depends_on : [];

                  return (
                    <div
                      key={idx}
                      className={`flex items-start gap-2 py-1 px-1.5 rounded transition-colors ${
                        statusVal === "done"
                          ? "text-on-surface-variant/70 bg-white/[0.02]"
                          : statusVal === "running"
                          ? "text-primary font-bold bg-primary/10 border border-primary/20"
                          : statusVal === "failed"
                          ? "text-rose-400 font-bold bg-rose-500/10 border border-rose-500/20"
                          : statusVal === "blocked"
                          ? "text-on-surface-variant/40 bg-white/[0.01]"
                          : "text-on-surface-variant/60"
                      }`}
                    >
                      <div className="shrink-0 mt-0.5">
                        {statusVal === "done" ? (
                          <CheckCircle2 size={12} className="text-emerald-400" />
                        ) : statusVal === "running" ? (
                          <Loader2 size={12} className="animate-spin text-primary" />
                        ) : statusVal === "failed" ? (
                          <AlertCircle size={12} className="text-rose-400" />
                        ) : statusVal === "blocked" ? (
                          <Ban size={12} className="text-on-surface-variant/40" />
                        ) : (
                          <Circle size={12} className="text-outline-variant" />
                        )}
                      </div>
                      <div className="flex-1 flex flex-col min-w-0">
                        <div className="flex items-center justify-between gap-2">
                          <span className={`break-words ${statusVal === "done" ? "line-through" : ""}`}>{title}</span>
                          {statusVal === "blocked" && (
                            <span className="shrink-0 text-[9px] px-1.5 py-0.2 rounded bg-amber-500/15 text-amber-300 font-mono">
                              blocked
                            </span>
                          )}
                        </div>
                        {deps && deps.length > 0 && (
                          <span className="text-[9px] text-outline-variant font-mono mt-0.5">
                            deps: {deps.join(", ")}
                          </span>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* Tool Execution History */}
          <div className="space-y-1.5 pt-2 border-t border-surface-variant/30">
            <div className="flex items-center justify-between font-bold uppercase text-[10px] text-on-surface-variant tracking-wider">
              <div className="flex items-center gap-1.5">
                <Terminal size={12} className="text-amber-400" />
                <span>Tool Activity Log ({toolHistory.length})</span>
              </div>
            </div>
            {toolHistory.length > 0 ? (
              <div className="space-y-1 pl-1 font-mono text-[10.5px]">
                {toolHistory.map((item, idx) => (
                  <div
                    key={idx}
                    className="flex items-center justify-between gap-2 p-1.5 rounded bg-[#18191f] border border-white/5"
                  >
                    <div className="flex items-center gap-1.5 truncate">
                      <span className="text-amber-400 font-bold">[{item.tool}]</span>
                      <span className="truncate text-on-surface-variant">
                        {item.detail || "Executed"}
                      </span>
                    </div>
                    <span className="shrink-0 text-[9px] text-outline-variant">
                      {new Date(item.timestamp).toLocaleTimeString([], {
                        hour: "2-digit",
                        minute: "2-digit",
                        second: "2-digit",
                      })}
                    </span>
                  </div>
                ))}
              </div>
            ) : (
              <div className="text-on-surface-variant/50 text-[10.5px] italic pl-1 py-1">
                No tools were executed
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
