import { useEffect, useState } from "react";
import { GitBranch, GitCommit, GitPullRequest, Plus, RefreshCw, Upload } from "lucide-react";

import { Button } from "../../components/ui/Button";
import { IconButton } from "../../components/ui/IconButton";
import { api } from "../../lib/api";
import { useWorkspaceStore } from "../../stores/workspaceStore";
import type { GitStatus } from "../../types/api";
export function GitPanel() {
  const [status, setStatus] = useState<GitStatus | null>(null);
  const [history, setHistory] = useState<{ sha: string; message: string; author: string; committed_at: string }[]>([]);
  const [diff, setDiff] = useState("");
  const [message, setMessage] = useState("");
  const [branchName, setBranchName] = useState("");
  const workspace = useWorkspaceStore((state) => state.currentWorkspace);

  const refresh = async () => {
    if (!workspace) return;
    try {
      setStatus(await api.get<GitStatus>("/api/git/status", { workspace: workspace.path }));
      setHistory(await api.get<{ sha: string; message: string; author: string; committed_at: string }[]>("/api/git/history", { workspace: workspace.path }));
    } catch {
      setStatus(null);
      setHistory([]);
    }
  };

  useEffect(() => {
    void refresh();
    if (!workspace) return;
    
    // 5-second status polling interval
    const interval = setInterval(() => {
      void refresh();
    }, 5000);
    
    return () => clearInterval(interval);
  }, [workspace?.path]);

  if (!workspace) {
    return (
      <section className="flex h-full flex-col items-center justify-center p-4 text-center space-y-2 select-none border-b border-surface-700 bg-surface-900">
        <GitBranch size={22} className="text-slate-600 mb-1 animate-pulse" />
        <span className="text-xs text-slate-500">Open a workspace to view Git status.</span>
      </section>
    );
  }

  return (
    <section className="grid h-full min-h-0 w-full min-w-0 grid-cols-1 grid-rows-[auto_38px_minmax(0,1fr)_auto]">
      <div className="bg-rose-950 text-white text-[10px] p-1 font-mono break-all select-all">
        DEBUG: ws={workspace?.path || "NULL"} msg={message || "EMPTY"} status={status ? "OK" : "NULL"}
      </div>
      <div className="flex items-center justify-between px-3 min-w-0 w-full">
        <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-slate-400">
          <GitBranch size={15} />
          Git
        </div>
        <IconButton label="Refresh Git" icon={<RefreshCw size={15} />} onClick={() => void refresh()} disabled={!workspace} />
      </div>
      <div className="min-h-0 min-w-0 w-full overflow-auto px-3 pb-2 text-sm">
        {status ? (
          <>
            <div className="mb-3 rounded-md bg-surface-850 px-3 py-2 text-slate-200 min-w-0 w-full">
              <div className="text-xs text-slate-500">Branch</div>
              <div className="flex gap-2 min-w-0 w-full">
                <select
                  className="h-8 min-w-0 flex-1 rounded border border-surface-700 bg-surface-900 text-xs text-slate-200 py-1 px-2 outline-none focus:border-accent-500 leading-normal"
                  value={status.branch}
                  onChange={async (event) => {
                    if (!workspace) return;
                    await api.post("/api/git/branch", { workspace: workspace.path, branch: event.target.value });
                    await refresh();
                  }}
                >
                  {status.branches.map((branch) => <option key={branch} className="bg-surface-900 text-slate-200">{branch}</option>)}
                </select>
              </div>
            </div>

            {/* Staged Changes */}
            {status.staged.length > 0 && (
              <div className="mb-3">
                <div className="text-[10px] font-bold text-slate-500 uppercase tracking-wider mb-1">Staged Changes</div>
                {status.staged.map((file) => (
                  <button
                    key={`staged-${file}`}
                    className="block w-full truncate border-b border-surface-800 py-1 text-left text-xs text-slate-400 hover:text-white"
                    onClick={async () => {
                      if (!workspace) return;
                      const response = await api.get<{ diff: string }>("/api/git/diff", { workspace: workspace.path, path: file });
                      setDiff(response.diff || "No staged changes for this file.");
                    }}
                  >
                    {file}
                  </button>
                ))}
              </div>
            )}

            {/* Unstaged Changes */}
            {status.unstaged.length > 0 && (
              <div className="mb-3">
                <div className="text-[10px] font-bold text-slate-500 uppercase tracking-wider mb-1">Unstaged Changes</div>
                {status.unstaged.map((file) => (
                  <button
                    key={`unstaged-${file}`}
                    className="block w-full truncate border-b border-surface-800 py-1 text-left text-xs text-slate-400 hover:text-white"
                    onClick={async () => {
                      if (!workspace) return;
                      const response = await api.get<{ diff: string }>("/api/git/diff", { workspace: workspace.path, path: file });
                      setDiff(response.diff || "No unstaged changes for this file.");
                    }}
                  >
                    {file}
                  </button>
                ))}
              </div>
            )}

            {/* Untracked Files */}
            {status.untracked.length > 0 && (
              <div className="mb-3">
                <div className="text-[10px] font-bold text-slate-500 uppercase tracking-wider mb-1">Untracked Files</div>
                {status.untracked.map((file) => (
                  <button
                    key={`untracked-${file}`}
                    className="block w-full truncate border-b border-surface-800 py-1 text-left text-xs text-slate-400 hover:text-white"
                    onClick={async () => {
                      if (!workspace) return;
                      const response = await api.get<{ diff: string }>("/api/git/diff", { workspace: workspace.path, path: file });
                      setDiff(response.diff || "No diff for untracked file.");
                    }}
                  >
                    {file}
                  </button>
                ))}
              </div>
            )}

            {!status.dirty ? <div className="text-slate-500">Working tree clean.</div> : null}
            {diff ? <pre className="mt-3 max-h-28 overflow-auto rounded bg-surface-950 p-2 font-mono text-[11px] text-slate-300">{diff}</pre> : null}
            {history.length ? (
              <div className="mt-3 space-y-1">
                <div className="text-xs uppercase tracking-wider text-slate-500">History</div>
                {history.slice(0, 5).map((item) => (
                  <div key={item.sha} className="truncate text-xs text-slate-400">{item.sha} {item.message}</div>
                ))}
              </div>
            ) : null}
          </>
        ) : (
          <div className="text-slate-500 truncate" title="No Git repository detected.">No Git repository detected.</div>
        )}
      </div>
      <div className="space-y-2 border-t border-surface-700 p-3 min-w-0 w-full">
        <input className="h-8 w-full min-w-0 rounded-md border-surface-700 bg-surface-850 text-sm text-slate-100" value={message} onChange={(event) => setMessage(event.target.value)} placeholder="Commit message" />
        <div className="flex gap-2 min-w-0 w-full">
          <input className="h-8 min-w-0 flex-1 rounded-md border-surface-700 bg-surface-850 text-sm text-slate-100" value={branchName} onChange={(event) => setBranchName(event.target.value)} placeholder="New branch" />
          <IconButton
            label="Create branch"
            icon={<Plus size={15} />}
            disabled={!workspace || !branchName.trim()}
            onClick={async () => {
              if (!workspace || !branchName.trim()) return;
              await api.post("/api/git/branch/create", { workspace: workspace.path, branch: branchName, checkout: true });
              setBranchName("");
              await refresh();
            }}
          />
        </div>
        <div className="flex flex-wrap gap-1.5 min-w-0 w-full">
          <Button
            variant="primary"
            onClick={async () => {
              alert(`Commit button clicked! workspace: ${workspace?.path}, message: ${message}`);
              if (!workspace || !message.trim()) return;
              try {
                await api.post("/api/git/commit", { workspace: workspace.path, message });
                alert("Commit success!");
                setMessage("");
                await refresh();
              } catch (e: any) {
                alert("Commit failed: " + e.message);
              }
            }}
            disabled={!workspace || !message.trim()}
          >
            <GitCommit size={15} />
            Commit
          </Button>
          <IconButton label="Pull" icon={<GitPullRequest size={15} />} onClick={async () => {
            alert(`Pull clicked! workspace: ${workspace?.path}`);
            if (!workspace) return;
            try {
              await api.post("/api/git/pull", undefined, { workspace: workspace.path });
              alert("Pull success!");
            } catch (e: any) {
              alert("Pull failed: " + e.message);
            }
          }} disabled={!workspace} />
          <IconButton label="Push" icon={<Upload size={15} />} onClick={async () => {
            alert(`Push clicked! workspace: ${workspace?.path}`);
            if (!workspace) return;
            try {
              await api.post("/api/git/push", undefined, { workspace: workspace.path });
              alert("Push success!");
            } catch (e: any) {
              alert("Push failed: " + e.message);
            }
          }} disabled={!workspace} />
        </div>
      </div>
    </section>
  );
}

