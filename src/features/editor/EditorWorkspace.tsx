import { lazy, Suspense, useEffect, useState } from "react";
import { Columns2, Replace, Save, SaveAll, Search, X, FolderOpen, Loader2, Sparkles, ChevronRight, FileCode, Check, Play, Square, Bug } from "lucide-react";
import * as monaco from "monaco-editor";
import Editor, { loader } from "@monaco-editor/react";

loader.config({ monaco });

import { Button } from "../../components/ui/Button";
import { FileIcon } from "../../components/ui/FileIcon";
import { useEditorStore } from "../../stores/editorStore";
import { useSettingsStore } from "../../stores/settingsStore";
import { useWorkspaceStore } from "../../stores/workspaceStore";
import { useRunStore } from "../../stores/runStore";
import { registerInlineCompletionProvider, useInlineCompletionStore } from "./inlineCompletionProvider";
import { installDebugDecorations } from "../../components/editor/MonacoPane";
import { debugClient } from "../../components/debug/debugClient";
import { DebugPanel } from "../../components/debug/DebugPanel";
import { DebugToolbar } from "../../components/debug/DebugToolbar";

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

  const [editorInstance, setEditorInstance] = useState<any>(null);
  const [showInline, setShowInline] = useState(false);
  const [inlinePrompt, setInlinePrompt] = useState("");

  if (!file) {
    return (
      <div className="grid h-full place-items-center text-sm text-on-surface-variant/50 bg-[#0a0a0c]">
        Select a file from the explorer.
      </div>
    );
  }

  const effectiveLanguage = (!file.language || file.language === "plaintext")
    ? getLanguageFromPath(file.path)
    : file.language;

  const handleBeforeMount = (monaco: any) => {
    monaco.editor.defineTheme("vs-stitch-dark", {
      base: "vs-dark",
      inherit: true,
      rules: [
        { token: "", foreground: "e5e1e4", background: "0a0a0c" },
        { token: "keyword", foreground: "9cefff", fontStyle: "bold" },
        { token: "string", foreground: "ffdeac" },
        { token: "comment", foreground: "859396", fontStyle: "italic" },
        { token: "function", foreground: "9acfda" },
        { token: "variable", foreground: "e5e1e4" },
        { token: "type", foreground: "ffdeac" },
        { token: "class", foreground: "ffdeac" },
        { token: "number", foreground: "ffb4ab" },
        { token: "delimiter", foreground: "bac9cc" },
      ],
      colors: {
        "editor.background": "#0a0a0c",
        "editor.foreground": "#e5e1e4",
        "editorCursor.foreground": "#00daf3",
        "editor.lineHighlightBackground": "#131315",
        "editorLineNumber.foreground": "#353437",
        "editorLineNumber.activeForeground": "#00daf3",
        "editorGutter.background": "#0a0a0c",
        "editor.selectionBackground": "#00daf325",
        "editor.inactiveSelectionBackground": "#00daf315",
      },
    });
  };

  const handleEditorDidMount = (editor: any, monaco: any) => {
    setEditorInstance(editor);
    monaco.editor.setTheme("vs-stitch-dark");
    registerInlineCompletionProvider(monaco);
    installDebugDecorations(editor, monaco, file.path);
    editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyI, () => {
      setShowInline(true);
    });

    editor.onDidChangeCursorPosition((e: any) => {
      useEditorStore.getState().setCursorPosition({
        line: e.position.lineNumber,
        col: e.position.column,
      });
    });

    const updateMarkers = () => {
      const model = editor.getModel();
      if (!model) return;
      const markers = monaco.editor.getModelMarkers({ resource: model.uri });
      let errors = 0;
      let warnings = 0;
      for (const m of markers) {
        if (m.severity === monaco.MarkerSeverity.Error) errors++;
        else if (m.severity === monaco.MarkerSeverity.Warning) warnings++;
      }
      useEditorStore.getState().setMarkerStats({ errors, warnings });
    };

    monaco.editor.onDidChangeMarkers(() => {
      updateMarkers();
    });
    updateMarkers();
  };

  return (
    <div className="relative h-full flex-1 bg-[#0a0a0c]">
      <Suspense fallback={
        <div className="h-full flex items-center justify-center bg-[#0a0a0c]">
          <div className="flex flex-col items-center gap-2">
            <Loader2 size={20} className="text-primary-container animate-spin" />
            <span className="text-[11px] text-on-surface-variant font-mono">Loading editor…</span>
          </div>
        </div>
      }>
        <Editor
          path={file.path}
          language={effectiveLanguage}
          value={file.content}
          theme="vs-stitch-dark"
          beforeMount={handleBeforeMount}
          onMount={handleEditorDidMount}
          options={{
            minimap: { enabled: true, side: "right", renderCharacters: false, maxColumn: 100 },
            fontSize,
            lineHeight: Math.round(fontSize * 1.55),
            fontFamily: "'JetBrains Mono', 'Cascadia Code', 'Fira Code', Consolas, monospace",
            fontLigatures: true,
            automaticLayout: true,
            wordWrap: "on",
            scrollBeyondLastLine: false,
            tabSize,
            renderWhitespace: "selection",
            glyphMargin: false,
            lineNumbersMinChars: 4,
            lineDecorationsWidth: 6,
            showFoldingControls: "mouseover",
            padding: { top: 12, bottom: 12 },
            smoothScrolling: true,
            cursorBlinking: "smooth",
            cursorSmoothCaretAnimation: "on",
            bracketPairColorization: { enabled: true },
            guides: {
              bracketPairs: true,
              indentation: true,
            },
            overviewRulerBorder: false,
            hideCursorInOverviewRuler: true,
            inlineSuggest: {
              enabled: true,
              mode: "prefix",
            },
            suggest: {
              preview: true,
            },
          }}
          onChange={(value) => void updateContent(file.path, value ?? "")}
        />
      </Suspense>

      {/* Inline AI Modifier Box (Ctrl+I) */}
      {showInline && (
        <div className="absolute top-3 right-12 z-50 flex items-center gap-2 rounded-xl bg-[#1e1f24] border border-primary-container/30 p-2.5 shadow-2xl">
          <input
            className="h-8 w-72 rounded-lg bg-[#131315] border border-surface-variant text-xs text-on-surface focus:outline-none focus:border-primary-container placeholder:text-outline-variant px-3"
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
          <button onClick={() => setShowInline(false)} className="text-on-surface-variant hover:text-on-surface p-1">
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
  const isFetchingCompletion = useInlineCompletionStore((s) => s.isFetching);
  const lastLatencyMs = useInlineCompletionStore((s) => s.lastLatencyMs);
  const cursorPosition = useEditorStore((state) => state.cursorPosition) || { line: 1, col: 1 };
  const markerStats = useEditorStore((state) => state.markerStats) || { errors: 0, warnings: 0 };
  
  const activeWorkspaces = useWorkspaceStore((state) => state.activeWorkspaces);
  const openWorkspace = useWorkspaceStore((state) => state.openWorkspace);

  const runStatus = useRunStore((state) => state.status);
  const runFile = useRunStore((state) => state.runFile);
  const stopRun = useRunStore((state) => state.stopRun);
  const isRunning = runStatus === "running" || runStatus === "compiling";
  const [isDebugging, setIsDebugging] = useState(debugClient.snapshot().active);

  useEffect(() => debugClient.subscribe((state) => setIsDebugging(state.active)), []);

  const handleRunOrStop = async () => {
    if (isRunning) {
      await stopRun();
      return;
    }
    if (!activePath || !activeFile) return;

    if (activeFile.dirty) {
      await saveFile(activePath);
    }

    const matchingWs = activeWorkspaces.find((w) => activePath.startsWith(w.path))?.path;
    const ws = matchingWs || (activePath.includes("/") || activePath.includes("\\")
      ? activePath.substring(0, Math.max(activePath.lastIndexOf("/"), activePath.lastIndexOf("\\")))
      : activeWorkspaces[0]?.path || "");

    window.dispatchEvent(new CustomEvent("code-os:menu", { detail: "view.openTerminal" }));
    window.dispatchEvent(new CustomEvent("code-os:show-run-output"));
    await runFile(ws, activePath);
  };

  const handleDebug = async () => {
    if (!activePath || !activeFile || getLanguageFromPath(activePath) !== "python") return;
    if (activeFile.dirty) await saveFile(activePath);
    await debugClient.start(activePath);
  };

  const replaceInCurrentFile = () => {
    if (!activeFile || !findText) return;
    void updateContent(activeFile.path, activeFile.content.replaceAll(findText, replaceText));
  };

  const handleToggleSplit = () => {
    if (splitPath) {
      toggleSplit(null);
    } else {
      toggleSplit(activePath);
    }
  };

  if (openFiles.length === 0) {
    return (
      <div className="flex h-full flex-col items-center justify-center bg-[#0a0a0c] p-8 text-center select-none text-on-surface">
        <div className="max-w-md w-full space-y-6">
          <div className="space-y-2">
            <div className="w-12 h-12 rounded-2xl bg-primary-container/10 border border-primary-container/20 flex items-center justify-center text-primary-container mx-auto">
              <span className="material-symbols-outlined text-2xl" style={{ fontVariationSettings: "'FILL' 1" }}>
                code
              </span>
            </div>
            <h2 className="text-xl font-bold text-on-surface">No Files Open</h2>
            <p className="text-xs text-on-surface-variant">Select a file from the explorer or open a folder to start coding.</p>
          </div>
          
          <div className="rounded-xl border border-surface-container-high bg-[#131315] p-6 shadow-lg">
            <button
              onClick={() => void openWorkspace()}
              className="w-full h-10 rounded-full bg-primary-container text-[#001f24] font-ui-label-bold text-ui-label-bold flex items-center justify-center gap-2 hover:bg-primary-fixed transition-all shadow-md cursor-pointer"
            >
              <FolderOpen size={16} />
              <span>Open Folder...</span>
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <section data-testid="editor-panel" className="flex flex-col h-full min-h-0 w-full bg-[#0a0a0c] overflow-hidden select-none">
      {/* ── File Tabs Header Row (Sleek Modern Tabs) ───────────────────── */}
      <div className="h-9 min-h-[36px] flex items-center justify-between px-2 bg-[#0e1014] border-b border-surface-variant/50 overflow-hidden shrink-0">
        {/* Tabs List */}
        <div className="flex items-center h-full overflow-x-auto no-scrollbar flex-1 min-w-0" role="tablist">
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
                className={`h-full flex items-center gap-2 px-3 cursor-pointer group transition-all duration-150 shrink-0 text-xs border-r border-white/[0.06] ${
                  isActive
                    ? "bg-[#0a0a0c] text-white border-t-2 border-t-primary shadow-xs font-medium"
                    : "bg-[#0e1014] hover:bg-[#13151b] text-on-surface-variant/75 hover:text-on-surface"
                }`}
              >
                <FileIcon filename={file.name} size={15} />

                <span className="truncate max-w-[150px] font-mono text-[11.5px]">{file.name}</span>

                {file.dirty && (
                  <div className="w-1.5 h-1.5 rounded-full bg-primary ml-0.5 shrink-0" />
                )}

                <span
                  role="button"
                  aria-label="Close tab"
                  onClick={(event) => {
                    event.stopPropagation();
                    closeFile(file.path);
                  }}
                  className="material-symbols-outlined text-[13px] text-on-surface-variant/40 group-hover:text-on-surface hover:bg-white/10 rounded p-0.5 shrink-0 transition-colors ml-1"
                >
                  close
                </span>
              </div>
            );
          })}
        </div>

        {/* Toolbar Controls */}
        <div className="flex items-center gap-1 pl-2 shrink-0 text-on-surface-variant">
          {/* Find toggle */}
          <button
            title="Toggle Find/Replace"
            onClick={() => setShowSearch((v) => !v)}
            className={`w-7 h-7 flex items-center justify-center rounded-lg transition-colors cursor-pointer ${
              showSearch ? "bg-primary-container/15 text-primary" : "hover:text-on-surface hover:bg-white/5"
            }`}
          >
            <Search size={13} />
          </button>

          <button
            data-testid="editor-debug-btn"
            title="Debug Python file"
            onClick={() => void handleDebug()}
            disabled={!activePath || getLanguageFromPath(activePath) !== "python" || isDebugging}
            className="h-7 px-2.5 flex items-center gap-1.5 rounded-lg text-xs font-mono font-medium border border-amber-400/30 bg-amber-400/10 text-amber-300 disabled:opacity-30"
          >
            <Bug size={12} /><span className="text-[11px]">Debug</span>
          </button>

          {isDebugging && <DebugToolbar />}

          {showSearch && (
            <div className="flex items-center gap-1 bg-surface-container-high border border-outline-variant/30 rounded-lg px-2 h-7">
              <input
                className="w-20 bg-transparent border-none text-[11px] text-on-surface placeholder:text-outline-variant focus:outline-none"
                value={findText}
                onChange={(e) => setFindText(e.target.value)}
                placeholder="Find"
              />
              <span className="text-outline-variant text-[10px]">→</span>
              <input
                className="w-20 bg-transparent border-none text-[11px] text-on-surface placeholder:text-outline-variant focus:outline-none"
                value={replaceText}
                onChange={(e) => setReplaceText(e.target.value)}
                placeholder="Replace"
              />
              <button
                onClick={replaceInCurrentFile}
                disabled={!activeFile || !findText}
                className="w-5 h-5 flex items-center justify-center text-on-surface-variant hover:text-primary disabled:opacity-30 cursor-pointer"
                title="Replace in file"
              >
                <Replace size={11} />
              </button>
            </div>
          )}

          {/* ── Run / Stop Action Button ── */}
          <button
            data-testid="editor-run-btn"
            title={isRunning ? "Stop Execution (Ctrl+Shift+R / F5)" : `Run ${activeFile ? getLanguageFromPath(activeFile.path).toUpperCase() : "File"} (Ctrl+Shift+R / F5)`}
            onClick={() => void handleRunOrStop()}
            disabled={!activePath}
            className={`h-7 px-2.5 flex items-center gap-1.5 rounded-lg text-xs font-mono font-medium transition-all cursor-pointer shadow-xs disabled:opacity-30 mr-1 ${
              isRunning
                ? "bg-red-500/20 text-red-400 hover:bg-red-500/30 border border-red-500/30 animate-pulse"
                : "bg-emerald-500/15 text-emerald-400 hover:bg-emerald-500/25 border border-emerald-500/20 hover:border-emerald-500/40"
            }`}
          >
            {isRunning ? (
              <>
                <Loader2 size={12} className="animate-spin text-red-400" />
                <span className="text-[11px]">Stop</span>
              </>
            ) : (
              <>
                <Play size={11} className="fill-emerald-400 text-emerald-400" />
                <span className="text-[11px]">Run</span>
              </>
            )}
          </button>

          <label className="flex items-center gap-1 text-[10px] text-on-surface-variant/60 cursor-pointer select-none px-1" title="Auto Save">
            <input
              type="checkbox"
              checked={autoSave}
              onChange={(e) => setAutoSave(e.target.checked)}
              className="rounded accent-primary w-3 h-3 cursor-pointer"
            />
            <span>Auto</span>
          </label>

          <button
            title="Save File (Ctrl+S)"
            onClick={() => activePath && void saveFile(activePath)}
            disabled={!activePath}
            className="w-7 h-7 flex items-center justify-center rounded-lg hover:text-on-surface hover:bg-white/5 disabled:opacity-30 transition-colors cursor-pointer"
          >
            <Save size={13} />
          </button>

          <button
            title="Save All"
            onClick={() => void saveAll()}
            disabled={!openFiles.length}
            className="w-7 h-7 flex items-center justify-center rounded-lg hover:text-on-surface hover:bg-white/5 disabled:opacity-30 transition-colors cursor-pointer"
          >
            <SaveAll size={13} />
          </button>

          <button
            title={splitPath ? "Close Split View" : "Split Editor"}
            onClick={handleToggleSplit}
            disabled={!activePath}
            className={`w-7 h-7 flex items-center justify-center rounded-lg transition-colors disabled:opacity-30 cursor-pointer ${
              splitPath ? "text-primary bg-primary/15" : "hover:text-on-surface hover:bg-white/5"
            }`}
          >
            {splitPath ? <X size={13} /> : <Columns2 size={13} />}
          </button>
        </div>
      </div>

      {/* ── Breadcrumbs Row (Path Navigation) ───────────────────────── */}
      {activeFile && (
        <div className="h-6 min-h-[24px] px-3.5 bg-[#0a0a0c] border-b border-surface-variant/30 flex items-center gap-1.5 text-[11px] font-mono text-on-surface-variant/60 select-none shrink-0">
          <span className="material-symbols-outlined text-[13px] text-primary/70">folder</span>
          <span className="hover:text-on-surface transition-colors cursor-default truncate max-w-[120px]">
            {activeWorkspaces[0]?.name || "workspace"}
          </span>
          <span className="text-white/20">›</span>
          <FileIcon filename={activeFile.name} size={13} />
          <span className="text-on-surface/90 font-medium truncate">
            {activeFile.name}
          </span>
        </div>
      )}

      {/* ── Editor Canvas Area ──────────────────────────────────────────────── */}
      <div className={`flex-1 min-h-0 relative ${splitPath ? "grid grid-cols-2 divide-x divide-surface-variant" : "flex flex-col"}`}>
        <MonacoPane filePath={activePath} />
        {splitPath ? <MonacoPane filePath={splitPath} /> : null}
      </div>

      {isDebugging && <DebugPanel />}

      {/* ── Editor Status Bar ─────────────────────────────────────────────── */}
      <div className="h-6 min-h-[24px] bg-[#0e1014] border-t border-surface-variant/40 flex items-center justify-between px-3 font-mono text-[10.5px] text-on-surface-variant select-none shrink-0">
        <div className="flex items-center gap-3">
          <span>UTF-8</span>
          <span>LF</span>
          <span>{activeFile ? getLanguageFromPath(activeFile.path).toUpperCase() : "PLAINTEXT"}</span>
          <div className="h-2.5 w-[1px] bg-white/10" />
          {/* AI Autocomplete Status Indicator */}
          {isFetchingCompletion ? (
            <span className="flex items-center gap-1 text-primary animate-pulse font-mono">
              <Loader2 size={10} className="animate-spin" />
              <span>AI completion…</span>
            </span>
          ) : (
            <span
              className="flex items-center gap-1 text-on-surface-variant/60 hover:text-on-surface-variant transition-colors font-mono cursor-default"
              title="AI Ghost-text Autocomplete active. Press Tab to accept suggestion, Esc to dismiss."
            >
              <Sparkles size={10} className="text-primary/70" />
              <span>AI Tab</span>
              {lastLatencyMs && <span className="text-[9px] opacity-60">({lastLatencyMs}ms)</span>}
            </span>
          )}
        </div>
        <div className="flex items-center gap-3">
          <span>Ln {cursorPosition.line}, Col {cursorPosition.col}</span>
          <span className="flex items-center gap-1" title={`${markerStats.errors} error(s)`}>
            <span className="material-symbols-outlined text-[12px] text-error">error</span> {markerStats.errors}
          </span>
          <span className="flex items-center gap-1" title={`${markerStats.warnings} warning(s)`}>
            <span className="material-symbols-outlined text-[12px] text-tertiary">warning</span> {markerStats.warnings}
          </span>
        </div>
      </div>
    </section>
  );
}
