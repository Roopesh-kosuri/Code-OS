import { FolderOpen, RotateCw, Settings, ShieldCheck, ShieldAlert, RefreshCw } from "lucide-react";
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
    <header className="bg-background flex justify-between items-center w-full px-6 py-2.5 border-b border-surface-container-low flex-shrink-0 z-50 select-none text-on-surface">
      {/* Left: Brand Logo & Status Cluster */}
      <div className="flex items-center gap-6">
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
                className="bg-error-container/20 text-error border border-error-container/40 rounded-full px-3 py-1 font-caption text-caption flex items-center gap-1.5 hover:bg-error-container/30 transition-colors"
                title="Workspace in Restricted Mode (Click to Trust workspace)"
              >
                <span className="material-symbols-outlined text-[14px]">gjt</span>
                <span>Restricted</span>
              </button>
            ) : (
              <button
                onClick={async () => {
                  if (currentWorkspace) {
                    await setWorkspaceTrust(currentWorkspace.path, false);
                  }
                }}
                className="bg-secondary-container/20 text-secondary border border-secondary-container rounded-full px-3 py-1 font-caption text-caption flex items-center gap-1.5 hover:bg-secondary-container/30 transition-colors"
                title="Workspace is Trusted (Click to switch to Restricted Mode)"
              >
                <span className="material-symbols-outlined text-[14px]" style={{ fontVariationSettings: "'FILL' 1" }}>
                  verified_user
                </span>
                <span>Trusted</span>
              </button>
            )
          )}

          <span className="bg-surface-variant text-on-surface-variant rounded-full px-3 py-1 font-caption text-caption">
            {indexLabel}
          </span>
        </div>
      </div>

      {/* Center: Navigation Links */}
      <nav className="flex items-center space-x-6">
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

      {/* Right: Actions */}
      <div className="flex items-center gap-3 text-on-surface-variant">
        {currentWorkspace ? (
          <button
            onClick={() => void openWorkspace()}
            className="flex items-center gap-2 bg-surface-container-low hover:bg-surface-container-high px-3 py-1 rounded-full border border-white/5 text-xs font-mono text-on-surface transition-all max-w-[180px] truncate"
            title={`Workspace: ${currentWorkspace.path} (Click to switch)`}
          >
            <FolderOpen size={13} className="text-primary shrink-0" />
            <span className="truncate">{currentWorkspace.name}</span>
          </button>
        ) : (
          <button
            onClick={() => void openWorkspace()}
            disabled={loading}
            className="flex items-center gap-2 bg-primary-container/10 hover:bg-primary-container/20 text-primary-container border border-primary-container/30 px-3 py-1 rounded-full text-xs font-bold transition-all shadow-[0_0_10px_rgba(0,218,243,0.15)]"
          >
            <FolderOpen size={13} />
            <span>Open Folder</span>
          </button>
        )}

        <button
          onClick={() => void runIndex()}
          className="hover:text-primary transition-colors p-1.5 rounded-full hover:bg-surface-variant/40"
          title="Re-index workspace"
        >
          <span className="material-symbols-outlined text-[18px]">refresh</span>
        </button>

        <button
          onClick={onOpenSettings}
          className="hover:text-primary transition-colors p-1.5 rounded-full hover:bg-surface-variant/40"
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
      </div>
    </header>
  );
}
