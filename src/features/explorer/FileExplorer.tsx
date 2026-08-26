import { ChevronRight, Copy, FileCode, Folder, FolderOpen, FolderPlus, MoreHorizontal, Plus, RefreshCw, Trash2, X, FilePlus, AlertCircle, ShieldAlert } from "lucide-react";
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
  const cleanParent = parent.replace(/[\\/]+$/, "");
  const cleanChild = child.replace(/^[\\/]+/, "");
  const separator = parent.includes("\\") ? "\\" : "/";
  return `${cleanParent}${separator}${cleanChild}`;
}

const INVALID_CHARS = /[*?"<>|:\0]/;

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
          <span className="truncate flex-1 select-none">{node.name}</span>
        )}
      </div>

      {isDirectory && isExpanded ? (
        node.children && node.children.length > 0 ? (
          node.children.map((child) => (
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
        ) : (
          <div className="text-[10.5px] text-on-surface-variant/40 italic py-1" style={{ paddingLeft: 24 + depth * 12 }}>
            (empty)
          </div>
        )
      ) : null}
    </div>
  );
}

export function FileExplorer() {
  const workspace = useWorkspaceStore((state) => state.currentWorkspace);
  const activeWorkspaces = useWorkspaceStore((state) => state.activeWorkspaces);
  const fileTrees = useWorkspaceStore((state) => state.fileTrees);
  const fallbackTree = useWorkspaceStore((state) => state.fileTree);
  const closeWorkspace = useWorkspaceStore((state) => state.closeWorkspace);
  const openWorkspace = useWorkspaceStore((state) => state.openWorkspace);
  const refreshTree = useWorkspaceStore((state) => state.refreshTree);

  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [context, setContext] = useState<ContextState>(null);
  
  const [editingPath, setEditingPath] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");

  // In-app creation state (replaces fragile window.prompt)
  const [creationTarget, setCreationTarget] = useState<{ parentPath: string; type: "file" | "directory" } | null>(null);
  const [creationName, setCreationName] = useState("");
  const [creationError, setCreationError] = useState<string | null>(null);
  const [toast, setToast] = useState<{ message: string; type: "error" | "info" } | null>(null);

  const effectiveWorkspaces = useMemo(() => {
    if (activeWorkspaces.length > 0) return activeWorkspaces;
    if (workspace) return [workspace];
    return [];
  }, [activeWorkspaces, workspace]);

  const getWorkspaceTree = (wsPath?: string): FileNode | null => {
    if (!wsPath) return fallbackTree || null;
    if (fileTrees[wsPath]) return fileTrees[wsPath];
    const norm = wsPath.replace(/\\/g, "/").toLowerCase();
    for (const [k, v] of Object.entries(fileTrees)) {
      if (k.replace(/\\/g, "/").toLowerCase() === norm && v) {
        return v;
      }
    }
    if (fallbackTree && (fallbackTree.path === wsPath || (fallbackTree.path && fallbackTree.path.replace(/\\/g, "/").toLowerCase() === norm))) {
      return fallbackTree;
    }
    return null;
  };

  useEffect(() => {
    setExpanded((current) => {
      const next = new Set(current);
      let changed = false;
      effectiveWorkspaces.forEach((ws) => {
        const t = getWorkspaceTree(ws.path);
        if (t && !next.has(t.path)) {
          next.add(t.path);
          changed = true;
        }
      });
      return changed ? next : current;
    });
  }, [effectiveWorkspaces, fileTrees, fallbackTree]);

  // Auto-dismiss toast
  useEffect(() => {
    if (toast) {
      const timer = setTimeout(() => setToast(null), 5000);
      return () => clearTimeout(timer);
    }
  }, [toast]);

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
      setToast({ message: error instanceof Error ? error.message : "Rename failed", type: "error" });
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

  const executeCreate = async (parentPath: string, name: string, type: "file" | "directory") => {
    const trimmed = name.trim();
    if (!trimmed) {
      setCreationError("Name cannot be empty");
      return;
    }
    if (INVALID_CHARS.test(trimmed)) {
      setCreationError("Filename contains invalid characters (* ? \" < > | :)");
      return;
    }
    if (trimmed === "." || trimmed === ".." || trimmed.includes("..")) {
      setCreationError("Invalid name or traversal attempt");
      return;
    }

    useWorkspaceStore.getState().selectWorkspaceForPath(parentPath);
    const activeWs = useWorkspaceStore.getState().currentWorkspace ?? (effectiveWorkspaces.length > 0 ? effectiveWorkspaces[0] : null);
    if (!activeWs) {
      setCreationError("No active workspace found");
      return;
    }

    const targetPath = joinPath(parentPath, trimmed);

    try {
      await api.post("/api/files/create", {
        workspace: activeWs.path,
        path: targetPath,
        type,
      });

      // Expand parent so newly created item is visible
      setExpanded((prev) => new Set([...prev, parentPath, ...(type === "directory" ? [targetPath] : [])]));
      setCreationTarget(null);
      setCreationName("");
      setCreationError(null);

      // Refresh file tree
      await refreshTree();

      // For new file: open tab and focus editor
      if (type === "file") {
        await useEditorStore.getState().openFile(targetPath);
        window.dispatchEvent(new CustomEvent("code-os:focus-editor", { detail: { path: targetPath } }));
      }
    } catch (error: any) {
      const msg = error?.message || error?.detail || "Creation failed";
      if (msg.toLowerCase().includes("restricted mode") || error?.status === 403) {
        setToast({ message: "Action blocked: Workspace is in Restricted Mode.", type: "error" });
      } else if (error?.status === 409 || msg.toLowerCase().includes("already exists")) {
        setCreationError(`File or directory already exists: ${trimmed}`);
        setToast({ message: `Path already exists: ${trimmed}`, type: "error" });
      } else {
        setCreationError(msg);
        setToast({ message: msg, type: "error" });
      }
    }
  };

  const runAction = async (action: string, node: FileNode) => {
    useWorkspaceStore.getState().selectWorkspaceForPath(node.path);
    const activeWs = useWorkspaceStore.getState().currentWorkspace ?? (effectiveWorkspaces.length > 0 ? effectiveWorkspaces[0] : null);
    if (!activeWs) return;

    try {
      if (action === "new-file" || action === "new-folder") {
        const parent = node.type === "directory" ? node.path : node.path.replace(/[\\/][^\\/]+$/, "");
        const type = action === "new-file" ? "file" : "directory";

        // Check if window.prompt is mocked (e.g. unit tests)
        let promptVal: string | null = null;
        try {
          promptVal = prompt(action === "new-file" ? "Enter file name (e.g. main.cpp, app.py, index.html):" : "Enter folder name:");
        } catch {
          promptVal = null;
        }

        if (promptVal !== null && promptVal !== undefined) {
          if (!promptVal.trim()) return;
          await executeCreate(parent, promptVal.trim(), type);
          return;
        }

        // Open in-app interactive creation dialog
        setCreationTarget({ parentPath: parent, type });
        setCreationName("");
        setCreationError(null);
        setContext(null);
        return;
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
      setToast({ message: error instanceof Error ? error.message : "Explorer action failed", type: "error" });
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
      const treeNode = getWorkspaceTree(activeWs.path);
      const targetNode = findNode(treeNode ?? null, target);
      if (!source || !targetNode || targetNode.type !== "directory") return;
      await api.post("/api/files/move", { workspace: activeWs.path, source, destination: joinPath(targetNode.path, source.split(/[\\/]/).pop() ?? "moved") });
      await refreshTree();
    };
    window.addEventListener("code-os:file-drop", listener);
    return () => window.removeEventListener("code-os:file-drop", listener);
  }, [workspace?.path, effectiveWorkspaces, fileTrees, refreshTree]);

  return (
    <section
      role="tree"
      data-testid="file-tree-panel"
      className="relative flex h-full min-h-0 w-full min-w-0 flex-col bg-surface-container-low text-on-surface select-none font-ui-label-reg text-ui-label-reg"
      onClick={() => setContext(null)}
    >
      {/*  Explorer Header  */}
      <div className="px-3 py-2 border-b border-surface-variant flex justify-between items-center bg-surface-container/50 shrink-0">
        <h2 className="font-ui-label-bold text-ui-label-bold text-on-surface uppercase tracking-wider text-[11px] truncate">
          {workspace?.name ?? (effectiveWorkspaces.length > 0 ? effectiveWorkspaces[0].name : "WORKSPACE")}
        </h2>
        <div className="flex items-center gap-1.5 text-on-surface-variant">
          <button
            onClick={() => {
              const activeWs = workspace ?? (effectiveWorkspaces.length > 0 ? effectiveWorkspaces[0] : null);
              if (!activeWs) return;
              const root = getWorkspaceTree(activeWs.path) ?? {
                name: activeWs.name,
                path: activeWs.path,
                type: "directory",
                children: [],
              };
              void runAction("new-file", root);
            }}
            className="p-1 hover:text-primary hover:bg-white/5 rounded transition-colors cursor-pointer"
            title="New File"
          >
            <FilePlus size={14} />
          </button>
          <button
            onClick={() => {
              const activeWs = workspace ?? (effectiveWorkspaces.length > 0 ? effectiveWorkspaces[0] : null);
              if (!activeWs) return;
              const root = getWorkspaceTree(activeWs.path) ?? {
                name: activeWs.name,
                path: activeWs.path,
                type: "directory",
                children: [],
              };
              void runAction("new-folder", root);
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

      {/* Toast Alert Banner */}
      {toast && (
        <div className="mx-2 mt-2 p-2 rounded bg-error/15 border border-error/30 text-error text-xs flex items-center justify-between animate-fade-in shrink-0">
          <div className="flex items-center gap-1.5 truncate">
            <ShieldAlert size={14} className="shrink-0 text-error" />
            <span className="truncate">{toast.message}</span>
          </div>
          <button onClick={() => setToast(null)} className="p-0.5 hover:bg-white/10 rounded cursor-pointer">
            <X size={12} />
          </button>
        </div>
      )}

      {/* In-app Creation Dialog */}
      {creationTarget && (
        <div className="mx-2 my-2 p-2.5 rounded-lg bg-surface-container border border-primary/40 shadow-xl space-y-2 shrink-0">
          <div className="flex items-center justify-between text-[11px] font-semibold text-primary">
            <span>{creationTarget.type === "file" ? "Create New File" : "Create New Folder"}</span>
            <span className="text-[10px] text-on-surface-variant font-mono truncate max-w-[130px]" title={creationTarget.parentPath}>
              in: {creationTarget.parentPath.split(/[\\/]/).pop() || "root"}
            </span>
          </div>
          <input
            type="text"
            className="w-full h-7 px-2 text-xs bg-[#131315] border border-outline-variant/60 rounded text-on-surface font-mono focus:border-primary focus:outline-none"
            placeholder={creationTarget.type === "file" ? "e.g. main.cpp, app.py, index.html" : "e.g. components, utils"}
            value={creationName}
            onChange={(e) => {
              setCreationName(e.target.value);
              setCreationError(null);
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter") void executeCreate(creationTarget.parentPath, creationName, creationTarget.type);
              if (e.key === "Escape") setCreationTarget(null);
            }}
            autoFocus
          />
          {creationError && (
            <div className="text-[10px] text-error flex items-center gap-1">
              <AlertCircle size={11} className="shrink-0" />
              <span className="truncate">{creationError}</span>
            </div>
          )}
          <div className="flex justify-end gap-1.5 pt-0.5">
            <button
              onClick={() => setCreationTarget(null)}
              className="px-2 py-0.5 text-[11px] rounded text-on-surface-variant hover:bg-white/5 cursor-pointer"
            >
              Cancel
            </button>
            <button
              onClick={() => void executeCreate(creationTarget.parentPath, creationName, creationTarget.type)}
              className="px-2.5 py-0.5 text-[11px] rounded bg-primary text-[#001f24] font-semibold hover:brightness-110 cursor-pointer"
            >
              Create
            </button>
          </div>
        </div>
      )}

      {/*  File Tree Scroll Area  */}
      <div className="min-h-0 flex-1 min-w-0 w-full overflow-auto py-2 font-code-sm text-code-sm text-on-surface-variant">
        {effectiveWorkspaces.length > 0 ? (
          effectiveWorkspaces.map((ws) => {
            const treeNode = getWorkspaceTree(ws.path);
            return (
              <div key={ws.path} className="mb-3">
                <div className="mb-1 flex h-6 items-center justify-between px-3 text-[10px] font-bold uppercase tracking-wider text-outline-variant bg-surface-container-high/40">
                  <span className="truncate" title={ws.path}>{ws.name}</span>
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      closeWorkspace(ws.path);
                    }}
                    className="text-on-surface-variant hover:text-on-surface p-0.5 rounded hover:bg-white/10 cursor-pointer"
                    title="Remove folder from workspace"
                  >
                    <X size={11} />
                  </button>
                </div>

                {treeNode ? (
                  <>
                    <TreeNode
                      node={treeNode}
                      depth={0}
                      expanded={expanded}
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
                    {treeNode.children && treeNode.children.length === 0 && (
                      <div className="px-4 py-2 text-[11px] text-on-surface-variant/50 italic">
                        Empty folder. Click "New File" above to create files.
                      </div>
                    )}
                  </>
                ) : (
                  <div className="p-3 text-center space-y-2">
                    <span className="text-[11px] text-on-surface-variant/70 block">Folder not loaded or unavailable on disk.</span>
                    <button
                      onClick={() => void openWorkspace()}
                      className="mx-auto text-[11px] bg-primary text-[#001f24] font-semibold px-3 py-1 rounded-full flex items-center gap-1 shadow-sm hover:brightness-110 cursor-pointer"
                    >
                      <FolderPlus size={12} />
                      <span>Open Folder...</span>
                    </button>
                  </div>
                )}
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
