import Editor from "@monaco-editor/react";
import { Columns2, Replace, Save, SaveAll, Search, X, FolderOpen } from "lucide-react";
import { useState } from "react";

import { CodeOsLogo } from "../../components/branding/CodeOsLogo";
import { Button } from "../../components/ui/Button";
import { IconButton } from "../../components/ui/IconButton";
import { useEditorStore } from "../../stores/editorStore";
import { useSettingsStore } from "../../stores/settingsStore";
import { useWorkspaceStore } from "../../stores/workspaceStore";

function MonacoPane({ filePath }: { filePath: string | null }) {
  const file = useEditorStore((state) => state.openFiles.find((item) => item.path === filePath));
  const updateContent = useEditorStore((state) => state.updateContent);
  const fontSize = useEditorStore((state) => state.fontSize);
  const tabSize = useEditorStore((state) => state.tabSize);
  const theme = useSettingsStore((state) => state.settings.theme);
  const isLight = theme === "light" || (theme === "system" && typeof window !== "undefined" && window.matchMedia("(prefers-color-scheme: light)").matches);

  const [editorInstance, setEditorInstance] = useState<any>(null);
  const [showInline, setShowInline] = useState(false);
  const [inlinePrompt, setInlinePrompt] = useState("");

  if (!file) {
    return <div className="grid h-full place-items-center text-sm text-slate-500 bg-surface-950">Select a file from the explorer.</div>;
  }

  const handleEditorDidMount = (editor: any, monaco: any) => {
    setEditorInstance(editor);
    editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyI, () => {
      setShowInline(true);
    });
  };

  return (
    <div className="relative h-full flex-1">
      <Editor
        path={file.path}
        language={file.language}
        value={file.content}
        theme={isLight ? "vs" : "vs-dark"}
        options={{
          minimap: { enabled: true },
          fontSize,
          fontFamily: "JetBrains Mono, Cascadia Code, Consolas, monospace",
          automaticLayout: true,
          wordWrap: "on",
          scrollBeyondLastLine: false,
          tabSize,
          renderWhitespace: "selection"
        }}
        onChange={(value) => void updateContent(file.path, value ?? "")}
        onMount={handleEditorDidMount}
      />
      {showInline && (
        <div className="absolute top-2 right-12 z-50 flex items-center gap-2 rounded-md bg-surface-900 border border-surface-700 p-2 shadow-lg">
          <input
            className="h-7 w-64 rounded bg-surface-850 border-surface-700 text-xs text-white focus:outline-none focus:border-accent-500 placeholder-slate-500 px-2"
            placeholder="Ask AI to modify selection... (Ctrl+I)"
            value={inlinePrompt}
            onChange={(e) => setInlinePrompt(e.target.value)}
            onKeyDown={(async (e) => {
              if (e.key === "Enter") {
                const promptVal = inlinePrompt.trim();
                if (!promptVal || !editorInstance) return;
                setShowInline(false);
                setInlinePrompt("");
                
                const selection = editorInstance.getSelection();
                const selectedText = editorInstance.getModel().getValueInRange(selection);
                
                const chatStore = (await import("../../stores/aiStore")).useAIStore.getState();
                const finalPrompt = `/refactor Propose changes for the selected code: "${selectedText}". Request: ${promptVal}`;
                void chatStore.sendMessage(finalPrompt, [filePath ?? ""]);
              }
              if (e.key === "Escape") {
                setShowInline(false);
              }
            })}
            autoFocus
          />
          <button onClick={() => setShowInline(false)} className="text-slate-500 hover:text-white">
            <X size={14} />
          </button>
        </div>
      )}
    </div>
  );
}

export function EditorWorkspace() {
  const [findText, setFindText] = useState("");
  const [replaceText, setReplaceText] = useState("");
  const openFiles = useEditorStore((state) => state.openFiles);
  const activePath = useEditorStore((state) => state.activePath);
  const splitPath = useEditorStore((state) => state.splitPath);
  const autoSave = useEditorStore((state) => state.autoSave);
  const closeFile = useEditorStore((state) => state.closeFile);
  const saveFile = useEditorStore((state) => state.saveFile);
  const saveAll = useEditorStore((state) => state.saveAll);
  const setAutoSave = useEditorStore((state) => state.setAutoSave);
  const updateContent = useEditorStore((state) => state.updateContent);
  const toggleSplit = useEditorStore((state) => state.toggleSplit);
  const activeFile = openFiles.find((file) => file.path === activePath);
  
  const activeWorkspaces = useWorkspaceStore((state) => state.activeWorkspaces);
  const recentWorkspaces = useWorkspaceStore((state) => state.recentWorkspaces);
  const openWorkspace = useWorkspaceStore((state) => state.openWorkspace);

  const replaceInCurrentFile = () => {
    if (!activeFile || !findText) return;
    void updateContent(activeFile.path, activeFile.content.replaceAll(findText, replaceText));
  };

  if (openFiles.length === 0) {
    if (activeWorkspaces.length === 0) {
      return (
        <div className="flex h-full flex-col items-center justify-center bg-surface-950 p-8 text-center select-none">
          <div className="max-w-md w-full space-y-6">
            <div className="space-y-3">
              <CodeOsLogo className="mx-auto w-full max-w-[380px] px-6 py-4" imageClassName="h-16 w-full" priority />
              <p className="text-sm text-slate-400">Local-first AI-assisted development workspace</p>
            </div>
            
            <div className="rounded-lg border border-surface-700 bg-surface-900 p-6 shadow-lg">
              <Button onClick={() => void openWorkspace()} className="w-full h-10 justify-center gap-2">
                <FolderOpen size={16} />
                Open Folder...
              </Button>
            </div>

            {recentWorkspaces.length > 0 && (
              <div className="space-y-2 text-left">
                <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-500">Recent Workspaces</h3>
                <div className="divide-y divide-surface-800 rounded-md border border-surface-700 bg-surface-900 overflow-hidden">
                  {recentWorkspaces.slice(0, 5).map((ws) => (
                    <button
                      key={ws.path}
                      className="flex w-full items-center justify-between px-3 py-2 text-xs text-slate-300 hover:bg-surface-800 hover:text-white transition-colors"
                      onClick={() => void openWorkspace(ws.path)}
                    >
                      <span className="font-semibold truncate mr-2">{ws.name}</span>
                      <span className="text-slate-500 truncate max-w-[200px]" title={ws.path}>{ws.path}</span>
                    </button>
                  ))}
                </div>
              </div>
            )}

            <div className="rounded-lg border border-surface-700 bg-surface-900 p-4 text-left text-xs text-slate-400 space-y-2">
              <div className="font-semibold text-slate-300 mb-1">Keyboard Shortcuts</div>
              <div className="flex justify-between"><span className="text-slate-500">Toggle Explorer</span><kbd className="rounded bg-surface-800 px-1.5 py-0.5 border border-surface-700 text-[10px]">Ctrl+B</kbd></div>
              <div className="flex justify-between"><span className="text-slate-500">Toggle Terminal</span><kbd className="rounded bg-surface-800 px-1.5 py-0.5 border border-surface-700 text-[10px]">Ctrl+`</kbd></div>
              <div className="flex justify-between"><span className="text-slate-500">Toggle AI Panel</span><kbd className="rounded bg-surface-800 px-1.5 py-0.5 border border-surface-700 text-[10px]">Ctrl+Shift+A</kbd></div>
              <div className="flex justify-between"><span className="text-slate-500">Save File</span><kbd className="rounded bg-surface-800 px-1.5 py-0.5 border border-surface-700 text-[10px]">Ctrl+S</kbd></div>
            </div>
          </div>
        </div>
      );
    } else {
      return (
        <div className="grid h-full place-items-center text-sm text-slate-500 bg-surface-950">
          Select a file from the explorer to open.
        </div>
      );
    }
  }

  return (
    <section className="grid h-full min-h-0 grid-rows-[38px_minmax(0,1fr)]">
      <div className="flex min-w-0 items-center border-b border-surface-700 bg-surface-900">
        <div className="flex min-w-0 flex-1 overflow-x-auto">
          {openFiles.map((file) => (
            <button
              key={file.path}
              className={`flex h-9 max-w-[220px] items-center gap-2 border-r border-surface-700 px-3 text-sm ${
                file.path === activePath ? "bg-surface-800 text-white" : "text-slate-400 hover:bg-surface-850"
              }`}
              onClick={() => {
                useWorkspaceStore.getState().selectWorkspaceForPath(file.path);
                useEditorStore.setState({ activePath: file.path });
              }}
            >
              <span className="truncate">{file.name}</span>
              {file.dirty ? <span className="text-warning">●</span> : null}
              <X size={14} onClick={(event) => { event.stopPropagation(); closeFile(file.path); }} />
            </button>
          ))}
        </div>
        <div className="flex items-center gap-2 pr-2">
          <div className="flex items-center gap-1 rounded-md border border-surface-700 bg-surface-850 px-2">
            <Search size={14} className="text-slate-500" />
            <input
              className="h-7 w-28 border-none bg-transparent p-0 text-xs text-slate-100 focus:ring-0"
              value={findText}
              onChange={(event) => setFindText(event.target.value)}
              placeholder="Find"
            />
            <input
              className="h-7 w-28 border-none bg-transparent p-0 text-xs text-slate-100 focus:ring-0"
              value={replaceText}
              onChange={(event) => setReplaceText(event.target.value)}
              placeholder="Replace"
            />
            <IconButton label="Replace in current file" icon={<Replace size={14} />} onClick={replaceInCurrentFile} disabled={!activeFile || !findText} />
          </div>
          <label className="flex items-center gap-1 text-xs text-slate-400">
            <input type="checkbox" checked={autoSave} onChange={(event) => setAutoSave(event.target.checked)} className="rounded border-surface-700 bg-surface-850" />
            Auto
          </label>
          <IconButton label="Save file" icon={<Save size={15} />} onClick={() => activePath && void saveFile(activePath)} disabled={!activePath} />
          <IconButton label="Save all" icon={<SaveAll size={15} />} onClick={() => void saveAll()} disabled={!openFiles.length} />
          <IconButton label="Split editor" icon={<Columns2 size={15} />} onClick={() => toggleSplit(splitPath ? null : activePath)} disabled={!activePath} />
        </div>
      </div>
      <div className={splitPath ? "grid h-full min-h-0 grid-cols-2" : "h-full min-h-0"}>
        <MonacoPane filePath={activePath} />
        {splitPath ? <MonacoPane filePath={splitPath} /> : null}
      </div>
    </section>
  );
}
