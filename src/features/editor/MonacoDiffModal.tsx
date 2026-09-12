import React, { useEffect, useState } from "react";
import { DiffEditor } from "@monaco-editor/react";
import { X, Copy, Check, FileDiff, ExternalLink } from "lucide-react";

export interface DiffData {
  path: string;
  original: string;
  updated: string;
  diff?: string;
  title?: string;
}

export function parseUnifiedDiff(diffText: string): { original: string; updated: string } {
  if (!diffText) return { original: "", updated: "" };
  const origLines: string[] = [];
  const updLines: string[] = [];

  const lines = diffText.split("\n");
  let inHunk = false;

  for (const line of lines) {
    if (line.startsWith("@@")) {
      inHunk = true;
      continue;
    }
    if (!inHunk) continue;

    if (line.startsWith("-")) {
      origLines.push(line.slice(1));
    } else if (line.startsWith("+")) {
      updLines.push(line.slice(1));
    } else if (line.startsWith(" ")) {
      origLines.push(line.slice(1));
      updLines.push(line.slice(1));
    } else if (line === "") {
      origLines.push("");
      updLines.push("");
    }
  }

  return {
    original: origLines.join("\n"),
    updated: updLines.join("\n"),
  };
}

export function getLanguageFromPath(filePath: string | null): string {
  if (!filePath) return "plaintext";
  const ext = filePath.split(".").pop()?.toLowerCase();
  const map: Record<string, string> = {
    cpp: "cpp",
    cc: "cpp",
    cxx: "cpp",
    hpp: "cpp",
    c: "c",
    h: "c",
    py: "python",
    ts: "typescript",
    tsx: "typescript",
    js: "javascript",
    jsx: "javascript",
    json: "json",
    rs: "rust",
    go: "go",
    java: "java",
    html: "html",
    css: "css",
    md: "markdown",
    markdown: "markdown",
    sh: "shell",
    bash: "shell",
    yaml: "yaml",
    yml: "yaml",
  };
  return ext ? (map[ext] || "plaintext") : "plaintext";
}

export function MonacoDiffViewer({
  original,
  modified,
  language = "plaintext",
  height = "100%",
  readOnly = true,
}: {
  original: string;
  modified: string;
  language?: string;
  height?: string | number;
  readOnly?: boolean;
}) {
  return (
    <div
      data-testid="monaco-diff-editor"
      className="w-full h-full min-h-[220px] relative overflow-hidden bg-[#0d0e11] rounded"
    >
      <DiffEditor
        height={height}
        language={language}
        original={original}
        modified={modified}
        theme="vs-dark"
        options={{
          readOnly,
          renderSideBySide: true,
          minimap: { enabled: false },
          scrollBeyondLastLine: false,
          fontSize: 12.5,
          lineNumbers: "on",
          wordWrap: "on",
          automaticLayout: true,
          diffWordWrap: "on",
        }}
        loading={
          <div className="flex items-center justify-center h-full text-xs text-on-surface-variant font-mono">
            Loading Diff Editor...
          </div>
        }
      />
    </div>
  );
}

export function MonacoDiffModal({
  data,
  onClose,
}: {
  data: DiffData | null;
  onClose: () => void;
}) {
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        onClose();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);

  if (!data) return null;

  let orig = data.original;
  let upd = data.updated;
  if (!orig && !upd && data.diff) {
    const parsed = parseUnifiedDiff(data.diff);
    orig = parsed.original;
    upd = parsed.updated;
  }

  const lang = getLanguageFromPath(data.path);
  const title = data.title || `Diff: ${data.path}`;

  const handleCopy = () => {
    void navigator.clipboard.writeText(upd);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div
      data-testid="monaco-diff-modal"
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/75 backdrop-blur-sm animate-fade-in"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="w-full max-w-5xl h-[85vh] flex flex-col bg-[#121316] border border-white/10 rounded-xl shadow-2xl overflow-hidden animate-scale-in">
        {/* Modal Header */}
        <div className="px-5 py-3 bg-[#18191e] border-b border-white/10 flex items-center justify-between shrink-0">
          <div className="flex items-center gap-2.5 min-w-0 flex-1">
            <FileDiff size={16} className="text-primary shrink-0" />
            <span className="font-semibold text-sm text-on-surface truncate font-mono">
              {title}
            </span>
            <span className="px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider bg-white/5 border border-white/10 text-on-surface-variant shrink-0">
              {lang}
            </span>
          </div>

          <div className="flex items-center gap-2 shrink-0">
            <button
              type="button"
              onClick={handleCopy}
              className="px-2.5 py-1 rounded bg-white/5 hover:bg-white/10 text-on-surface text-xs font-medium border border-white/10 flex items-center gap-1.5 transition-colors cursor-pointer"
            >
              {copied ? <Check size={12} className="text-emerald-400" /> : <Copy size={12} />}
              <span>{copied ? "Copied" : "Copy modified"}</span>
            </button>
            <button
              type="button"
              data-testid="close-diff-modal"
              onClick={onClose}
              className="p-1 rounded text-on-surface-variant hover:text-on-surface hover:bg-white/10 transition-colors cursor-pointer"
            >
              <X size={18} />
            </button>
          </div>
        </div>

        {/* Side-by-Side Label Header */}
        <div className="grid grid-cols-2 bg-[#141519] border-b border-white/5 text-[11px] font-mono text-on-surface-variant px-4 py-1.5 shrink-0">
          <div className="text-rose-400 font-semibold flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full bg-rose-500" />
            Original Code (Before)
          </div>
          <div className="text-emerald-400 font-semibold flex items-center gap-1.5 pl-4 border-l border-white/5">
            <span className="w-2 h-2 rounded-full bg-emerald-500" />
            Modified Code (After)
          </div>
        </div>

        {/* Monaco Diff Viewer Body */}
        <div className="flex-1 p-2 bg-[#0d0e11] overflow-hidden">
          <MonacoDiffViewer
            original={orig}
            modified={upd}
            language={lang}
            height="100%"
            readOnly={true}
          />
        </div>
      </div>
    </div>
  );
}
