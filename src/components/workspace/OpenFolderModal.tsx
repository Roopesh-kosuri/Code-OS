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
    // Close modal on success: either workspace opened directly (no error)
    // or trust dialog is pending (pendingWorkspacePath set, isOpeningFolder cleared)
    const state = useWorkspaceStore.getState();
    if (!state.error) {
      onClose();
    }
  };

  const handleRecentClick = async (path: string) => {
    await openWorkspace(path);
    const state = useWorkspaceStore.getState();
    if (!state.error) {
      onClose();
    }
  };


  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-md animate-in fade-in duration-200 select-text">
      <div
        className="w-full max-w-md rounded-2xl border border-white/10 bg-[#12141a]/95 backdrop-blur-2xl shadow-[0_25px_60px_rgba(0,0,0,0.85)] ring-1 ring-white/10 overflow-hidden flex flex-col max-h-[90vh] animate-popover-in"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-white/10 px-5 py-3.5 select-none bg-[#0e1017]/60">
          <div className="flex items-center gap-2.5 text-xs font-bold uppercase tracking-wider text-on-surface">
            <FolderOpen size={16} className="text-primary shrink-0" />
            <span>Open Folder to Workspace</span>
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded-lg text-on-surface-variant hover:text-on-surface hover:bg-white/5 transition-colors cursor-pointer"
            title="Close modal"
          >
            <X size={15} />
          </button>
        </div>

        {/* Modal content */}
        <div className="flex-1 overflow-y-auto p-5 space-y-4">
          {error && (
            <div className="rounded-xl border border-error/30 bg-error/10 p-3 text-xs text-error shadow-sm">
              {error}
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-3.5">
            <div>
              <label className="text-[10px] text-on-surface-variant/70 mb-1.5 block font-bold uppercase tracking-wider select-none">
                Enter Absolute Directory Path
              </label>
              <input
                type="text"
                placeholder="e.g. C:/Users/Name/Projects/my-app"
                value={pathInput}
                onChange={(e) => setPathInput(e.target.value)}
                className="w-full rounded-xl bg-[#0a0c12] border border-white/10 px-3.5 py-2.5 text-xs font-mono text-on-surface placeholder:text-on-surface-variant/40 focus:outline-none focus:border-primary/50 focus:ring-1 focus:ring-primary/20 transition-all shadow-inner"
                autoFocus
                disabled={loading}
              />
            </div>
            <div className="flex justify-end items-center gap-2 pt-1 select-none">
              <button
                type="button"
                onClick={onClose}
                disabled={loading}
                className="px-4 py-2 rounded-xl text-xs font-semibold text-on-surface-variant hover:text-on-surface hover:bg-white/5 transition-all cursor-pointer disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={loading || !pathInput.trim()}
                className="px-5 py-2 rounded-xl bg-primary text-[#001f24] font-ui-label-bold text-xs font-bold hover:bg-primary/90 hover:shadow-[0_0_15px_rgba(0,218,243,0.35)] active:scale-[0.98] transition-all flex items-center gap-2 shadow-sm cursor-pointer disabled:opacity-50"
              >
                {loading ? (
                  <>
                    <RefreshCw size={13} className="animate-spin" /> Opening...
                  </>
                ) : (
                  "Open Folder"
                )}
              </button>
            </div>
          </form>

          {/* Recent Workspaces section */}
          {(recentWorkspaces || []).length > 0 && (
            <div className="space-y-2 border-t border-white/10 pt-4">
              <div className="text-[10px] text-on-surface-variant/70 font-bold uppercase tracking-wider select-none mb-1.5">
                Recent Folders
              </div>
              <div className="space-y-2 max-h-52 overflow-y-auto pr-0.5">
                {recentWorkspaces.map((ws) => (
                  <button
                    key={ws.path}
                    type="button"
                    onClick={() => void handleRecentClick(ws.path)}
                    disabled={loading}
                    title={ws.path}
                    className="w-full flex items-center justify-between p-2.5 rounded-xl bg-[#161822]/60 border border-white/5 hover:bg-[#1f2230] hover:border-white/15 text-left transition-all duration-150 group cursor-pointer shadow-sm hover:translate-y-[-1px] active:scale-[0.99]"
                  >
                    <div className="flex items-center gap-3 min-w-0 flex-1">
                      <div className="p-1.5 rounded-lg bg-white/5 border border-white/5 text-on-surface-variant group-hover:text-primary group-hover:bg-primary/10 group-hover:border-primary/20 transition-colors shrink-0">
                        <Folder size={14} />
                      </div>
                      <div className="min-w-0 flex-1">
                        <div className="text-xs font-semibold text-on-surface group-hover:text-primary transition-colors truncate">
                          {ws.name}
                        </div>
                        <div className="text-[10px] text-on-surface-variant/60 font-mono truncate max-w-[280px]">
                          {ws.path}
                        </div>
                      </div>
                    </div>
                    <ChevronRight size={14} className="text-on-surface-variant/40 group-hover:text-on-surface transition-colors shrink-0 ml-2" />
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
