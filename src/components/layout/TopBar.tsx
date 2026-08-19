import { useState, useEffect } from "react";
import { FolderOpen, RotateCw, Settings, ShieldCheck, ShieldAlert, RefreshCw, Minus, Square, X, Copy } from "lucide-react";
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
  const indexStatus = useIndexStore((state) => state.status);
  const runIndex = useIndexStore((state) => state.run);
  const restrictedMode = useWorkspaceStore((state) => state.restrictedMode);
  const setWorkspaceTrust = useWorkspaceStore((state) => state.setWorkspaceTrust);
  const [isMaximized, setIsMaximized] = useState(false);

  useEffect(() => {
    if (window.codeOS?.windowControls) {
      window.codeOS.windowControls.isMaximized().then(setIsMaximized).catch(() => {});
    }
  }, []);

  const handleMinimize = () => {
    window.codeOS?.windowControls?.minimize();
  };

  const handleMaximize = async () => {
    if (window.codeOS?.windowControls) {
      await window.codeOS.windowControls.maximize();
      const max = await window.codeOS.windowControls.isMaximized();
      setIsMaximized(max);
    }
  };

  const handleClose = () => {
    window.codeOS?.windowControls?.close();
  };

  const indexLabel = indexStatus
    ? indexStatus.status === "ready"
      ? `Index: Ready`
      : `Index: ${indexStatus.status}`
    : "Index: Pending";

  const navItems = [
    { id: "main", label: "Main" },
    { id: "agent", label: "Agent" },
    { id: "duo", label: "Duo" },
    { id: "verifier", label: "Verifier" },
    { id: "diagnostics", label: "Diagnostics" },
    { id: "proposals", label: "Proposals" },
    { id: "settings", label: "Settings" },
  ];

  return (
    <header
      style={{ WebkitAppRegion: "drag" } as React.CSSProperties}
      className="bg-background flex justify-between items-center w-full px-6 py-2.5 border-b border-surface-container-low flex-shrink-0 z-50 select-none text-on-surface"
    >
      {/* Left: Brand Logo & Status Cluster */}
      <div className="flex items-center gap-6" style={{ WebkitAppRegion: "no-drag" } as React.CSSProperties}>
        <div 
          onClick={() => onViewChange("main")}
          className="flex items-center gap-2 cursor-pointer group"
        >
          <div className="w-8 h-8 rounded-lg bg-primary/10 border border-primary/20 flex items-center justify-center group-hover:bg-primary/20 transition-colors">
            <span className="material-symbols-outlined text-primary text-xl" style={{ fontVariationSettings: "'FILL' 1" }}>
              terminal
            </span>
          </div>
          <span className="font-headline-md text-headline-md font-bold tracking-tight text-on-surface">
            CODE <span className="text-primary-container">OS</span>
          </span>
        </div>

        {/* Status Cluster */}
        <div className="flex items-center gap-2 ml-2">
          {currentWorkspace && (
            restrictedMode ? (
              <button
                onClick={async () => {
                  if (currentWorkspace) {
                    await setWorkspaceTrust(currentWorkspace.path, true);
                  }
                }}
                className="bg-error/15 text-error border border-error/30 rounded-full px-3 py-1 font-caption text-caption flex items-center gap-1.5 hover:bg-error/25 transition-all shadow-xs cursor-pointer"
                title="Workspace in Restricted Mode (Click to Trust workspace)"
              >
                <ShieldAlert size={13} className="text-error shrink-0" />
                <span className="font-semibold text-xs">Restricted</span>
              </button>
            ) : (
              <button
                onClick={async () => {
                  if (currentWorkspace) {
                    await setWorkspaceTrust(currentWorkspace.path, false);
                  }
                }}
                className="bg-secondary-container/20 text-secondary border border-secondary-container rounded-full px-3 py-1 font-caption text-caption flex items-center gap-1.5 hover:bg-secondary-container/30 transition-all shadow-xs cursor-pointer"
                title="Workspace is Trusted (Click to switch to Restricted Mode)"
              >
                <ShieldCheck size={13} className="text-secondary shrink-0" />
                <span className="font-semibold text-xs">Trusted</span>
              </button>
            )
          )}

          <span className="bg-surface-variant text-on-surface-variant rounded-full px-3 py-1 font-caption text-caption">
            {indexLabel}
          </span>
        </div>
      </div>

      {/* Center: Navigation Links */}
      <nav className="flex items-center space-x-6" style={{ WebkitAppRegion: "no-drag" } as React.CSSProperties}>
        {navItems.map(({ id, label }) => {
          const isActive = id === "settings" ? false : activeView === id;
          return (
            <button
              key={id}
              onClick={() => {
                if (id === "settings") {
                  onOpenSettings();
                } else {
                  onViewChange(id);
                }
              }}
              className={`transition-all scale-95 duration-150 py-1 cursor-pointer ${
                isActive
                  ? "text-primary font-ui-label-bold text-ui-label-bold border-b-2 border-primary pb-1"
                  : "text-on-surface-variant font-ui-label-reg text-ui-label-reg hover:text-primary"
              }`}
            >
              {label}
            </button>
          );
        })}
      </nav>

      {/* Right: Actions & Window Controls */}
      <div className="flex items-center gap-3 text-on-surface-variant" style={{ WebkitAppRegion: "no-drag" } as React.CSSProperties}>
        {currentWorkspace ? (
          <button
            onClick={() => void openWorkspace()}
            className="flex items-center gap-2 bg-surface-container-low hover:bg-surface-container-high px-3 py-1 rounded-full border border-white/5 text-xs font-mono text-on-surface transition-all max-w-[180px] truncate cursor-pointer"
            title={`Workspace: ${currentWorkspace.path} (Click to switch)`}
          >
            <FolderOpen size={13} className="text-primary shrink-0" />
            <span className="truncate">{currentWorkspace.name}</span>
          </button>
        ) : (
          <button
            onClick={() => void openWorkspace()}
            disabled={loading}
            className="flex items-center gap-2 bg-primary-container/10 hover:bg-primary-container/20 text-primary-container border border-primary-container/30 px-3 py-1 rounded-full text-xs font-bold transition-all shadow-[0_0_10px_rgba(0,218,243,0.15)] cursor-pointer"
          >
            <FolderOpen size={13} />
            <span>Open Folder</span>
          </button>
        )}

        <button
          onClick={() => void runIndex()}
          className="hover:text-primary transition-colors p-1.5 rounded-full hover:bg-surface-variant/40 cursor-pointer"
          title="Re-index workspace"
        >
          <span className="material-symbols-outlined text-[18px]">refresh</span>
        </button>

        <button
          onClick={onOpenSettings}
          className="hover:text-primary transition-colors p-1.5 rounded-full hover:bg-surface-variant/40 cursor-pointer"
          title="Settings"
        >
          <span className="material-symbols-outlined text-[18px]">settings</span>
        </button>

        <div 
          onClick={onOpenSettings}
          className="w-8 h-8 rounded-full bg-surface-variant border border-outline-variant/40 overflow-hidden ml-1 cursor-pointer flex items-center justify-center hover:ring-2 hover:ring-primary/40 transition-all"
          title="User Profile & Settings"
        >
          <span className="material-symbols-outlined text-on-surface-variant text-lg">
            account_circle
          </span>
        </div>

        {/* Custom Window Controls (Frameless Chrome) */}
        {window.codeOS && (
          <div className="flex items-center gap-1 ml-2 pl-2 border-l border-surface-container-high">
            <button
              onClick={handleMinimize}
              className="w-7 h-7 flex items-center justify-center rounded-md hover:bg-surface-variant text-on-surface-variant hover:text-on-surface transition-colors cursor-pointer"
              title="Minimize"
              aria-label="Minimize"
            >
              <Minus size={13} />
            </button>
            <button
              onClick={handleMaximize}
              className="w-7 h-7 flex items-center justify-center rounded-md hover:bg-surface-variant text-on-surface-variant hover:text-on-surface transition-colors cursor-pointer"
              title={isMaximized ? "Restore" : "Maximize"}
              aria-label={isMaximized ? "Restore" : "Maximize"}
            >
              {isMaximized ? <Copy size={11} className="rotate-180" /> : <Square size={11} />}
            </button>
            <button
              onClick={handleClose}
              className="w-7 h-7 flex items-center justify-center rounded-md hover:bg-error hover:text-white text-on-surface-variant transition-colors cursor-pointer"
              title="Close"
              aria-label="Close"
            >
              <X size={14} />
            </button>
          </div>
        )}
      </div>
    </header>
  );
}

