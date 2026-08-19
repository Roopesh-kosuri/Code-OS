import { ChevronRight, Copy, FileCode, Folder, FolderOpen, FolderPlus, MoreHorizontal, Plus, RefreshCw, Trash2, X, FilePlus } from "lucide-react";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { api } from "../../lib/api";
import { useEditorStore } from "../../stores/editorStore";
import { useWorkspaceStore } from "../../stores/workspaceStore";
import type { FileNode } from "../../types/api";
import { FileIcon } from "../../components/ui/FileIcon";

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
  onRenameBlur,
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
  const activePath = useEditorStore((state) => state.activePath);
  const isDirectory = node.type === "directory";
  const isExpanded = expanded.has(node.path);
  const isEditing = node.path === editingPath;
  const isActive = node.path === activePath;

  return (
    <div>
      <div
        role="treeitem"
        data-testid="file-tree-item"
        className={`group flex h-7 items-center gap-1.5 px-2 font-code-sm text-code-sm cursor-pointer transition-all ${
          isActive
            ? "bg-primary/10 text-primary border-r-2 border-primary font-semibold"
            : "text-on-surface-variant hover:bg-surface-variant/40 hover:text-on-surface"
        }`}
        style={{ paddingLeft: 8 + depth * 12 }}
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
        {isDirectory ? (
          <span className="material-symbols-outlined text-[15px] text-on-surface-variant/60 shrink-0">
            {isExpanded ? "keyboard_arrow_down" : "keyboard_arrow_right"}
          </span>
        ) : (
          <span className="w-[15px] shrink-0" />
        )}

        <FileIcon filename={node.name} isDirectory={isDirectory} isOpen={isExpanded} size={16} />

        {isEditing ? (
          <input
            className="h-5 flex-1 min-w-0 bg-[#131315] border border-primary-container rounded px-1.5 text-xs text-on-surface focus:outline-none select-text font-mono"
            value={renameValue}
            onChange={(e) => onRenameChange(e.target.value)}
            onKeyDown={(e) => onRenameKeyDown(e, node)}
            onBlur={() => onRenameBlur(node)}
            autoFocus
            onClick={(e) => e.stopPropagation()}
          />
        ) : (
          <span
            className="min-w-0 flex-1 truncate font-mono text-[11px] ml-0.5"
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
          className="hidden text-on-surface-variant hover:text-on-surface group-hover:block p-0.5 rounded"
          onClick={(event) => {
            event.stopPropagation();
            onContext({ node, x: event.clientX, y: event.clientY });
          }}
        >
          <MoreHorizontal size={12} />
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
  const refreshTree = useWorkspaceStore((state) => state.refreshTree);

  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [context, setContext] = useState<ContextState>(null);
  
  const [editingPath, setEditingPath] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");

  const expandedWithRoot = expanded;

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
        const name = prompt(action === "new-file" ? "Enter file name (e.g. main.cpp, app.py, index.html):" : "Enter folder name:");
        if (!name) return;
        const parent = node.type === "directory" ? node.path : node.path.replace(/[\\/][^\\/]+$/, "");
        const targetPath = joinPath(parent, name);
        await api.post("/api/files/create", { workspace: activeWs.path, path: targetPath, type: action === "new-file" ? "file" : "directory" });
        setExpanded((prev) => new Set([...prev, parent, ...(action === "new-folder" ? [targetPath] : [])]));
        await refreshTree();
        if (action === "new-file") {
          void useEditorStore.getState().openFile(targetPath);
        }
      }
      if (action === "rename") {
        setEditingPath(node.path);
        setRenameValue(node.name);
        setContext(null);
        return;
      }
      if (action === "delete") {
        if (confirm(`Are you sure you want to delete ${node.name}?`)) {
          await api.post("/api/files/delete", { workspace: activeWs.path, path: node.path });
          useEditorStore.getState().closeFile(node.path);
          await refreshTree();
        }
      }
      if (action === "duplicate") {
        await api.post("/api/files/duplicate", { workspace: activeWs.path, path: node.path });
        await refreshTree();
      }
      if (action === "reveal") {
        if (window.codeOS?.revealInSystemExplorer) {
          await window.codeOS.revealInSystemExplorer(node.path);
        } else {
          await api.post("/api/files/reveal", { workspace: activeWs.path, path: node.path });
        }
      }
      if (action === "copy-path") {
        try {
          await navigator.clipboard.writeText(node.path);
        } catch {
          window.codeOS?.copyText(node.path);
        }
      }
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
    <section
      role="tree"
      data-testid="file-tree-panel"
      className="relative flex h-full min-h-0 w-full min-w-0 flex-col bg-surface-container-low text-on-surface select-none font-ui-label-reg text-ui-label-reg"
      onClick={() => setContext(null)}
    >
      {/* ── Explorer Header ──────────────────────────────────────────────── */}
      <div className="px-3 py-2 border-b border-surface-variant flex justify-between items-center bg-surface-container/50 shrink-0">
        <h2 className="font-ui-label-bold text-ui-label-bold text-on-surface uppercase tracking-wider text-[11px] truncate">
          {workspace?.name ?? "WORKSPACE"}
        </h2>
        <div className="flex items-center gap-1.5 text-on-surface-variant">
          <button
            onClick={() => {
              if (activeWorkspaces.length > 0) {
                const root = fileTrees[activeWorkspaces[0].path];
                if (root) void runAction("new-file", root);
              }
            }}
            className="p-1 hover:text-primary hover:bg-white/5 rounded transition-colors cursor-pointer"
            title="New File"
          >
            <FilePlus size={14} />
          </button>
          <button
            onClick={() => {
              if (activeWorkspaces.length > 0) {
                const root = fileTrees[activeWorkspaces[0].path];
                if (root) void runAction("new-folder", root);
              }
            }}
            className="p-1 hover:text-primary hover:bg-white/5 rounded transition-colors cursor-pointer"
            title="New Folder"
          >
            <FolderPlus size={14} />
          </button>
          <button
            onClick={() => void refreshTree()}
            className="p-1 hover:text-primary hover:bg-white/5 rounded transition-colors cursor-pointer"
            title="Refresh Explorer"
          >
            <RefreshCw size={13} />
          </button>
        </div>
      </div>

      {/* ── File Tree Scroll Area ────────────────────────────────────────── */}
      <div className="min-h-0 flex-1 min-w-0 w-full overflow-auto py-2 font-code-sm text-code-sm text-on-surface-variant">
        {activeWorkspaces.length > 0 ? (
          activeWorkspaces.map((ws) => {
            const treeNode = fileTrees[ws.path];
            if (!treeNode) return null;
            return (
              <div key={ws.path} className="mb-3">
                <div className="mb-1 flex h-6 items-center justify-between px-3 text-[10px] font-bold uppercase tracking-wider text-outline-variant bg-surface-container-high/40">
                  <span className="truncate" title={ws.path}>{ws.name}</span>
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      closeWorkspace(ws.path);
                    }}
                    className="text-on-surface-variant hover:text-on-surface p-0.5 rounded hover:bg-white/10"
                    title="Remove folder from workspace"
                  >
                    <X size={11} />
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
          <div className="flex h-full flex-col items-center justify-center p-6 text-center space-y-3">
            <span className="text-xs text-on-surface-variant/50">No active workspace folder.</span>
            <button
              onClick={() => void openWorkspace()}
              className="bg-primary-container text-[#001f24] font-ui-label-bold text-xs px-4 py-2 rounded-full flex items-center gap-1.5 shadow-sm hover:bg-primary-fixed transition-colors cursor-pointer"
            >
              <FolderPlus size={13} />
              <span>Open Folder</span>
            </button>
          </div>
        )}
      </div>

      {/* Context Menu */}
      {context ? (
        <div
          className="fixed z-50 w-52 rounded-xl border border-surface-container-high bg-[#1e1f24] py-1.5 text-xs shadow-2xl text-on-surface"
          style={{ left: context.x, top: context.y }}
          onClick={(e) => e.stopPropagation()}
        >
          <MenuButton icon={<Plus size={13} />} label="New File" onClick={() => void runAction("new-file", context.node)} />
          <MenuButton icon={<FolderPlus size={13} />} label="New Folder" onClick={() => void runAction("new-folder", context.node)} />
          <MenuButton icon={<MoreHorizontal size={13} />} label="Rename" onClick={() => void runAction("rename", context.node)} />
          <MenuButton icon={<Copy size={13} />} label="Duplicate" onClick={() => void runAction("duplicate", context.node)} />
          <MenuButton icon={<FolderOpen size={13} />} label="Reveal in Explorer" onClick={() => void runAction("reveal", context.node)} />
          <MenuButton icon={<Copy size={13} />} label="Copy Path" onClick={() => void runAction("copy-path", context.node)} />
          <div className="h-px bg-surface-variant my-1" />
          <MenuButton icon={<Trash2 size={13} />} label="Delete" danger onClick={() => void runAction("delete", context.node)} />
        </div>
      ) : null}
    </section>
  );
}

function MenuButton({ icon, label, danger, onClick }: { icon: ReactNode; label: string; danger?: boolean; onClick: () => void }) {
  return (
    <button
      className={`flex w-full items-center gap-2.5 px-3 py-1.5 text-left transition-colors cursor-pointer ${
        danger ? "text-error hover:bg-error/10" : "text-on-surface hover:bg-white/5"
      }`}
      onClick={onClick}
    >
      {icon}
      <span>{label}</span>
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
