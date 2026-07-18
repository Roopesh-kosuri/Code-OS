import { FolderOpen, RotateCw, Settings, X, ShieldCheck, ShieldAlert } from "lucide-react";

import { Button } from "../ui/Button";
import { CodeOsLogo } from "../branding/CodeOsLogo";
import { IconButton } from "../ui/IconButton";
import { useEditorStore } from "../../stores/editorStore";
import { useIndexStore } from "../../stores/indexStore";
import { useWorkspaceStore } from "../../stores/workspaceStore";

type TopBarProps = {
  onOpenSettings: () => void;
};

export function TopBar({ onOpenSettings }: TopBarProps) {
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
    <header className="flex h-11 shrink-0 items-center justify-between border-b border-surface-700 bg-surface-900 px-3">
      <div className="flex items-center gap-3">
        <CodeOsLogo className="h-8 w-[124px] px-1.5" imageClassName="h-5 w-full" priority />
        <Button variant="primary" onClick={() => void openWorkspace()} disabled={loading} id="btn-open-folder">
          <FolderOpen size={16} />
          Open Folder
        </Button>
        <div className="max-w-[320px] md:max-w-[480px] truncate text-sm text-slate-350" id="workspace-title-display">
          {currentWorkspace?.name ?? "No workspace open"} {error ? `- ${error}` : ""}
        </div>
        {currentWorkspace && (
          <button
            id="btn-trust-status"
            className={`flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-semibold transition-all duration-200 ${
              restrictedMode
                ? "bg-amber-500/10 text-amber-400 border border-amber-500/25 hover:bg-amber-500/20"
                : "bg-emerald-500/10 text-emerald-400 border border-emerald-500/25 hover:bg-emerald-500/20"
            }`}
            onClick={async () => {
              if (restrictedMode) {
                if (confirm(`Trust workspace "${currentWorkspace.name}"? This allows full AI write capabilities.`)) {
                  await setWorkspaceTrust(currentWorkspace.path, true);
                }
              } else {
                if (confirm(`Disable trust for workspace "${currentWorkspace.name}"? This puts it in restricted read-only mode.`)) {
                  await setWorkspaceTrust(currentWorkspace.path, false);
                }
              }
            }}
            title={restrictedMode ? "Restricted Mode: Click to trust workspace" : "Trusted Workspace: Click to restrict"}
          >
            {restrictedMode ? <ShieldAlert size={12} /> : <ShieldCheck size={12} />}
            <span>{restrictedMode ? "Restricted" : "Trusted"}</span>
          </button>
        )}
        {currentWorkspace ? (
          <button
            className="rounded bg-surface-850 px-2 py-0.5 text-xs text-slate-400 hover:text-white"
            onClick={() => void runIndex()}
            title={indexStatus?.message ?? "Repository index status"}
          >
            {indexLabel}
          </button>
        ) : null}
      </div>

      <div className="flex items-center gap-1">
        <IconButton label="Refresh explorer" icon={<RotateCw size={15} />} onClick={() => void refreshTree()} disabled={!currentWorkspace} />
        <IconButton
          label="Close workspace"
          icon={<X size={15} />}
          onClick={() => {
            closeWorkspace();
            closeWorkspaceTabs();
          }}
          disabled={!currentWorkspace}
        />
        <div className="h-4 w-px bg-surface-700 mx-1" />
        <IconButton
          label="Open Settings"
          icon={<Settings size={15} />}
          onClick={onOpenSettings}
        />
      </div>
    </header>
  );
}
