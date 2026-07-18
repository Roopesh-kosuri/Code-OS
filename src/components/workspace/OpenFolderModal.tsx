import { useEffect, useState } from "react";
import { Folder, FolderOpen, X, RefreshCw, ChevronRight } from "lucide-react";
import { useWorkspaceStore } from "../../stores/workspaceStore";
import { Button } from "../ui/Button";

interface OpenFolderModalProps {
  onClose: () => void;
}

export function OpenFolderModal({ onClose }: OpenFolderModalProps) {
  const [pathInput, setPathInput] = useState("");
  const openWorkspace = useWorkspaceStore((s) => s.openWorkspace);
  const recentWorkspaces = useWorkspaceStore((s) => s.recentWorkspaces);
  const loadRecent = useWorkspaceStore((s) => s.loadRecent);
  const loading = useWorkspaceStore((s) => s.loading);
  const error = useWorkspaceStore((s) => s.error);

  useEffect(() => {
    void loadRecent();
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [loadRecent, onClose]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!pathInput.trim()) return;
    await openWorkspace(pathInput.trim());
    if (!useWorkspaceStore.getState().error) {
      onClose();
    }
  };

  const handleRecentClick = async (path: string) => {
    await openWorkspace(path);
    if (!useWorkspaceStore.getState().error) {
      onClose();
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-surface-950/70 p-4 backdrop-blur-sm select-text">
      <div
        className="w-full max-w-md rounded-xl border border-surface-700 bg-surface-900 shadow-2xl overflow-hidden flex flex-col max-h-[90vh]"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-surface-750 px-4 py-3 select-none">
          <div className="flex items-center gap-2 text-xs font-bold uppercase tracking-wider text-slate-350">
            <FolderOpen size={16} className="text-accent-500" />
            Open Folder to Workspace
          </div>
          <button
            onClick={onClose}
            className="text-slate-500 hover:text-white transition-colors"
            title="Close modal"
          >
            <X size={16} />
          </button>
        </div>

        {/* Modal content */}
        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          {error && (
            <div className="rounded-lg border border-danger/45 bg-danger/5 p-2.5 text-xs text-danger">
              {error}
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-3">
            <div>
              <label className="text-[10px] text-slate-500 mb-1 block font-semibold uppercase tracking-wider select-none">
                Enter Absolute Directory Path
              </label>
              <input
                type="text"
                placeholder="e.g. C:/Users/Name/Projects/my-app"
                value={pathInput}
                onChange={(e) => setPathInput(e.target.value)}
                className="w-full rounded bg-surface-950 border border-surface-700 px-3 py-2 text-xs text-slate-200 placeholder:text-slate-600 focus:outline-none focus:border-accent-500 transition-colors"
                autoFocus
                disabled={loading}
              />
            </div>
            <div className="flex justify-end gap-2 pt-1 select-none">
              <Button type="button" variant="ghost" onClick={onClose} disabled={loading}>
                Cancel
              </Button>
              <Button type="submit" variant="primary" disabled={loading || !pathInput.trim()}>
                {loading ? <><RefreshCw size={13} className="animate-spin" /> Opening...</> : "Open Folder"}
              </Button>
            </div>
          </form>

          {/* Recent Workspaces section */}
          {recentWorkspaces.length > 0 && (
            <div className="space-y-2 border-t border-surface-750/70 pt-3.5">
              <div className="text-[10px] text-slate-500 font-semibold uppercase tracking-wider select-none">
                Recent Folders
              </div>
              <div className="space-y-1.5 max-h-48 overflow-y-auto">
                {recentWorkspaces.map((ws) => (
                  <button
                    key={ws.path}
                    type="button"
                    onClick={() => void handleRecentClick(ws.path)}
                    disabled={loading}
                    className="w-full flex items-center justify-between p-2 rounded-lg bg-surface-950/40 border border-surface-850 hover:bg-surface-800/50 hover:border-surface-700 text-left transition-all group"
                  >
                    <div className="flex items-center gap-2.5 min-w-0">
                      <Folder size={15} className="text-slate-500 group-hover:text-accent-500 transition-colors shrink-0" />
                      <div className="min-w-0">
                        <div className="text-xs font-semibold text-slate-250 truncate group-hover:text-white">
                          {ws.name}
                        </div>
                        <div className="text-[10px] text-slate-600 font-mono truncate max-w-[340px]">
                          {ws.path}
                        </div>
                      </div>
                    </div>
                    <ChevronRight size={13} className="text-slate-700 group-hover:text-slate-350 transition-colors shrink-0" />
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
