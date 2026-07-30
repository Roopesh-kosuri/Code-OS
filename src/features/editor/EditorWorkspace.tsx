import { lazy, Suspense, useState } from "react";
import { Columns2, Replace, Save, SaveAll, Search, X, FolderOpen, Loader2 } from "lucide-react";
import * as monaco from "monaco-editor";
import Editor, { loader } from "@monaco-editor/react";

// Configure Monaco loader to use the bundled monaco instance directly.
// This guarantees instant, offline loading in Electron production builds with zero CDN or node_modules path dependencies.
loader.config({ monaco });


import { CodeOsLogo } from "../../components/branding/CodeOsLogo";
import { Button } from "../../components/ui/Button";
import { IconButton } from "../../components/ui/IconButton";
import { useEditorStore } from "../../stores/editorStore";
import { useSettingsStore } from "../../stores/settingsStore";
import { useWorkspaceStore } from "../../stores/workspaceStore";

function getLanguageFromPath(filePath: string | null): string {
  if (!filePath) return "plaintext";
  const ext = filePath.split(".").pop()?.toLowerCase();
  const map: Record<string, string> = {
    java: "java",
    c: "c",
    h: "c",
    cpp: "cpp",
    cc: "cpp",
    cxx: "cpp",
    hpp: "cpp",
    cs: "csharp",
    rs: "rust",
    go: "go",
    py: "python",
    js: "javascript",
    jsx: "javascript",
    ts: "typescript",
    tsx: "typescript",
    html: "html",
    htm: "html",
    css: "css",
    scss: "scss",
    less: "less",
    json: "json",
    md: "markdown",
    sql: "sql",
    sh: "shell",
    bash: "shell",
    zsh: "shell",
    ps1: "powershell",
    php: "php",
    rb: "ruby",
    kt: "kotlin",
    kts: "kotlin",
    swift: "swift",
    xml: "xml",
    yaml: "yaml",
    yml: "yaml",
    dockerfile: "dockerfile",
  };
  return ext ? (map[ext] || "plaintext") : "plaintext";
}

function MonacoPane({ filePath }: { filePath: string | null }) {
  const file = useEditorStore((state) => state.openFiles.find((item) => item.path === filePath));
  const updateContent = useEditorStore((state) => state.updateContent);
  const fontSize = useEditorStore((state) => state.fontSize);
  const tabSize = useEditorStore((state) => state.tabSize);
  const theme = useSettingsStore((state) => state.settings.theme);
  const activeThemeName = (theme === "system" && typeof window !== "undefined" && window.matchMedia("(prefers-color-scheme: light)").matches)
    ? "light"
    : (theme || "dark");
  const isLight = activeThemeName === "light";

  const monacoTheme = activeThemeName === "light"
    ? "vs"
    : activeThemeName === "void"
      ? "vs-void"
      : activeThemeName === "cyberpunk"
        ? "vs-cyberpunk"
        : "vs-dark";

  const [editorInstance, setEditorInstance] = useState<any>(null);
  const [showInline, setShowInline] = useState(false);
  const [inlinePrompt, setInlinePrompt] = useState("");

  if (!file) {
    return <div className="grid h-full place-items-center text-sm text-slate-500 bg-[var(--surface)]">Select a file from the explorer.</div>;
  }

  const effectiveLanguage = (!file.language || file.language === "plaintext")
    ? getLanguageFromPath(file.path)
    : file.language;

  const handleBeforeMount = (monaco: any) => {
    monaco.editor.defineTheme("vs-dark", {
      base: "vs-dark",
      inherit: true,
      rules: [
        { token: "", foreground: "e5e2e3", background: "131418" },
        { token: "keyword", foreground: "00daf3", fontStyle: "bold" },
        { token: "string", foreground: "ffdf96" },
        { token: "comment", foreground: "6e808a", fontStyle: "italic" },
        { token: "function", foreground: "82aaff" },
        { token: "variable", foreground: "c3f5ff" },
        { token: "type", foreground: "9cf0ff" },
        { token: "class", foreground: "9cf0ff" },
        { token: "number", foreground: "f78c6c" },
        { token: "delimiter", foreground: "bac9cc" },
      ],
      colors: {
        "editor.background": "#131418",
        "editor.foreground": "#e5e2e3",
        "editorCursor.foreground": "#00daf3",
        "editor.lineHighlightBackground": "#1e2026",
        "editorLineNumber.foreground": "#425056",
        "editorLineNumber.activeForeground": "#00daf3",
        "editorGutter.background": "#131418",
        "editor.selectionBackground": "#00626e66",
        "editor.inactiveSelectionBackground": "#00626e33",
      },
    });

    monaco.editor.defineTheme("vs-void", {
      base: "vs-dark",
      inherit: true,
      rules: [
        { token: "", foreground: "f4f4f5", background: "000000" },
        { token: "keyword", foreground: "e4e4e7", fontStyle: "bold" },
        { token: "string", foreground: "eab308" },
        { token: "comment", foreground: "52525b", fontStyle: "italic" },
        { token: "function", foreground: "a1a1aa" },
        { token: "variable", foreground: "d4d4d8" },
        { token: "type", foreground: "f4f4f5" },
        { token: "class", foreground: "f4f4f5" },
        { token: "number", foreground: "a1a1aa" },
        { token: "delimiter", foreground: "71717a" },
      ],
      colors: {
        "editor.background": "#000000",
        "editor.foreground": "#f4f4f5",
        "editorCursor.foreground": "#a1a1aa",
        "editor.lineHighlightBackground": "#101010",
        "editorLineNumber.foreground": "#3f3f46",
        "editorLineNumber.activeForeground": "#e4e4e7",
        "editorGutter.background": "#000000",
        "editor.selectionBackground": "#27272a88",
        "editor.inactiveSelectionBackground": "#18181b55",
      },
    });

    monaco.editor.defineTheme("vs-cyberpunk", {
      base: "vs-dark",
      inherit: true,
      rules: [
        { token: "", foreground: "dcf1f5", background: "080b12" },
        { token: "keyword", foreground: "00e5ff", fontStyle: "bold" },
        { token: "string", foreground: "ffdd00" },
        { token: "comment", foreground: "4b7e8a", fontStyle: "italic" },
        { token: "function", foreground: "ff007f" },
        { token: "variable", foreground: "ff79c6" },
        { token: "type", foreground: "00ffd8" },
        { token: "class", foreground: "00e5ff" },
        { token: "number", foreground: "ff007f" },
        { token: "delimiter", foreground: "72abb7" },
      ],
      colors: {
        "editor.background": "#080b12",
        "editor.foreground": "#dcf1f5",
        "editorCursor.foreground": "#00e5ff",
        "editor.lineHighlightBackground": "#0f141c",
        "editorLineNumber.foreground": "#2f3f58",
        "editorLineNumber.activeForeground": "#00e5ff",
        "editorGutter.background": "#080b12",
        "editor.selectionBackground": "#00e5ff33",
        "editor.inactiveSelectionBackground": "#ff007f22",
      },
    });

    monaco.editor.defineTheme("vs", {
      base: "vs",
      inherit: true,
      rules: [
        { token: "keyword", foreground: "0969da", fontStyle: "bold" },
        { token: "string", foreground: "0a3069" },
        { token: "comment", foreground: "57606a", fontStyle: "italic" },
        { token: "function", foreground: "8250df" },
        { token: "variable", foreground: "953800" },
        { token: "type", foreground: "0550ae" },
        { token: "class", foreground: "0550ae" },
      ],
      colors: {
        "editor.background": "#ffffff",
        "editor.foreground": "#1f2328",
        "editorCursor.foreground": "#0969da",
        "editor.lineHighlightBackground": "#f6f8fa",
        "editorLineNumber.foreground": "#8c959f",
        "editorLineNumber.activeForeground": "#0969da",
        "editorGutter.background": "#ffffff",
      },
    });
  };

  const handleEditorDidMount = (editor: any, monaco: any) => {
    setEditorInstance(editor);
    monaco.editor.setTheme(monacoTheme);
    editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyI, () => {
      setShowInline(true);
    });
  };

  return (
    <div className="relative h-full flex-1 bg-[var(--surface)]">
      <Suspense fallback={
        <div className="h-full flex items-center justify-center bg-[var(--surface)]">
          <div className="flex flex-col items-center gap-2">
            <Loader2 size={20} className="text-primary animate-spin" />
            <span className="text-[11px] text-on-surface-variant font-mono">Loading editor…</span>
          </div>
        </div>
      }>
        <Editor
          path={file.path}
          language={effectiveLanguage}
          value={file.content}
          theme={monacoTheme}
          beforeMount={handleBeforeMount}
          onMount={handleEditorDidMount}
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
        />
      </Suspense>

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
  const [showSearch, setShowSearch] = useState(false);
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

  const handleToggleSplit = () => {
    if (splitPath) {
      // Close split view
      toggleSplit(null);
    } else {
      // Open split view
      toggleSplit(activePath);
    }
  };

  if (openFiles.length === 0) {
    if (activeWorkspaces.length === 0) {
      return (
        <div className="flex h-full flex-col items-center justify-center bg-[var(--bg-surface-950,#0a0a0b)] p-8 text-center select-none">
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
        <div className="grid h-full place-items-center text-sm text-slate-500 bg-[var(--bg-surface-950,#0a0a0b)]">
          Select a file from the explorer to open.
        </div>
      );
    }
  }

  return (
    <section data-testid="editor-panel" className="grid h-full min-h-0 grid-rows-[40px_minmax(0,1fr)] bg-[var(--bg-surface-950,#0a0a0b)]">
      {/* Tab & Toolbar Row — scrollable so AI panel never covers buttons */}
      <div className="flex h-10 bg-surface-container-low/90 backdrop-blur-md border-b border-outline-variant/20 overflow-hidden shrink-0 glass-edge select-none">
        {/* File Tabs — takes all available space */}
        <div className="flex min-w-0 flex-1 overflow-x-auto" role="tablist">
          {openFiles.map((file) => {
            const isActive = file.path === activePath;
            return (
              <div
                key={file.path}
                role="tab"
                aria-selected={isActive}
                onClick={() => {
                  useWorkspaceStore.getState().selectWorkspaceForPath(file.path);
                  useEditorStore.setState({ activePath: file.path });
                }}
                className={`flex items-center px-3 min-w-[100px] max-w-[180px] gap-1.5 cursor-pointer relative group transition-colors shrink-0 ${
                  isActive
                    ? "bg-[var(--bg-surface-950)] border-t-2 border-primary border-r border-[var(--outline-variant)]/20 text-[var(--on-surface)] font-semibold"
                    : "border-r border-[var(--outline-variant)]/10 text-[var(--on-surface-variant)]/70 hover:bg-[var(--outline-variant)]/10 hover:text-[var(--on-surface)]"
                }`}
              >
                <span className={`material-symbols-outlined text-[13px] shrink-0 ${isActive ? "text-primary-fixed-dim" : "text-on-surface-variant"}`}>
                  {file.name.endsWith(".ts") || file.name.endsWith(".tsx") || file.name.endsWith(".js") ? "code" :
                   file.name.endsWith(".css") ? "style" : "description"}
                </span>
                <span className="font-body-base text-body-base truncate flex-1 text-[12px]">{file.name}</span>
                {file.dirty && <span className="text-tertiary-container text-[10px] shrink-0">●</span>}
                <span
                  role="button"
                  aria-label="Close tab"
                  onClick={(event) => { event.stopPropagation(); closeFile(file.path); }}
                  className="material-symbols-outlined text-[13px] text-on-surface-variant opacity-0 group-hover:opacity-100 hover:bg-surface-variant rounded p-0.5 shrink-0"
                >
                  close
                </span>
              </div>

            );
          })}
        </div>

        {/* Toolbar — fixed width on the right, never shrinks */}
        <div className="flex items-center gap-1 pr-2 pl-1 border-l border-outline-variant/10 bg-surface-container-low/50 shrink-0">
          {/* Search toggle */}
          <button
            title="Toggle Find/Replace"
            onClick={() => setShowSearch((v) => !v)}
            className={`w-7 h-7 flex items-center justify-center rounded transition-colors ${showSearch ? "bg-primary/10 text-primary" : "text-on-surface-variant/70 hover:text-primary hover:bg-primary/5"}`}
          >
            <Search size={13} />
          </button>

          {/* Inline Find/Replace — shown when search toggled */}
          {showSearch && (
            <div className="flex items-center gap-1 bg-surface-container-high border border-outline-variant/20 rounded px-1.5 h-7">
              <input
                className="w-20 bg-transparent border-none text-[11px] text-on-surface placeholder:text-on-surface-variant/40 focus:outline-none"
                value={findText}
                onChange={(event) => setFindText(event.target.value)}
                placeholder="Find"
              />
              <span className="text-outline-variant/50 text-[10px]">→</span>
              <input
                className="w-20 bg-transparent border-none text-[11px] text-on-surface placeholder:text-on-surface-variant/40 focus:outline-none"
                value={replaceText}
                onChange={(event) => setReplaceText(event.target.value)}
                placeholder="Replace"
              />
              <button
                onClick={replaceInCurrentFile}
                disabled={!activeFile || !findText}
                className="w-5 h-5 flex items-center justify-center text-on-surface-variant/70 hover:text-primary disabled:opacity-30"
                title="Replace in file"
              >
                <Replace size={11} />
              </button>
            </div>
          )}

          <label className="flex items-center gap-1 text-[10px] text-on-surface-variant/60 cursor-pointer select-none px-1" title="Auto Save">
            <input
              type="checkbox"
              checked={autoSave}
              onChange={(event) => setAutoSave(event.target.checked)}
              className="rounded border-surface-700 bg-surface-850 w-3 h-3"
            />
            Auto
          </label>

          <button
            title="Save File (Ctrl+S)"
            onClick={() => activePath && void saveFile(activePath)}
            disabled={!activePath}
            className="w-7 h-7 flex items-center justify-center rounded text-on-surface-variant/70 hover:text-primary hover:bg-primary/5 disabled:opacity-30 transition-colors"
          >
            <Save size={13} />
          </button>

          <button
            title="Save All"
            onClick={() => void saveAll()}
            disabled={!openFiles.length}
            className="w-7 h-7 flex items-center justify-center rounded text-on-surface-variant/70 hover:text-primary hover:bg-primary/5 disabled:opacity-30 transition-colors"
          >
            <SaveAll size={13} />
          </button>

          <button
            title={splitPath ? "Close Split View" : "Split Editor"}
            onClick={handleToggleSplit}
            disabled={!activePath}
            className={`w-7 h-7 flex items-center justify-center rounded transition-colors disabled:opacity-30 ${splitPath ? "text-primary bg-primary/10" : "text-on-surface-variant/70 hover:text-primary hover:bg-primary/5"}`}
          >
            {splitPath ? <X size={13} /> : <Columns2 size={13} />}
          </button>
        </div>
      </div>

      {/* Editor Area */}
      <div className={splitPath ? "grid h-full min-h-0 grid-cols-2" : "h-full min-h-0"}>
        <MonacoPane filePath={activePath} />
        {splitPath ? <MonacoPane filePath={splitPath} /> : null}
      </div>
    </section>
  );
}
