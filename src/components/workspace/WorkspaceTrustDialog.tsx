import { useState } from "react";
import { Shield, AlertTriangle, FolderOpen, Lock, Unlock } from "lucide-react";
import { Button } from "../ui/Button";
import { IconButton } from "../ui/IconButton";

type WorkspaceTrustDialogProps = {
  workspacePath: string;
  onTrust: () => void;
  onRestricted: () => void;
  onCancel: () => void;
};

export function WorkspaceTrustDialog({ workspacePath, onTrust, onRestricted, onCancel }: WorkspaceTrustDialogProps) {
  const [selected, setSelected] = useState<"trust" | "restricted" | null>(null);

  const handleConfirm = () => {
    if (selected === "trust") {
      onTrust();
    } else if (selected === "restricted") {
      onRestricted();
    }
  };

  const workspaceName = workspacePath.split(/[\\/]/).pop() || workspacePath;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="bg-surface-900 border border-surface-700 rounded-xl shadow-2xl max-w-lg w-full mx-4 overflow-hidden">
        {/* Header */}
        <div className="bg-surface-800 border-b border-surface-700 px-6 py-4">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-amber-500/10 rounded-lg">
              <Shield size={20} className="text-amber-400" />
            </div>
            <div>
              <h2 className="text-lg font-semibold text-white">Workspace Trust Required</h2>
              <p className="text-sm text-slate-400">First time opening this workspace</p>
            </div>
          </div>
        </div>

        {/* Content */}
        <div className="p-6 space-y-4">
          <div className="bg-surface-950 border border-surface-800 rounded-lg p-4">
            <div className="flex items-center gap-2 mb-2">
              <FolderOpen size={16} className="text-slate-400" />
              <span className="font-mono text-sm text-slate-300 truncate">{workspaceName}</span>
            </div>
            <p className="text-xs text-slate-500 font-mono truncate">{workspacePath}</p>
          </div>

          <p className="text-sm text-slate-300 leading-relaxed">
            This app needs your permission to access this workspace. Trusted workspaces allow AI agents to read, edit, and run commands. Restricted mode limits access to read-only operations.
          </p>

          {/* Options */}
          <div className="space-y-3">
            <button
              onClick={() => setSelected("trust")}
              className={`w-full flex items-start gap-3 p-4 rounded-lg border transition-all ${
                selected === "trust"
                  ? "bg-emerald-500/10 border-emerald-500/50 ring-1 ring-emerald-500/30"
                  : "bg-surface-800 border-surface-700 hover:border-surface-600"
              }`}
            >
              <div className={`p-2 rounded-lg ${selected === "trust" ? "bg-emerald-500/20" : "bg-surface-700"}`}>
                <Unlock size={18} className={selected === "trust" ? "text-emerald-400" : "text-slate-400"} />
              </div>
              <div className="flex-1 text-left">
                <div className="font-semibold text-white mb-1">Trust Workspace</div>
                <div className="text-xs text-slate-400">
                  Full access: AI can read, edit files, and run commands with your approval
                </div>
              </div>
            </button>

            <button
              onClick={() => setSelected("restricted")}
              className={`w-full flex items-start gap-3 p-4 rounded-lg border transition-all ${
                selected === "restricted"
                  ? "bg-amber-500/10 border-amber-500/50 ring-1 ring-amber-500/30"
                  : "bg-surface-800 border-surface-700 hover:border-surface-600"
              }`}
            >
              <div className={`p-2 rounded-lg ${selected === "restricted" ? "bg-amber-500/20" : "bg-surface-700"}`}>
                <Lock size={18} className={selected === "restricted" ? "text-amber-400" : "text-slate-400"} />
              </div>
              <div className="flex-1 text-left">
                <div className="font-semibold text-white mb-1">Restricted Mode</div>
                <div className="text-xs text-slate-400">
                  Read-only: Browse files without AI write access or command execution
                </div>
              </div>
            </button>
          </div>

          {/* Warning */}
          <div className="flex items-start gap-2 p-3 bg-amber-500/5 border border-amber-500/20 rounded-lg">
            <AlertTriangle size={16} className="text-amber-400 shrink-0 mt-0.5" />
            <p className="text-xs text-amber-200/80 leading-relaxed">
              Only trust workspaces you control. AI agents will require explicit approval before executing commands or making changes.
            </p>
          </div>
        </div>

        {/* Footer */}
        <div className="bg-surface-800 border-t border-surface-700 px-6 py-4 flex justify-between items-center">
          <Button variant="ghost" onClick={onCancel}>
            Cancel
          </Button>
          <Button
            variant="primary"
            onClick={handleConfirm}
            disabled={!selected}
            className="min-w-[120px]"
          >
            Continue
          </Button>
        </div>
      </div>
    </div>
  );
}
