import React, { useState } from "react";
import {
  ShieldCheck,
  ShieldAlert,
  AlertTriangle,
  Loader2,
  ChevronDown,
  ChevronUp,
  FileCheck,
  TestTube,
  Lock,
  Package,
  CheckCircle2,
  XCircle,
  HelpCircle,
} from "lucide-react";
import type { VerificationState, VerificationHookResult } from "../../stores/aiStore";

interface VerificationBadgeProps {
  verification?: VerificationState | null;
  className?: string;
}

function getHookIcon(hook: string) {
  switch (hook) {
    case "readback_hash":
      return <FileCheck size={12} className="shrink-0 text-cyan-400" />;
    case "security_scan":
      return <Lock size={12} className="shrink-0 text-amber-400" />;
    case "test_suite":
      return <TestTube size={12} className="shrink-0 text-indigo-400" />;
    case "npm_audit":
      return <Package size={12} className="shrink-0 text-violet-400" />;
    default:
      return <HelpCircle size={12} className="shrink-0 text-zinc-400" />;
  }
}

function getHookLabel(hook: string): string {
  switch (hook) {
    case "readback_hash":
      return "Readback Hash";
    case "security_scan":
      return "Diff-Scoped Security";
    case "test_suite":
      return "Targeted Tests";
    case "npm_audit":
      return "Package Lock Audit";
    default:
      return hook;
  }
}

function getHookStatusBadge(status: string) {
  const norm = (status || "").toLowerCase();
  if (norm === "passed") {
    return (
      <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-mono font-medium bg-emerald-500/15 text-emerald-300 border border-emerald-500/30">
        <CheckCircle2 size={10} className="text-emerald-400" />
        passed
      </span>
    );
  }
  if (norm === "failed") {
    return (
      <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-mono font-medium bg-rose-500/15 text-rose-300 border border-rose-500/30">
        <XCircle size={10} className="text-rose-400" />
        failed
      </span>
    );
  }
  if (norm === "warn") {
    return (
      <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-mono font-medium bg-amber-500/15 text-amber-300 border border-amber-500/30">
        <AlertTriangle size={10} className="text-amber-400" />
        warn
      </span>
    );
  }
  if (norm === "skipped") {
    return (
      <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-mono font-medium bg-zinc-800 text-zinc-400 border border-zinc-700">
        skipped
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-mono font-medium bg-amber-500/10 text-amber-300 border border-amber-500/20">
      {status}
    </span>
  );
}

export function VerificationBadge({ verification, className = "" }: VerificationBadgeProps) {
  const [expanded, setExpanded] = useState(false);

  if (!verification || !verification.status || verification.status === "idle") {
    return null;
  }

  const { status, results = [], verdict } = verification;
  const caveats = verdict?.caveats || [];
  const reasons = verdict?.reasons || [];
  const summaryLine = verdict?.summary_line || "";

  // Compute failed hook names for compact pill display
  const failedHooks = results
    .filter((r) => (r.status || "").toLowerCase() === "failed")
    .map((r) => getHookLabel(r.hook));

  let pillClasses = "";
  let icon = null;
  let label = "";

  switch (status.toLowerCase()) {
    case "verifying":
      pillClasses = "bg-zinc-800/90 text-zinc-300 border-zinc-700/60 hover:bg-zinc-800";
      icon = <Loader2 size={12} className="animate-spin text-zinc-400 shrink-0" />;
      label = "verifying…";
      break;

    case "verified":
      pillClasses = "bg-emerald-500/15 text-emerald-300 border-emerald-500/30 hover:bg-emerald-500/25";
      icon = <ShieldCheck size={12} className="text-emerald-400 shrink-0" />;
      label = caveats.length > 0 ? "verified (with caveats)" : "verified";
      break;

    case "unverified":
      pillClasses = "bg-amber-500/15 text-amber-300 border-amber-500/30 hover:bg-amber-500/25";
      icon = <AlertTriangle size={12} className="text-amber-400 shrink-0" />;
      label = reasons.length > 0 ? `unverified: ${reasons[0]}` : "unverified";
      break;

    case "failed":
      pillClasses = "bg-rose-500/15 text-rose-300 border-rose-500/30 hover:bg-rose-500/25";
      icon = <ShieldAlert size={12} className="text-rose-400 shrink-0" />;
      label = failedHooks.length > 0 ? `verification failed: ${failedHooks.join(", ")}` : "verification failed";
      break;

    default:
      pillClasses = "bg-zinc-800 text-zinc-400 border-zinc-700";
      icon = <HelpCircle size={12} className="text-zinc-500 shrink-0" />;
      label = status;
      break;
  }

  return (
    <div className={`w-full mt-2 pt-2 border-t border-white/10 ${className}`}>
      {/* Pill Toggle Button */}
      <button
        type="button"
        data-testid="verification-badge-btn"
        onClick={() => setExpanded(!expanded)}
        className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-mono font-medium border shadow-xs transition-all cursor-pointer ${pillClasses}`}
        title="Click to view verification evidence details"
      >
        {icon}
        <span className="truncate max-w-[320px]">{label}</span>
        {expanded ? (
          <ChevronUp size={11} className="opacity-70 ml-0.5 shrink-0" />
        ) : (
          <ChevronDown size={11} className="opacity-70 ml-0.5 shrink-0" />
        )}
      </button>

      {/* Expandable Evidence Drawer */}
      {expanded && (
        <div
          data-testid="verification-drawer"
          className="mt-2.5 p-3 rounded-xl bg-[#14151a] border border-white/10 text-xs space-y-2.5 shadow-md animate-in fade-in slide-in-from-top-1 duration-150"
        >
          {/* Summary Line Header */}
          {summaryLine && (
            <div className="flex items-start gap-2 pb-2 border-b border-white/5 font-mono text-[11.5px] leading-relaxed text-zinc-200">
              <span className="text-primary font-bold">Evidence:</span>
              <span className="break-words [overflow-wrap:anywhere]">{summaryLine}</span>
            </div>
          )}

          {/* Caveat Chips */}
          {caveats.length > 0 && (
            <div className="space-y-1">
              <span className="text-[10px] uppercase font-bold text-amber-400/90 tracking-wider">Caveats:</span>
              <div className="flex flex-wrap gap-1.5">
                {caveats.map((caveat, idx) => (
                  <span
                    key={idx}
                    className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10.5px] font-mono bg-amber-500/10 text-amber-300 border border-amber-500/25"
                  >
                    <AlertTriangle size={10} className="text-amber-400 shrink-0" />
                    {caveat}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Unverified / Failed Reasons */}
          {reasons.length > 0 && (
            <div className="space-y-1">
              <span className="text-[10px] uppercase font-bold text-rose-400/90 tracking-wider">Reasons:</span>
              <div className="flex flex-wrap gap-1.5">
                {reasons.map((reason, idx) => (
                  <span
                    key={idx}
                    className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10.5px] font-mono bg-rose-500/10 text-rose-300 border border-rose-500/25"
                  >
                    <XCircle size={10} className="text-rose-400 shrink-0" />
                    {reason}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Per-Hook Results */}
          <div className="space-y-2 pt-1">
            <span className="text-[10px] uppercase font-bold text-zinc-400 tracking-wider">Verification Hooks:</span>
            {results.length === 0 ? (
              <p className="text-[11px] text-zinc-500 font-mono italic">No verification hooks executed.</p>
            ) : (
              <div className="space-y-1.5">
                {results.map((r: VerificationHookResult, idx: number) => (
                  <div
                    key={idx}
                    className="p-2 rounded-lg bg-[#1a1b22] border border-white/5 space-y-1 font-mono text-[11px]"
                  >
                    <div className="flex items-center justify-between gap-2">
                      <div className="flex items-center gap-1.5 min-w-0">
                        {getHookIcon(r.hook)}
                        <span className="font-semibold text-zinc-200 truncate">{getHookLabel(r.hook)}</span>
                      </div>
                      <div className="flex items-center gap-2 shrink-0">
                        {r.duration_ms > 0 && (
                          <span className="text-[10px] text-zinc-500 font-mono">
                            {r.duration_ms < 1000 ? `${r.duration_ms}ms` : `${(r.duration_ms / 1000).toFixed(2)}s`}
                          </span>
                        )}
                        {getHookStatusBadge(r.status)}
                      </div>
                    </div>

                    {r.summary && (
                      <p className="text-[10.5px] text-zinc-400 leading-snug break-words pl-4">
                        {r.summary}
                      </p>
                    )}

                    {r.skip_reason && (
                      <p className="text-[10px] text-zinc-500 italic pl-4">
                        Reason: {r.skip_reason}
                      </p>
                    )}

                    {r.details && r.details.length > 0 && (
                      <div className="mt-1 pl-4 space-y-0.5">
                        {r.details.map((det, dIdx) => (
                          <div key={dIdx} className="text-[10px] text-rose-300/90 break-words font-mono bg-rose-500/10 px-1.5 py-0.5 rounded border border-rose-500/20">
                            {det}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
