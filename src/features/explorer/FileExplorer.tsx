import { ChevronRight, Copy, File, Folder, FolderOpen, FolderPlus, MoreHorizontal, Plus, RefreshCw, Trash2, X } from "lucide-react";
import { useEffect, useMemo, useState, type ReactNode } from "react";

import { Button } from "../../components/ui/Button";
import { IconButton } from "../../components/ui/IconButton";
import { api } from "../../lib/api";
import { useEditorStore } from "../../stores/editorStore";
import { useWorkspaceStore } from "../../stores/workspaceStore";
import type { FileNode } from "../../types/api";

type ContextState = {
  node: FileNode;
  x: number;
  y: number;
} | null;

function joinPath(parent: string, child: string): string {
  return `${parent}${parent.includes("\\") ? "\\" : "/"}${child}`;
}

function TreeNode({
  node,
  depth,
  expanded,
  onToggle,
  onContext,
  editingPath,
  renameValue,
  onStartRename,
  onRenameChange,
  onRenameKeyDown,
  onRenameBlur
}: {
  node: FileNode;
  depth: number;
  expanded: Set<string>;
  onToggle: (path: string) => void;
  onContext: (state: ContextState) => void;
  editingPath: string | null;
  renameValue: string;
  onStartRename: (path: string, name: string) => void;
  onRenameChange: (val: string) => void;
  onRenameKeyDown: (e: React.KeyboardEvent, node: FileNode) => void;
  onRenameBlur: (node: FileNode) => void;
}) {
  const openFile = useEditorStore((state) => state.openFile);
  const isDirectory = node.type === "directory";
  const isExpanded = expanded.has(node.path);
  const isEditing = node.path === editingPath;

  return (
    <div>
      <div
        className="group flex h-7 items-center gap-1 rounded px-2 text-sm text-slate-300 hover:bg-surface-800 hover:text-white"
        style={{ paddingLeft: 8 + depth * 14 }}
        draggable={!isEditing}
        onDragStart={(event) => event.dataTransfer.setData("text/plain", node.path)}
        onDrop={(event) => {
          event.preventDefault();
          window.dispatchEvent(new CustomEvent("code-os:file-drop", { detail: { source: event.dataTransfer.getData("text/plain"), target: node.path } }));
        }}
        onDragOver={(event) => isDirectory && event.preventDefault()}
        onClick={() => {
          if (isEditing) return;
          useWorkspaceStore.getState().selectWorkspaceForPath(node.path);
          if (isDirectory) onToggle(node.path);
          else void openFile(node.path);
        }}
        onContextMenu={(event) => {
          event.preventDefault();
          onContext({ node, x: event.clientX, y: event.clientY });
        }}
      >
        {isDirectory ? <ChevronRight size={13} className={isExpanded ? "rotate-90 transition-transform" : "transition-transform"} /> : <span className="w-[13px]" />}
        {isDirectory ? (
          isExpanded ? <FolderOpen size={15} className="text-accent-500" /> : <Folder size={15} className="text-accent-500" />
        ) : (
          <File size={15} className="text-slate-400" />
        )}
        {isEditing ? (
          <input
            className="h-5 flex-1 min-w-0 bg-surface-950 border border-accent-500 rounded px-1 text-xs text-white focus:outline-none select-text"
            value={renameValue}
            onChange={(e) => onRenameChange(e.target.value)}
            onKeyDown={(e) => onRenameKeyDown(e, node)}
            onBlur={() => onRenameBlur(node)}
            autoFocus
            onClick={(e) => e.stopPropagation()}
          />
        ) : (
          <span
            className="min-w-0 flex-1 truncate"
            onDoubleClick={(e) => {
              e.stopPropagation();
              onStartRename(node.path, node.name);
            }}
          >
            {node.name}
          </span>
        )}
        <button
          title="More actions"
          className="hidden text-slate-400 hover:text-white group-hover:block"
          onClick={(event) => {
            event.stopPropagation();
            onContext({ node, x: event.clientX, y: event.clientY });
          }}
        >
          <MoreHorizontal size={14} />
        </button>
      </div>
      {isDirectory && isExpanded ? (
        node.children?.map((child) => (
          <TreeNode
            key={child.path}
            node={child}
            depth={depth + 1}
            expanded={expanded}
            onToggle={onToggle}
            onContext={onContext}
            editingPath={editingPath}
            renameValue={renameValue}
            onStartRename={onStartRename}
            onRenameChange={onRenameChange}
            onRenameKeyDown={onRenameKeyDown}
            onRenameBlur={onRenameBlur}
          />
        ))
      ) : null}
    </div>
  );
}

export function FileExplorer() {
  const workspace = useWorkspaceStore((state) => state.currentWorkspace);
  const activeWorkspaces = useWorkspaceStore((state) => state.activeWorkspaces);
  const fileTrees = useWorkspaceStore((state) => state.fileTrees);
  const closeWorkspace = useWorkspaceStore((state) => state.closeWorkspace);
  const openWorkspace = useWorkspaceStore((state) => state.openWorkspace);
  const tree = useWorkspaceStore((state) => state.fileTree);
  const refreshTree = useWorkspaceStore((state) => state.refreshTree);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [context, setContext] = useState<ContextState>(null);
  
  // Inline rename state
  const [editingPath, setEditingPath] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");

  const expandedWithRoot = expanded;

  // Auto-expand root folder when a workspace is added
  useEffect(() => {
    setExpanded((current) => {
      const next = new Set(current);
      let changed = false;
      activeWorkspaces.forEach((ws) => {
        const t = fileTrees[ws.path];
        if (t && !next.has(t.path)) {
          next.add(t.path);
          changed = true;
        }
      });
      return changed ? next : current;
    });
  }, [activeWorkspaces, fileTrees]);

  const handleRenameSubmit = async (node: FileNode) => {
    const val = renameValue.trim();
    if (!val || val === node.name) {
      setEditingPath(null);
      return;
    }
    useWorkspaceStore.getState().selectWorkspaceForPath(node.path);
    const activeWs = useWorkspaceStore.getState().currentWorkspace;
    if (!activeWs) {
      setEditingPath(null);
      return;
    }
    try {
      await api.post("/api/files/rename", { workspace: activeWs.path, path: node.path, new_name: val });
      await refreshTree();
    } catch (error) {
      alert(error instanceof Error ? error.message : "Rename failed");
    } finally {
      setEditingPath(null);
    }
  };

  const handleRenameKeyDown = (e: React.KeyboardEvent, node: FileNode) => {
    if (e.key === "Enter") {
      void handleRenameSubmit(node);
    } else if (e.key === "Escape") {
      setEditingPath(null);
    }
  };

  const runAction = async (action: string, node: FileNode) => {
    useWorkspaceStore.getState().selectWorkspaceForPath(node.path);
    const activeWs = useWorkspaceStore.getState().currentWorkspace;
    if (!activeWs) return;
    try {
      if (action === "new-file" || action === "new-folder") {
        const name = prompt(action === "new-file" ? "File name" : "Folder name");
        if (!name) return;
        const parent = node.type === "directory" ? node.path : node.path.replace(/[\\/][^\\/]+$/, "");
        await api.post("/api/files/create", { workspace: activeWs.path, path: joinPath(parent, name), type: action === "new-file" ? "file" : "directory" });
      }
      if (action === "rename") {
        setEditingPath(node.path);
        setRenameValue(node.name);
        setContext(null);
        return; // Don't close context and resolve immediately
      }
      if (action === "delete" && confirm(`Delete ${node.name}?`)) {
        await api.post("/api/files/delete", { workspace: activeWs.path, path: node.path });
      }
      if (action === "duplicate") {
        await api.post("/api/files/duplicate", { workspace: activeWs.path, path: node.path });
      }
      if (action === "reveal") {
        await window.codeOS?.revealInSystemExplorer(node.path);
      }
      if (action === "copy-path") {
        await (window.codeOS?.copyText(node.path) ?? navigator.clipboard.writeText(node.path));
      }
      await refreshTree();
    } catch (error) {
      alert(error instanceof Error ? error.message : "Explorer action failed");
    } finally {
      setContext(null);
    }
  };

  useEffect(() => {
    const listener = async (event: Event) => {
      const { source, target } = (event as CustomEvent<{ source: string; target: string }>).detail;
      useWorkspaceStore.getState().selectWorkspaceForPath(target);
      const activeWs = useWorkspaceStore.getState().currentWorkspace;
      if (!activeWs) return;
      const treeNode = fileTrees[activeWs.path];
      const targetNode = findNode(treeNode ?? null, target);
      if (!source || !targetNode || targetNode.type !== "directory") return;
      await api.post("/api/files/move", { workspace: activeWs.path, source, destination: joinPath(targetNode.path, source.split(/[\\/]/).pop() ?? "moved") });
      await refreshTree();
    };
    window.addEventListener("code-os:file-drop", listener);
    return () => window.removeEventListener("code-os:file-drop", listener);
  }, [workspace?.path, activeWorkspaces, fileTrees, refreshTree]);

  return (
    <section className="relative flex h-full min-h-0 w-full min-w-0 flex-col border-b border-surface-700" onClick={() => setContext(null)}>
      <div className="flex h-10 shrink-0 items-center justify-between px-3 min-w-0 w-full">
        <div className="text-xs font-semibold uppercase tracking-wider text-slate-400">Explorer</div>
        <div className="flex gap-0.5">
          <IconButton label="Add folder to workspace" icon={<FolderPlus size={15} />} onClick={() => void openWorkspace()} />
          <IconButton label="Refresh tree" icon={<RefreshCw size={15} />} onClick={() => void refreshTree()} disabled={activeWorkspaces.length === 0} />
        </div>
      </div>
      <div className="min-h-0 flex-1 min-w-0 w-full overflow-auto px-1 pb-2">
        {activeWorkspaces.length > 0 ? (
          activeWorkspaces.map((ws) => {
            const treeNode = fileTrees[ws.path];
            if (!treeNode) return null;
            return (
              <div key={ws.path} className="mb-4">
                <div className="flex h-7 items-center justify-between px-2 text-xs font-bold uppercase tracking-wider text-slate-500 bg-surface-850 rounded mb-1">
                  <span className="truncate" title={ws.path}>{ws.name}</span>
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      closeWorkspace(ws.path);
                    }}
                    className="text-slate-500 hover:text-white"
                    title="Remove folder from workspace"
                  >
                    <X size={12} />
                  </button>
                </div>
                <TreeNode
                  node={treeNode}
                  depth={0}
                  expanded={expandedWithRoot}
                  onToggle={(path) => setExpanded((current) => {
                    const next = new Set(current);
                    if (next.has(path)) next.delete(path);
                    else next.add(path);
                    return next;
                  })}
                  onContext={setContext}
                  editingPath={editingPath}
                  renameValue={renameValue}
                  onStartRename={(path, name) => {
                    setEditingPath(path);
                    setRenameValue(name);
                  }}
                  onRenameChange={setRenameValue}
                  onRenameKeyDown={handleRenameKeyDown}
                  onRenameBlur={handleRenameSubmit}
                />
              </div>
            );
          })
        ) : (
          <div className="flex h-full flex-col items-center justify-center p-4 text-center space-y-2.5">
            <span className="text-xs text-slate-500 select-none">No active workspace folder open.</span>
            <Button
              variant="primary"
              onClick={() => void openWorkspace()}
              className="h-8 text-xs font-semibold px-3"
            >
              <FolderPlus size={13} /> Open Folder
            </Button>
          </div>
        )}
      </div>
      {context ? (
        <div className="fixed z-50 w-56 rounded-md border border-surface-700 bg-surface-900 py-1 text-sm shadow-xl" style={{ left: context.x, top: context.y }} onClick={(event) => event.stopPropagation()}>
          <MenuButton icon={<Plus size={14} />} label="New File" onClick={() => void runAction("new-file", context.node)} />
          <MenuButton icon={<FolderPlus size={14} />} label="New Folder" onClick={() => void runAction("new-folder", context.node)} />
          <MenuButton icon={<MoreHorizontal size={14} />} label="Rename" onClick={() => void runAction("rename", context.node)} />
          <MenuButton icon={<Copy size={14} />} label="Duplicate" onClick={() => void runAction("duplicate", context.node)} />
          <MenuButton icon={<FolderOpen size={14} />} label="Reveal in System Explorer" onClick={() => void runAction("reveal", context.node)} />
          <MenuButton icon={<Copy size={14} />} label="Copy Path" onClick={() => void runAction("copy-path", context.node)} />
          <MenuButton icon={<Trash2 size={14} />} label="Delete" danger onClick={() => void runAction("delete", context.node)} />
        </div>
      ) : null}
    </section>
  );
}

function MenuButton({ icon, label, danger, onClick }: { icon: ReactNode; label: string; danger?: boolean; onClick: () => void }) {
  return (
    <button className={`flex w-full items-center gap-2 px-3 py-2 text-left hover:bg-surface-800 ${danger ? "text-danger" : "text-slate-200"}`} onClick={onClick}>
      {icon}
      {label}
    </button>
  );
}

function findNode(node: FileNode | null, path: string): FileNode | null {
  if (!node) return null;
  if (node.path === path) return node;
  for (const child of node.children ?? []) {
    const found = findNode(child, path);
    if (found) return found;
  }
  return null;
}

