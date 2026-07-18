import { useEffect, useState } from "react";
import { Eye, Info, RefreshCw, Layers, GitBranch, Terminal } from "lucide-react";
import { api } from "../../lib/api";
import { useWorkspaceStore } from "../../stores/workspaceStore";
import { useEditorStore } from "../../stores/editorStore";

type ContextData = {
  workspace: string;
  active_file: {
    path: string;
    name: string;
    content: string;
    selection: string | null;
  } | null;
  git_status: {
    branch?: string;
    dirty?: boolean;
    staged?: string[];
    unstaged?: string[];
    status?: string;
  } | null;
  dependencies: Array<{ name: string; version: string }>;
  open_tabs: Array<{ path: string; name: string }>;
  readme: string | null;
};

export function ContextPanel() {
  const [context, setContext] = useState<ContextData | null>(null);
  const [loading, setLoading] = useState(false);
  const workspace = useWorkspaceStore((state) => state.currentWorkspace);
  const activePath = useEditorStore((state) => state.activePath);
  const openFiles = useEditorStore((state) => state.openFiles);

  const fetchContext = async () => {
    if (!workspace) return;
    setLoading(true);
    try {
      const open_tabs = openFiles.map((file) => file.path);
      const data = await api.post<ContextData>("/api/ai/context", {
        workspace: workspace.path,
        active_path: activePath,
        open_tabs
      });
      setContext(data);
    } catch {
      setContext(null);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void fetchContext();
  }, [workspace?.path, activePath, openFiles.length]);

  if (!workspace) {
    return <div className="p-3 text-sm text-slate-500">Open a workspace to view context engine status.</div>;
  }

  return (
    <section className="grid h-full min-h-0 w-full min-w-0 grid-cols-1 grid-rows-[38px_1fr] border-b border-surface-700">
      <div className="flex items-center justify-between border-b border-surface-700 px-3 py-1">
        <div className="flex items-center gap-2">
          <Eye size={15} className="text-slate-400" />
          <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">AI Context Inspector</span>
        </div>
        <button onClick={() => void fetchContext()} className="text-slate-500 hover:text-white" disabled={loading}>
          <RefreshCw size={13} className={loading ? "animate-spin" : ""} />
        </button>
      </div>

      <div className="overflow-auto p-3 text-xs space-y-4 min-h-0">
        <p className="text-[10px] text-slate-500 italic">
          This panel shows the exact metadata and code segments that will be packaged and sent to the LLM when you chat.
        </p>

        {context ? (
          <div className="space-y-3">
            {/* Active File Context */}
            <div className="space-y-1">
              <span className="font-semibold text-slate-300 flex items-center gap-1">
                <Info size={12} className="text-accent-400" /> Active Editor Context
              </span>
              {context.active_file ? (
                <div className="bg-surface-850 p-2 rounded border border-surface-800 space-y-1 font-mono text-[10px]">
                  <div className="text-slate-200 truncate font-semibold">{context.active_file.name}</div>
                  <div className="text-slate-500 truncate">Path: {context.active_file.path}</div>
                  <div className="text-slate-400 mt-1">
                    Content size: {context.active_file.content.length} characters
                  </div>
                  {context.active_file.selection && (
                    <div className="mt-1 text-[9px] bg-accent-950/20 border border-accent-900/30 p-1 rounded text-accent-200 truncate">
                      Selection active: "{context.active_file.selection.slice(0, 40)}..."
                    </div>
                  )}
                </div>
              ) : (
                <div className="text-slate-500 italic font-mono text-[10px] p-1 bg-surface-850 rounded">No file open in editor.</div>
              )}
            </div>

            {/* Git Status Context */}
            <div className="space-y-1">
              <span className="font-semibold text-slate-300 flex items-center gap-1">
                <GitBranch size={12} className="text-accent-400" /> Workspace Git Context
              </span>
              {context.git_status ? (
                <div className="bg-surface-850 p-2 rounded border border-surface-800 space-y-1 font-mono text-[10px] text-slate-300">
                  {context.git_status.status ? (
                    <div className="text-slate-500 italic">{context.git_status.status}</div>
                  ) : (
                    <>
                      <div>Branch: <span className="text-emerald-400 font-semibold">{context.git_status.branch}</span></div>
                      <div>Dirty files: <span className="text-rose-400 font-semibold">{context.git_status.dirty ? "Yes" : "No"}</span></div>
                      {context.git_status.staged && context.git_status.staged.length > 0 && (
                        <div className="text-emerald-300">Staged: {context.git_status.staged.length} files</div>
                      )}
                      {context.git_status.unstaged && context.git_status.unstaged.length > 0 && (
                        <div className="text-rose-300">Unstaged: {context.git_status.unstaged.length} files</div>
                      )}
                    </>
                  )}
                </div>
              ) : (
                <div className="text-slate-500 italic font-mono text-[10px] p-1 bg-surface-850 rounded">Failed to read git state.</div>
              )}
            </div>

            {/* Open Tabs */}
            <div className="space-y-1">
              <span className="font-semibold text-slate-300 flex items-center gap-1">
                <Layers size={12} className="text-accent-400" /> Active Editor Tabs ({context.open_tabs.length})
              </span>
              {context.open_tabs.length > 0 ? (
                <div className="max-h-20 overflow-auto border border-surface-800 rounded bg-surface-900/30 p-1 space-y-0.5 font-mono text-[10px]">
                  {context.open_tabs.map((tab, idx) => (
                    <div key={idx} className="text-slate-400 px-1 py-0.5 hover:bg-surface-850 rounded truncate">
                      {tab.name}
                    </div>
                  ))}
                </div>
              ) : (
                <div className="text-slate-500 italic font-mono text-[10px] p-1 bg-surface-850 rounded">No tabs open.</div>
              )}
            </div>

            {/* Project Dependencies count */}
            <div className="space-y-1">
              <span className="font-semibold text-slate-300 flex items-center gap-1">
                <Terminal size={12} className="text-accent-400" /> Workspace Dependencies ({context.dependencies.length})
              </span>
              {context.dependencies.length > 0 ? (
                <div className="max-h-20 overflow-auto border border-surface-800 rounded bg-surface-900/30 p-1 space-y-0.5 font-mono text-[9px] text-slate-400">
                  {context.dependencies.slice(0, 10).map((dep, idx) => (
                    <div key={idx} className="flex justify-between items-center px-1">
                      <span className="truncate max-w-[100px]">{dep.name}</span>
                      <span className="text-slate-500">{dep.version || "latest"}</span>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="text-slate-500 italic font-mono text-[10px] p-1 bg-surface-850 rounded">No parsed package dependencies.</div>
              )}
            </div>
          </div>
        ) : (
          <div className="text-slate-500 text-center py-6">
            <RefreshCw className="mx-auto mb-2 animate-spin text-slate-600" size={20} />
            Gathering active code context...
          </div>
        )}
      </div>
    </section>
  );
}
