import { lazy, Suspense, useEffect, useState, useRef, useCallback } from "react";
import {
  Columns2,
  Replace,
  Save,
  SaveAll,
  Search,
  X,
  FolderOpen,
  Loader2,
  Sparkles,
  ChevronRight,
  FileCode,
  Check,
  Play,
  Square,
  Bug,
  Eye,
  GitBranch,
} from "lucide-react";
import * as monaco from "monaco-editor";
import Editor, { loader } from "@monaco-editor/react";

loader.config({ monaco });

import "./monacoWorkers";
import { registerIntellisenseProviders, disposeIntellisenseProviders } from "./intellisenseProviders";
import { parseDiagnostics, type ParsedDiagnostic } from "./errorLensParser";
import { MarkdownPreview } from "./MarkdownPreview";

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
import { api } from "../../lib/api";

function formatRelativeTime(timestamp: number): string {
  if (!timestamp) return "";
  const now = Math.floor(Date.now() / 1000);
  const diff = now - timestamp;
  if (diff < 60) return "just now";
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  if (diff < 2592000) return `${Math.floor(diff / 86400)}d ago`;
  if (diff < 31536000) return `${Math.floor(diff / 2592000)}mo ago`;
  return `${Math.floor(diff / 31536000)}y ago`;
}

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
    markdown: "markdown",
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
  const currentWorkspace = useWorkspaceStore((state) => state.currentWorkspace);

  const runLogs = useRunStore((state) => state.logs);
  const runStatus = useRunStore((state) => state.status);

  const [editorInstance, setEditorInstance] = useState<any>(null);
  const [monacoInstance, setMonacoInstance] = useState<any>(null);
  const [showInline, setShowInline] = useState(false);
  const [inlinePrompt, setInlinePrompt] = useState("");
  const [isIntellisenseActive, setIsIntellisenseActive] = useState(() =>
    typeof localStorage !== "undefined" ? localStorage.getItem("code-os:editor.enableIntellisense") !== "false" : true
  );
  const [isErrorLensActive, setIsErrorLensActive] = useState(() =>
    typeof localStorage !== "undefined" ? localStorage.getItem("code-os:editor.enableErrorLens") !== "false" : true
  );
  const [isGitBlameActive, setIsGitBlameActive] = useState(() =>
    typeof localStorage !== "undefined" ? localStorage.getItem("code-os:editor.enableGitBlame") === "true" : false
  );

  const [blameMap, setBlameMap] = useState<Record<number, any>>({});
  const errorLensDecorationsRef = useRef<string[]>([]);
  const blameDecorationsRef = useRef<string[]>([]);

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

  // Fetch Git Blame data
  const fetchBlame = useCallback(async () => {
    if (!currentWorkspace || !file?.path || !isGitBlameActive) {
      setBlameMap({});
      return;
    }
    try {
      const res = await api.get<{ git: boolean; lines: any[] }>("/api/git/blame", {
        workspace: currentWorkspace.path,
        file_path: file.path,
      });
      if (res?.git && Array.isArray(res.lines)) {
        const map: Record<number, any> = {};
        for (const item of res.lines) {
          map[item.line] = item;
        }
        setBlameMap(map);
      } else {
        setBlameMap({});
      }
    } catch {
      setBlameMap({});
    }
  }, [currentWorkspace?.path, file?.path, isGitBlameActive]);

  useEffect(() => {
    void fetchBlame();
  }, [fetchBlame]);

  // Error Lens: parse diagnostics & render markers + inline decorations
  useEffect(() => {
    if (!editorInstance || !monacoInstance || !file || !currentWorkspace) return;
    const model = editorInstance.getModel();
    if (!model) return;

    if (runStatus === "compiling" || runStatus === "running") {
      monacoInstance.editor.setModelMarkers(model, "error-lens", []);
      errorLensDecorationsRef.current = editorInstance.deltaDecorations(errorLensDecorationsRef.current, []);
      return;
    }

    if ((runStatus === "completed" || runStatus === "failed") && isErrorLensActive) {
      const fullLog = runLogs.map((l) => l.text).join("\n");
      const allDiags = parseDiagnostics(fullLog, currentWorkspace.path);
      const normFilePath = file.path.replace(/\\/g, "/").toLowerCase();
      const fileDiags = allDiags.filter((d) => {
        const dPath = d.filePath.replace(/\\/g, "/").toLowerCase();
        return normFilePath.endsWith(dPath) || dPath.endsWith(normFilePath);
      });

      const markers = fileDiags.map((d) => ({
        severity: d.severity === "error" ? monacoInstance.MarkerSeverity.Error : monacoInstance.MarkerSeverity.Warning,
        message: d.message,
        startLineNumber: d.line,
        startColumn: d.column || 1,
        endLineNumber: d.line,
        endColumn: 1000,
        source: `Error Lens (${d.source})`,
      }));
      monacoInstance.editor.setModelMarkers(model, "error-lens", markers);

      const decorations = fileDiags.map((d) => ({
        range: new monacoInstance.Range(d.line, 1, d.line, 1000),
        options: {
          isWholeLine: true,
          after: {
            contentText: `   ■ ${d.message}`,
            inlineClassName: d.severity === "error"
              ? "text-error/80 text-[11px] font-mono italic select-none pl-3"
              : "text-warning/80 text-[11px] font-mono italic select-none pl-3",
          },
        },
      }));
      errorLensDecorationsRef.current = editorInstance.deltaDecorations(errorLensDecorationsRef.current, decorations);
    }
  }, [runLogs, runStatus, isErrorLensActive, editorInstance, monacoInstance, file?.path, currentWorkspace?.path]);

  // Update Git Blame inline annotation on active line
  const updateBlameAnnotation = useCallback((lineNum: number) => {
    if (!editorInstance || !monacoInstance || !isGitBlameActive) {
      if (editorInstance) {
        blameDecorationsRef.current = editorInstance.deltaDecorations(blameDecorationsRef.current, []);
      }
      return;
    }
    const info = blameMap[lineNum];
    if (!info) {
      blameDecorationsRef.current = editorInstance.deltaDecorations(blameDecorationsRef.current, []);
      return;
    }

    const relTime = formatRelativeTime(info.author_time);
    const annotationText = `   ${info.author}${relTime ? `, ${relTime}` : ""} • ${info.summary}`;

    const decorations = [
      {
        range: new monacoInstance.Range(lineNum, 1, lineNum, 1000),
        options: {
          isWholeLine: true,
          after: {
            contentText: annotationText,
            inlineClassName: "text-on-surface-variant/40 text-[11px] font-mono select-none pl-4 hover:text-on-surface-variant transition-colors",
          },
        },
      },
    ];
    blameDecorationsRef.current = editorInstance.deltaDecorations(blameDecorationsRef.current, decorations);
  }, [editorInstance, monacoInstance, isGitBlameActive, blameMap]);

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
    setMonacoInstance(monaco);
    editor.focus();

    if (isIntellisenseActive) {
      registerIntellisenseProviders(monaco);
    }

    const intellisenseToggleListener = (e: Event) => {
      const enabled = (e as CustomEvent)?.detail?.enabled ?? true;
      setIsIntellisenseActive(enabled);
      if (enabled) {
        registerIntellisenseProviders(monaco);
        editor.updateOptions({
          quickSuggestions: { other: true, comments: false, strings: true },
          suggestOnTriggerCharacters: true,
          parameterHints: { enabled: true },
          snippetSuggestions: "inline",
        });
      } else {
        disposeIntellisenseProviders();
        editor.updateOptions({
          quickSuggestions: false,
          suggestOnTriggerCharacters: false,
          parameterHints: { enabled: false },
          snippetSuggestions: "none",
        });
      }
    };
    window.addEventListener("code-os:toggle-intellisense", intellisenseToggleListener);

    const errorLensToggleListener = (e: Event) => {
      const enabled = (e as CustomEvent)?.detail?.enabled ?? true;
      setIsErrorLensActive(enabled);
      if (!enabled) {
        const model = editor.getModel();
        if (model) monaco.editor.setModelMarkers(model, "error-lens", []);
        errorLensDecorationsRef.current = editor.deltaDecorations(errorLensDecorationsRef.current, []);
      }
    };
    window.addEventListener("code-os:toggle-error-lens", errorLensToggleListener);

    const blameToggleListener = (e: Event) => {
      const enabled = (e as CustomEvent)?.detail?.enabled ?? false;
      setIsGitBlameActive(enabled);
      if (!enabled) {
        blameDecorationsRef.current = editor.deltaDecorations(blameDecorationsRef.current, []);
      }
    };
    window.addEventListener("code-os:toggle-git-blame", blameToggleListener);

    editor.onDidDispose(() => {
      window.removeEventListener("code-os:toggle-intellisense", intellisenseToggleListener);
      window.removeEventListener("code-os:toggle-error-lens", errorLensToggleListener);
      window.removeEventListener("code-os:toggle-git-blame", blameToggleListener);
    });

    const focusHandler = (e: Event) => {
      const detail = (e as CustomEvent)?.detail;
      if (!detail?.path || detail.path === file.path) {
        editor.focus();
      }
    };
    window.addEventListener("code-os:focus-editor", focusHandler);
    editor.onDidDispose(() => {
      window.removeEventListener("code-os:focus-editor", focusHandler);
    });

    monaco.editor.setTheme("vs-stitch-dark");
    registerInlineCompletionProvider(monaco);
    installDebugDecorations(editor, monaco, file.path);

    editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyI, () => {
      setShowInline(true);
    });

    // On file edit: clear stale error lens diagnostics for this file
    editor.onDidChangeModelContent(() => {
      const model = editor.getModel();
      if (model) {
        monaco.editor.setModelMarkers(model, "error-lens", []);
      }
      errorLensDecorationsRef.current = editor.deltaDecorations(errorLensDecorationsRef.current, []);
    });

    // On cursor move: update cursor status & blame annotation
    editor.onDidChangeCursorPosition((e: any) => {
      useEditorStore.getState().setCursorPosition({
        line: e.position.lineNumber,
        col: e.position.column,
      });
      updateBlameAnnotation(e.position.lineNumber);
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
            <span className="text-[11px] text-on-surface-variant font-mono">Loading editor.</span>
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
              mode: "subwordSmart",
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
  const [showMarkdownPreview, setShowMarkdownPreview] = useState(false);

  const openFiles = useEditorStore((state) => state.openFiles);
  const activePath = useEditorStore((state) => state.activePath);
  const splitPath = useEditorStore((state) => state.splitPath);
  const autoSave = useEditorStore((state) => state.autoSave);
  const tabSize = useEditorStore((state) => state.tabSize);
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

  const isMarkdown = activeFile?.path?.toLowerCase().endsWith(".md") || activeFile?.path?.toLowerCase().endsWith(".markdown");

  useEffect(() => debugClient.subscribe((state) => setIsDebugging(state.active)), []);

  // Ctrl+Shift+V Markdown Preview shortcut
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.shiftKey && (e.key === "V" || e.key === "v")) {
        if (isMarkdown) {
          e.preventDefault();
          setShowMarkdownPreview((v) => !v);
        }
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isMarkdown]);

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
    if (!activePath || !activeFile) return;
    if (activeFile.dirty) await saveFile(activePath);
    window.dispatchEvent(new CustomEvent("code-os:menu", { detail: "view.switchUtility:debug" }));
    window.dispatchEvent(new CustomEvent("code-os:menu", { detail: "view.openTerminal" }));
    if (getLanguageFromPath(activePath) === "python") {
      await debugClient.start(activePath);
    }
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
      {/* File Tabs Header Row */}
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
                onClick={() => useEditorStore.setState({ activePath: file.path })}
                className={`group flex items-center gap-2 px-3 h-full cursor-pointer border-r border-surface-variant/30 text-xs transition-all relative ${
                  isActive
                    ? "bg-[#0a0a0c] text-on-surface font-medium border-t-2 border-t-primary"
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
          {/* Markdown Preview toggle */}
          {isMarkdown && (
            <button
              title="Toggle Markdown Preview (Ctrl+Shift+V)"
              onClick={() => setShowMarkdownPreview((v) => !v)}
              className={`h-7 px-2 flex items-center gap-1 rounded-lg text-xs font-mono transition-colors cursor-pointer ${
                showMarkdownPreview
                  ? "bg-primary-container/20 text-primary border border-primary/30"
                  : "hover:text-on-surface hover:bg-white/5"
              }`}
            >
              <Eye size={13} />
              <span className="text-[10.5px]">Preview</span>
            </button>
          )}

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
              <span className="text-outline-variant text-[10px]"> </span>
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

          {/* Run / Stop Action Button */}
          <button
            data-testid="editor-run-btn"
            title={isRunning ? "Stop execution" : "Run file in terminal"}
            onClick={() => void handleRunOrStop()}
            className={`h-7 px-3 flex items-center gap-1.5 rounded-lg text-xs font-mono font-bold transition-all shadow-sm cursor-pointer ${
              isRunning
                ? "bg-red-500/20 text-red-400 border border-red-500/30 hover:bg-red-500/30 animate-pulse"
                : "bg-primary-container text-[#001f24] hover:brightness-110 active:scale-95"
            }`}
          >
            {isRunning ? (
              <>
                <Square size={11} className="fill-red-400" />
                <span>Stop</span>
              </>
            ) : (
              <>
                <Play size={11} className="fill-current" />
                <span>Run</span>
              </>
            )}
          </button>

          {/* Split View Toggle */}
          <button
            title="Split Editor"
            onClick={handleToggleSplit}
            className={`w-7 h-7 flex items-center justify-center rounded-lg transition-colors cursor-pointer ${
              splitPath ? "bg-primary-container/15 text-primary" : "hover:text-on-surface hover:bg-white/5"
            }`}
          >
            <Columns2 size={13} />
          </button>
        </div>
      </div>

      {/* Editor Canvas Area (with Markdown Preview Split Support) */}
      <div
        className={`flex-1 min-h-0 relative ${
          showMarkdownPreview && isMarkdown
            ? "grid grid-cols-2 divide-x divide-surface-variant"
            : splitPath
            ? "grid grid-cols-2 divide-x divide-surface-variant"
            : "flex flex-col"
        }`}
      >
        <MonacoPane filePath={activePath} />
        {showMarkdownPreview && isMarkdown ? (
          <MarkdownPreview content={activeFile?.content ?? ""} />
        ) : splitPath ? (
          <MonacoPane filePath={splitPath} />
        ) : null}
      </div>

      {isDebugging && <DebugPanel />}

      {/* Editor Status Bar */}
      <div className="h-6 flex items-center justify-between px-3 bg-[#0a0a0c] border-t border-surface-variant/30 text-[10.5px] font-mono text-on-surface-variant/70 shrink-0 select-none">
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-1 hover:text-on-surface transition-colors">
            <span className="text-red-400 font-bold">{markerStats.errors}</span> errors
            <span className="text-amber-400 font-bold ml-1">{markerStats.warnings}</span> warnings
          </div>

          {activeFile && (
            <span className="text-on-surface-variant/40">|</span>
          )}

          {activeFile && (
            <span className="text-cyan-400 font-medium">
              {getLanguageFromPath(activeFile.path)}
            </span>
          )}
        </div>

        <div className="flex items-center gap-3">
          {isFetchingCompletion && (
            <div className="flex items-center gap-1 text-primary-container animate-pulse">
              <Sparkles size={11} />
              <span>AI Generating...</span>
            </div>
          )}

          {!isFetchingCompletion && lastLatencyMs !== null && (
            <span className="text-on-surface-variant/50 text-[9.5px]">
              AI: {lastLatencyMs}ms
            </span>
          )}

          <span>Ln {cursorPosition.line}, Col {cursorPosition.col}</span>
          <span>Spaces: {tabSize}</span>
          <span>UTF-8</span>
        </div>
      </div>
    </section>
  );
}
