import { lazy, Suspense, useState } from "react";
import { Columns2, Replace, Save, SaveAll, Search, X, FolderOpen, Loader2 } from "lucide-react";
import * as monaco from "monaco-editor";
import Editor, { loader } from "@monaco-editor/react";

loader.config({ monaco });

import { Button } from "../../components/ui/Button";
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
    editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyI, () => {
      setShowInline(true);
    });
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
            minimap: { enabled: true },
            fontSize,
            fontFamily: "JetBrains Mono, Cascadia Code, Consolas, monospace",
            automaticLayout: true,
            wordWrap: "on",
            scrollBeyondLastLine: false,
            tabSize,
            renderWhitespace: "selection",
            glyphMargin: false,
            lineNumbersMinChars: 3,
            lineDecorationsWidth: 4,
            showFoldingControls: "mouseover",
            padding: { top: 6, bottom: 6 },
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
  
  const activeWorkspaces = useWorkspaceStore((state) => state.activeWorkspaces);
  const openWorkspace = useWorkspaceStore((state) => state.openWorkspace);

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
    <section data-testid="editor-panel" className="grid h-full min-h-0 grid-rows-[42px_minmax(0,1fr)_26px] bg-[#0a0a0c]">
      {/* ── File Tabs Header Row (Google Stitch Pill Tabs) ───────────────────── */}
      <div className="flex items-center justify-between px-3 bg-surface-container-low/80 backdrop-blur-sm border-b border-surface-variant z-10 select-none overflow-hidden">
        {/* Pill Tabs List */}
        <div className="flex items-center gap-2 overflow-x-auto no-scrollbar py-1.5 flex-1 min-w-0" role="tablist">
          {openFiles.map((file) => {
            const isActive = file.path === activePath;
            const isPy = file.name.endsWith(".py");
            const isHtml = file.name.endsWith(".html");
            const isCss = file.name.endsWith(".css");
            const isJs = file.name.endsWith(".js") || file.name.endsWith(".ts") || file.name.endsWith(".tsx");

            return (
              <div
                key={file.path}
                role="tab"
                aria-selected={isActive}
                onClick={() => {
                  useWorkspaceStore.getState().selectWorkspaceForPath(file.path);
                  useEditorStore.setState({ activePath: file.path });
                }}
                className={`flex items-center gap-2 px-3.5 py-1 rounded-full cursor-pointer group transition-all duration-150 shrink-0 text-xs ${
                  isActive
                    ? "bg-primary-container/10 border border-primary-container/30 text-primary-container shadow-sm font-semibold"
                    : "hover:bg-surface-variant/50 text-on-surface-variant hover:text-on-surface border border-transparent"
                }`}
              >
                <span className={`material-symbols-outlined text-[14px] shrink-0 ${
                  isActive
                    ? "text-primary-container"
                    : isHtml
                      ? "text-error"
                      : isCss
                        ? "text-secondary"
                        : "text-on-surface-variant"
                }`}>
                  {isPy || isJs ? "data_object" : isHtml ? "html" : isCss ? "style" : "description"}
                </span>

                <span className="truncate max-w-[140px] font-mono text-[12px]">{file.name}</span>

                {file.dirty && (
                  <div className="w-1.5 h-1.5 rounded-full bg-primary-container ml-0.5 shrink-0" />
                )}

                <span
                  role="button"
                  aria-label="Close tab"
                  onClick={(event) => {
                    event.stopPropagation();
                    closeFile(file.path);
                  }}
                  className="material-symbols-outlined text-[14px] text-on-surface-variant/40 group-hover:text-on-surface hover:bg-surface-variant rounded p-0.5 shrink-0 transition-colors ml-1"
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
              showSearch ? "bg-primary-container/15 text-primary-container" : "hover:text-on-surface hover:bg-white/5"
            }`}
          >
            <Search size={13} />
          </button>

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
                className="w-5 h-5 flex items-center justify-center text-on-surface-variant hover:text-primary-container disabled:opacity-30 cursor-pointer"
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
              onChange={(e) => setAutoSave(e.target.checked)}
              className="rounded accent-primary-container w-3 h-3"
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
              splitPath ? "text-primary-container bg-primary-container/15" : "hover:text-on-surface hover:bg-white/5"
            }`}
          >
            {splitPath ? <X size={13} /> : <Columns2 size={13} />}
          </button>
        </div>
      </div>

      {/* ── Editor Canvas Area ──────────────────────────────────────────────── */}
      <div className={splitPath ? "grid h-full min-h-0 grid-cols-2 divide-x divide-surface-variant" : "h-full min-h-0"}>
        <MonacoPane filePath={activePath} />
        {splitPath ? <MonacoPane filePath={splitPath} /> : null}
      </div>

      {/* ── Editor Status Bar (Google Stitch Bottom Bar) ───────────────────── */}
      <div className="h-6.5 bg-surface-container-low/50 border-t border-surface-variant flex items-center justify-between px-4 font-code-sm text-code-sm text-on-surface-variant select-none">
        <div className="flex items-center gap-4 text-[11px]">
          <span>UTF-8</span>
          <span>LF</span>
          <span>{activeFile ? getLanguageFromPath(activeFile.path).toUpperCase() : "PLAINTEXT"}</span>
        </div>
        <div className="flex items-center gap-4 text-[11px]">
          <span>Ln 12, Col 24</span>
          <span className="flex items-center gap-1">
            <span className="material-symbols-outlined text-[13px] text-error">error</span> 0
          </span>
          <span className="flex items-center gap-1">
            <span className="material-symbols-outlined text-[13px] text-tertiary">warning</span> 0
          </span>
        </div>
      </div>
    </section>
  );
}
