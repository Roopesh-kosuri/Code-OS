import { ShieldAlert, Terminal, FileCode, FlaskConical, Check, X } from "lucide-react";
import { Button } from "./Button";

type PermissionGateProps = {
  type: "command" | "file-write" | "test-run" | "duo-finalize";
  details: string;
  command?: string;
  files?: string[];
  onApprove: () => void;
  onReject: () => void;
  isLoading?: boolean;
};

export function PermissionGate({ type, details, command, files, onApprove, onReject, isLoading }: PermissionGateProps) {
  const config = {
    "command": {
      icon: Terminal,
      color: "amber",
      title: "Command Execution Required",
      description: "This will run a shell command in your workspace"
    },
    "file-write": {
      icon: FileCode,
      color: "rose", 
      title: "File Write Permission Required",
      description: "This will modify files in your workspace"
    },
    "test-run": {
      icon: FlaskConical,
      color: "emerald",
      title: "Test Execution Required",
      description: "This will run your test suite"
    },
    "duo-finalize": {
      icon: Check,
      color: "violet",
      title: "Duo Loop Finalization",
      description: "Apply the final proposed changes after critic approval"
    }
  }[type];

  const { icon: Icon, color, title, description } = config;

  const THEME_CONFIGS: Record<"amber" | "rose" | "emerald" | "violet", {
    border: string;
    bg: string;
    text: string;
    inputText: string;
    badgeBg: string;
    badgeBorder: string;
    icon: string;
    btnBg: string;
  }> = {
    amber: {
      border: "border-amber-500/40",
      bg: "bg-amber-950/20",
      text: "text-amber-300",
      inputText: "text-amber-400",
      badgeBg: "bg-amber-500/5",
      badgeBorder: "border-amber-500/20",
      icon: "text-amber-400",
      btnBg: "bg-amber-600 hover:bg-amber-500 border-amber-500/30"
    },
    rose: {
      border: "border-rose-500/40",
      bg: "bg-rose-950/20",
      text: "text-rose-300",
      inputText: "text-rose-400",
      badgeBg: "bg-rose-500/5",
      badgeBorder: "border-rose-500/20",
      icon: "text-rose-400",
      btnBg: "bg-rose-600 hover:bg-rose-500 border-rose-500/30"
    },
    emerald: {
      border: "border-emerald-500/40",
      bg: "bg-emerald-950/20",
      text: "text-emerald-300",
      inputText: "text-emerald-400",
      badgeBg: "bg-emerald-500/5",
      badgeBorder: "border-emerald-500/20",
      icon: "text-emerald-400",
      btnBg: "bg-emerald-600 hover:bg-emerald-500 border-emerald-500/30"
    },
    violet: {
      border: "border-violet-500/40",
      bg: "bg-violet-950/20",
      text: "text-violet-300",
      inputText: "text-violet-400",
      badgeBg: "bg-violet-500/5",
      badgeBorder: "border-violet-500/20",
      icon: "text-violet-400",
      btnBg: "bg-violet-600 hover:bg-violet-500 border-violet-500/30"
    }
  };

  const themeMap = THEME_CONFIGS[color as "amber" | "rose" | "emerald" | "violet"] ?? THEME_CONFIGS.amber;

  const handleApproveClick = () => {
    console.info(`[PermissionGate] Approve clicked for type=${type}`);
    onApprove();
  };

  const handleRejectClick = () => {
    console.info(`[PermissionGate] Reject clicked for type=${type}`);
    onReject();
  };

  return (
    <div className={`rounded-lg border p-4 space-y-3 ${themeMap.border} ${themeMap.bg}`}>
      {/* Header */}
      <div className={`flex items-center gap-2 font-bold text-sm ${themeMap.text}`}>
        <Icon size={16} className="shrink-0" />
        <span>{title}</span>
      </div>

      {/* Description */}
      <p className="text-slate-300 text-xs leading-relaxed">{description}</p>

      {/* Details */}
      <div className="text-slate-400 text-xs leading-snug">{details}</div>

      {/* Command preview */}
      {command && (
        <div className="bg-surface-950 p-2 rounded font-mono text-[10px] text-slate-400 select-all break-all border border-surface-800">
          <span className={themeMap.inputText}>$</span> {command}
        </div>
      )}

      {/* Files list */}
      {files && files.length > 0 && (
        <div className="space-y-1">
          <div className="text-[9px] font-semibold text-slate-500 uppercase tracking-wider">Files to modify</div>
          <div className="flex flex-wrap gap-1">
            {files.slice(0, 5).map((file, idx) => (
              <span
                key={idx}
                className="text-[9px] font-mono text-slate-300 bg-surface-800 border border-surface-700 px-1.5 py-0.5 rounded truncate max-w-[150px]"
                title={file}
              >
                {file.split(/[\\/]/).pop()}
              </span>
            ))}
            {files.length > 5 && (
              <span className="text-[9px] text-slate-500">+{files.length - 5} more</span>
            )}
          </div>
        </div>
      )}

      {/* Warning */}
      <div className={`flex items-start gap-2 p-2 border rounded ${themeMap.badgeBg} ${themeMap.badgeBorder}`}>
        <ShieldAlert size={14} className={`shrink-0 mt-0.5 ${themeMap.icon}`} />
        <p className="text-xs text-slate-300 leading-relaxed">
          Review this action carefully. It will be executed with your approval and cannot be undone automatically.
        </p>
      </div>

      {/* Actions */}
      <div className="flex gap-2 justify-end pt-2">
        <Button
          variant="ghost"
          onClick={handleRejectClick}
          disabled={isLoading}
          className="h-8 px-3 text-xs"
        >
          <X size={12} className="mr-1" />
          Deny
        </Button>
        <Button
          variant="primary"
          onClick={handleApproveClick}
          disabled={isLoading}
          className={`h-8 px-3 text-xs ${themeMap.btnBg}`}
        >
          {isLoading ? (
            <span>Processing...</span>
          ) : (
            <span className="flex items-center">
              <Check size={12} className="mr-1" />
              Approve
            </span>
          )}
        </Button>
      </div>
    </div>
  );
}
