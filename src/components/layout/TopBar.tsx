import { FolderOpen, RotateCw, Settings, X, ShieldCheck, ShieldAlert } from "lucide-react";

import { Button } from "../ui/Button";
import { CodeOsLogo } from "../branding/CodeOsLogo";
import { IconButton } from "../ui/IconButton";
import { useEditorStore } from "../../stores/editorStore";
import { useIndexStore } from "../../stores/indexStore";
import { useWorkspaceStore } from "../../stores/workspaceStore";

type TopBarProps = {
  onOpenSettings: () => void;
  activeView: string;
  onViewChange: (view: string) => void;
};

export function TopBar({ onOpenSettings, activeView, onViewChange }: TopBarProps) {
  const currentWorkspace = useWorkspaceStore((state) => state.currentWorkspace);
  const loading = useWorkspaceStore((state) => state.loading);
  const openWorkspace = useWorkspaceStore((state) => state.openWorkspace);
  const refreshTree = useWorkspaceStore((state) => state.refreshTree);
  const closeWorkspace = useWorkspaceStore((state) => state.closeWorkspace);
  const error = useWorkspaceStore((state) => state.error);
  const closeWorkspaceTabs = useEditorStore((state) => state.closeWorkspaceTabs);
  const indexStatus = useIndexStore((state) => state.status);
  const runIndex = useIndexStore((state) => state.run);
  const restrictedMode = useWorkspaceStore((state) => state.restrictedMode);
  const setWorkspaceTrust = useWorkspaceStore((state) => state.setWorkspaceTrust);

  const indexLabel = indexStatus
    ? indexStatus.status === "ready"
      ? `Index ready: ${indexStatus.indexed_files} files`
      : `Index ${indexStatus.status}`
    : "Index pending";

  return (
    <header data-testid="top-nav" className="relative flex justify-between items-center w-full px-4 h-12 z-50 bg-[var(--bg-surface-900)]/90 backdrop-blur-xl border-b border-[var(--outline-variant)]/20 shadow-sm shrink-0 select-none text-[var(--on-surface)]">
      {/* Left Section: Brand Logo & Top Nav Links */}
      <div className="flex items-center gap-6 min-w-0">
        <span 
          onClick={() => onViewChange("main")}
          className="font-headline-md text-headline-md font-black tracking-tight text-primary cursor-pointer hover:opacity-90 transition-opacity"
        >
          CODE OS
        </span>
        
        {/* Navigation Links */}
        <nav className="hidden lg:flex items-center gap-1 border-l border-[var(--outline-variant)]/20 pl-6 h-5">
          {["main", "agent", "duo", "verifier", "diagnostics", "proposals"].map((v) => (
            <button
              key={v}
              onClick={() => onViewChange(v)}
              className={`font-label-caps text-label-caps px-3 py-1 rounded cursor-pointer transition-all capitalize font-medium ${
                activeView === v
                  ? "text-primary border-b-2 border-primary bg-primary/10 font-bold shadow-[0_0_8px_rgba(0,229,255,0.2)]"
                  : "text-[var(--on-surface-variant)] hover:text-[var(--on-surface)] hover:bg-[var(--outline-variant)]/10"
              }`}
            >
              {v}
            </button>
          ))}
          <button
            onClick={onOpenSettings}
            className="font-label-caps text-label-caps px-3 py-1 rounded cursor-pointer transition-all text-[var(--on-surface-variant)] hover:text-[var(--on-surface)] hover:bg-[var(--outline-variant)]/10 font-medium"
          >
            Settings
          </button>
        </nav>
      </div>

      {/* Right Section: Workspace Pill, Indexing Status & Tools */}
      <div className="flex items-center gap-3">
        {/* Workspace Selector Pill */}
        {currentWorkspace ? (
          <button
            data-testid="workspace-selector"
            onClick={() => void openWorkspace()}
            className="flex items-center gap-2 bg-surface-container-high hover:bg-surface-container-highest px-3 py-1 rounded-full border border-white/10 text-xs font-mono text-on-surface transition-all max-w-[200px] truncate"
            title={`Workspace: ${currentWorkspace.path} (Click to switch)`}
          >
            <FolderOpen size={13} className="text-primary shrink-0" />
            <span className="truncate">{currentWorkspace.name}</span>
          </button>
        ) : (
          <button
            data-testid="workspace-selector"
            onClick={() => void openWorkspace()}
            disabled={loading}
            className="flex items-center gap-2 bg-primary/10 hover:bg-primary/20 text-primary border border-primary/30 px-3 py-1 rounded-full text-xs font-bold transition-all shadow-[0_0_10px_rgba(0,229,255,0.15)]"
          >
            <FolderOpen size={13} />
            <span>Open Folder</span>
          </button>
        )}

        {/* Workspace Trust Status Pill */}
        {currentWorkspace && (

          restrictedMode ? (
            <button
              onClick={async () => {
                if (currentWorkspace) {
                  await setWorkspaceTrust(currentWorkspace.path, true);
                }
              }}
              className="flex items-center gap-1.5 bg-amber-500/10 hover:bg-amber-500/20 text-amber-300 border border-amber-500/30 px-2.5 py-1 rounded-full text-[11px] font-medium transition-all cursor-pointer shrink-0"
              title="Workspace in Restricted Mode (Click to Trust workspace for AI write & command execution)"
            >
              <ShieldAlert size={13} className="text-amber-400 shrink-0" />
              <span>Restricted</span>
            </button>
          ) : (
            <button
              onClick={async () => {
                if (currentWorkspace) {
                  await setWorkspaceTrust(currentWorkspace.path, false);
                }
              }}
              className="flex items-center gap-1.5 bg-emerald-500/10 hover:bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 px-2.5 py-1 rounded-full text-[11px] font-medium transition-all cursor-pointer shrink-0"
              title="Workspace is Trusted (Click to switch to Restricted Mode)"
            >
              <ShieldCheck size={13} className="text-emerald-400 shrink-0" />
              <span>Trusted</span>
            </button>
          )
        )}


        {/* Index Status Chip */}
        <div className="hidden sm:flex items-center gap-1.5 font-micro-label text-micro-label text-on-surface-variant bg-surface-container-low px-2.5 py-1 rounded border border-white/5 font-mono">
          <span className="w-1.5 h-1.5 rounded-full bg-primary-container animate-pulse" />
          <span>{indexLabel}</span>
        </div>

        {/* Action Buttons */}
        <button
          onClick={() => void runIndex()}
          aria-label="Re-index workspace"
          className="text-on-surface-variant hover:text-primary transition-colors p-1.5 rounded hover:bg-white/5"
          title="Re-index Workspace"
        >
          <RotateCw size={14} />
        </button>

        <button
          onClick={onOpenSettings}
          aria-label="Settings"
          className="text-on-surface-variant hover:text-primary transition-colors p-1.5 rounded hover:bg-white/5"
          title="Settings"
        >
          <Settings size={14} />
        </button>
      </div>
    </header>

  );
}
