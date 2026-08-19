import { useEffect, useMemo, useState } from "react";
import { GitBranch, GitCommit, RefreshCw, Upload } from "lucide-react";

import { api } from "../../lib/api";
import { useWorkspaceStore } from "../../stores/workspaceStore";
import type { GitStatus } from "../../types/api";

type Commit = { sha: string; message: string; author: string; committed_at: string };

export function GitPanel() {
  const workspace = useWorkspaceStore((state) => state.currentWorkspace);
  const [status, setStatus] = useState<GitStatus | null>(null);
  const [history, setHistory] = useState<Commit[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [message, setMessage] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);

  const changedFiles = useMemo(() => {
    if (!status) return [];
    return [...new Set([...status.staged, ...status.unstaged, ...status.untracked])];
  }, [status]);

  const refresh = async () => {
    if (!workspace) return;
    try {
      const [nextStatus, nextHistory] = await Promise.all([
        api.get<GitStatus>("/api/git/status", { workspace: workspace.path }),
        api.get<Commit[]>("/api/git/history", { workspace: workspace.path, limit: 5 }),
      ]);
      setStatus(nextStatus);
      setHistory(nextHistory);
      setSelected((current) => new Set([...current].filter((file) => [...nextStatus.staged, ...nextStatus.unstaged, ...nextStatus.untracked].includes(file))));
    } catch (error) {
      setStatus(null);
      setHistory([]);
      setNotice(error instanceof Error ? error.message : "Git repository unavailable");
    }
  };

  useEffect(() => { void refresh(); }, [workspace?.path]);

  const toggle = (file: string) => setSelected((current) => {
    const next = new Set(current);
    next.has(file) ? next.delete(file) : next.add(file);
    return next;
  });

  const commit = async () => {
    if (!workspace || !message.trim() || selected.size === 0) return;
    setBusy(true);
    setNotice("");
    try {
      await api.post("/api/git/commit", { workspace: workspace.path, message: message.trim(), files: [...selected] });
      setMessage("");
      setSelected(new Set());
      setNotice("Commit created.");
      await refresh();
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Commit failed");
    } finally { setBusy(false); }
  };

  const push = async () => {
    if (!workspace) return;
    setBusy(true);
    setNotice("");
    try {
      await api.post("/api/git/push", undefined, { workspace: workspace.path });
      setNotice("Push completed.");
      await refresh();
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Push failed");
    } finally { setBusy(false); }
  };

  if (!workspace) return <section className="p-4 text-sm text-on-surface-variant">Open a workspace to use Source Control.</section>;

  return (
    <section className="flex h-full min-h-0 flex-col bg-surface-container-low text-sm">
      <header className="flex items-center justify-between border-b border-outline-variant/20 px-3 py-3">
        <span className="flex items-center gap-2 font-semibold"><GitBranch size={16} />Source Control</span>
        <button aria-label="Refresh Git status" onClick={() => void refresh()} className="text-on-surface-variant hover:text-on-surface"><RefreshCw size={16} /></button>
      </header>
      <div className="min-h-0 flex-1 overflow-auto p-3">
        <div className="mb-3 text-xs text-on-surface-variant">{status ? `Branch: ${status.branch}` : "No Git repository detected."}</div>
        {changedFiles.length > 0 && <div className="space-y-1">
          <div className="text-xs font-semibold uppercase text-on-surface-variant">Changes</div>
          {changedFiles.map((file) => <label key={file} className="flex cursor-pointer items-center gap-2 rounded px-1 py-1 hover:bg-surface-variant/30">
            <input type="checkbox" checked={selected.has(file)} onChange={() => toggle(file)} />
            <span className="truncate" title={file}>{file}</span>
          </label>)}
        </div>}
        {status && changedFiles.length === 0 && <p className="text-on-surface-variant">Working tree clean.</p>}
        <div className="mt-5">
          <div className="mb-1 text-xs font-semibold uppercase text-on-surface-variant">Recent commits</div>
          {history.length ? history.map((item) => <div key={item.sha} className="truncate py-1 text-xs" title={`${item.sha} ${item.message}`}><span className="text-primary">{item.sha}</span> {item.message}</div>) : <p className="text-xs text-on-surface-variant">No commits yet.</p>}
        </div>
      </div>
      <footer className="border-t border-outline-variant/20 p-3">
        <input value={message} onChange={(event) => setMessage(event.target.value)} placeholder="Commit message" className="mb-2 h-9 w-full rounded border border-outline-variant bg-surface px-2" />
        <div className="flex gap-2">
          <button disabled={busy || !message.trim() || selected.size === 0} onClick={() => void commit()} className="flex items-center gap-1 rounded bg-primary px-3 py-2 text-on-primary disabled:opacity-50"><GitCommit size={15} />Commit</button>
          <button disabled={busy} onClick={() => void push()} className="flex items-center gap-1 rounded border border-outline-variant px-3 py-2 disabled:opacity-50"><Upload size={15} />Push</button>
        </div>
        {notice && <p role="status" className="mt-2 text-xs text-on-surface-variant">{notice}</p>}
      </footer>
    </section>
  );
}
