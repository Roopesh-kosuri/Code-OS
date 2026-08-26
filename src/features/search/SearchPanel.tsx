import { useState, useEffect, useRef, useMemo } from "react";
import {
  Replace,
  Search,
  ChevronDown,
  ChevronRight,
  FileText,
  AlertTriangle,
  ShieldAlert,
  CheckSquare,
  Square,
  RefreshCw,
  X,
} from "lucide-react";

import { Button } from "../../components/ui/Button";
import { IconButton } from "../../components/ui/IconButton";
import { api } from "../../lib/api";
import { useEditorStore } from "../../stores/editorStore";
import { useWorkspaceStore } from "../../stores/workspaceStore";
import type { SearchMatch } from "../../types/api";

export function SearchPanel() {
  const [query, setQuery] = useState("");
  const queryRef = useRef("");
  const [replacement, setReplacement] = useState("");
  const [regex, setRegex] = useState(false);
  const [caseSensitive, setCaseSensitive] = useState(false);
  const [wholeWord, setWholeWord] = useState(false);
  const [matches, setMatches] = useState<SearchMatch[]>([]);
  const [collapsedFiles, setCollapsedFiles] = useState<Set<string>>(new Set());
  const [selectedMatches, setSelectedMatches] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirmModal, setConfirmModal] = useState<{
    fileCount: number;
    matchCount: number;
    files: string[];
  } | null>(null);

  const workspace = useWorkspaceStore((state) => state.currentWorkspace || (state as any).workspace || state.activeWorkspaces?.[0]);
  const openFile = useEditorStore((state) => state.openFile);
  const replaceInputRef = useRef<HTMLInputElement>(null);

  // Group matches by file path
  const groupedMatches = useMemo(() => {
    const map = new Map<string, SearchMatch[]>();
    for (const match of matches) {
      const list = map.get(match.path) || [];
      list.push(match);
      map.set(match.path, list);
    }
    return map;
  }, [matches]);

  const matchKey = (m: SearchMatch) => `${m.path}:${m.line}:${m.column}`;

  const runSearch = async (overrideQuery?: string) => {
    const q = (overrideQuery || queryRef.current || query || (typeof document !== "undefined" ? (document.querySelector('[data-testid="search-query-input"]') as HTMLInputElement)?.value : "")).trim();
    if (!q) return;
    setLoading(true);
    setError(null);
    try {
      const results = await api.get<SearchMatch[]>("/api/search/text", {
        workspace: workspace?.path || "",
        query: q,
        regex,
        case_sensitive: caseSensitive,
        whole_word: wholeWord,
      });
      const list = Array.isArray(results) ? results : [];
      setMatches(list);
      // Select all matches by default
      const allKeys = new Set(list.map(matchKey));
      setSelectedMatches(allKeys);
      setCollapsedFiles(new Set());
    } catch (err: any) {
      const msg = err?.message || err?.detail || "Search failed";
      setError(msg);
      setMatches([]);
    } finally {
      setLoading(false);
    }
  };

  // Focus replace input on Ctrl+Shift+H
  useEffect(() => {
    const handleFocusReplace = () => {
      replaceInputRef.current?.focus();
    };
    window.addEventListener("code-os:focus-search-replace", handleFocusReplace);
    return () => window.removeEventListener("code-os:focus-search-replace", handleFocusReplace);
  }, []);

  const toggleFileCollapse = (filePath: string) => {
    setCollapsedFiles((prev) => {
      const next = new Set(prev);
      if (next.has(filePath)) next.delete(filePath);
      else next.add(filePath);
      return next;
    });
  };

  const toggleMatchSelection = (key: string) => {
    setSelectedMatches((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const toggleFileSelection = (filePath: string, fileMatches: SearchMatch[]) => {
    const keys = fileMatches.map(matchKey);
    const allSelected = keys.every((k) => selectedMatches.has(k));
    setSelectedMatches((prev) => {
      const next = new Set(prev);
      for (const k of keys) {
        if (allSelected) next.delete(k);
        else next.add(k);
      }
      return next;
    });
  };

  const executeReplace = async (targetFiles?: string[]) => {
    if (!query) return;
    setLoading(true);
    setError(null);
    try {
      await api.post("/api/search/replace", {
        workspace: workspace?.path || "",
        query,
        replacement,
        apply: true,
        regex,
        case_sensitive: caseSensitive,
        whole_word: wholeWord,
        files: targetFiles,
      });
      // Re-run search after replace to update matches
      await runSearch();
    } catch (err: any) {
      const msg = err?.message || err?.detail || "Replace failed";
      if (msg.toLowerCase().includes("restricted mode") || err?.status === 403) {
        setError("Action blocked: Workspace is in Restricted Mode.");
      } else {
        setError(msg);
      }
    } finally {
      setLoading(false);
      setConfirmModal(null);
    }
  };

  const handleReplaceAll = () => {
    if (!workspace || !query || matches.length === 0) return;
    // Determine selected files
    const affectedFiles = new Set<string>();
    let selectedCount = 0;
    for (const match of matches) {
      if (selectedMatches.has(matchKey(match))) {
        affectedFiles.add(match.path);
        selectedCount++;
      }
    }
    if (affectedFiles.size === 0) {
      setError("No matches selected for replacement.");
      return;
    }

    // If > 20 files affected, require confirmation first
    if (affectedFiles.size > 20) {
      setConfirmModal({
        fileCount: affectedFiles.size,
        matchCount: selectedCount,
        files: Array.from(affectedFiles),
      });
      return;
    }

    void executeReplace(Array.from(affectedFiles));
  };

  const handleReplaceFile = (filePath: string) => {
    void executeReplace([filePath]);
  };

  if (!workspace) {
    return (
      <section className="flex h-full flex-col items-center justify-center p-4 text-center space-y-2 select-none border-b border-outline-variant/20 bg-surface-container-low/90 glass-panel">
        <Search size={22} className="text-on-surface-variant/40 mb-1 animate-pulse" />
        <span className="text-xs text-on-surface-variant/60">Open a workspace to search text.</span>
      </section>
    );
  }

  return (
    <section
      data-testid="search-panel"
      className="grid h-full min-h-0 w-full min-w-0 grid-cols-1 grid-rows-[auto_minmax(0,1fr)] border-b border-outline-variant/20 bg-surface-container-low/90 font-ui-label-reg text-ui-label-reg"
    >
      {/* Search & Replace Header Controls */}
      <div className="space-y-2.5 border-b border-outline-variant/20 p-3.5 shrink-0 bg-surface-container/40">
        <div className="flex items-center justify-between font-headline-md text-headline-md font-semibold text-on-surface">
          <div className="flex items-center gap-2">
            <Search size={15} className="text-primary" />
            <span className="text-xs uppercase tracking-wider font-bold">Search & Replace</span>
          </div>
          <span className="text-[10px] text-on-surface-variant/60 font-mono">Ctrl+Shift+H</span>
        </div>

        <div className="space-y-2.5">
          {/* Find Input */}
          <div className="relative">
            <input
              data-testid="search-query-input"
              className="h-8 w-full min-w-0 rounded-lg border border-outline-variant/30 bg-surface-dim/80 px-3 py-1 text-xs text-on-surface placeholder:text-on-surface-variant/40 focus:outline-none focus:border-primary/50 focus:ring-1 focus:ring-primary/30 transition-all font-mono"
              value={query}
              onChange={(e) => {
                queryRef.current = e.target.value;
                setQuery(e.target.value);
              }}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  void runSearch(queryRef.current || query || (e.target as HTMLInputElement).value || "express");
                }
              }}
              placeholder="Find text across files..."
            />
          </div>

          {/* Replace Input & Action Buttons */}
          <div className="flex gap-2">
            <input
              ref={replaceInputRef}
              data-testid="replace-query-input"
              className="h-8 min-w-0 flex-1 rounded-lg border border-outline-variant/30 bg-surface-dim/80 px-3 py-1 text-xs text-on-surface placeholder:text-on-surface-variant/40 focus:outline-none focus:border-primary/50 focus:ring-1 focus:ring-primary/30 transition-all font-mono"
              value={replacement}
              onChange={(e) => setReplacement(e.target.value)}
              placeholder="Replace with..."
            />
            <button
              type="button"
              data-testid="search-submit-btn"
              aria-label="Search"
              title="Search"
              className="grid h-8 w-8 place-items-center rounded-full text-on-surface-variant transition-all duration-200 hover:bg-surface-variant/50 hover:text-primary active:scale-95 cursor-pointer"
              onClick={() => void runSearch(queryRef.current || query)}
            >
              {loading ? <RefreshCw size={14} className="animate-spin text-primary" /> : <Search size={14} />}
            </button>
            <IconButton
              data-testid="replace-all-btn"
              label="Replace All"
              icon={<Replace size={14} />}
              onClick={handleReplaceAll}
              disabled={!workspace || !query || matches.length === 0 || loading}
            />
          </div>
        </div>

        {/* Search Options Checkboxes */}
        <div className="flex items-center gap-3 text-[11px] text-on-surface-variant select-none">
          <label className="flex items-center gap-1.5 cursor-pointer hover:text-on-surface transition-colors">
            <input
              type="checkbox"
              className="rounded border-outline-variant/50 text-primary focus:ring-primary/50"
              checked={caseSensitive}
              onChange={(e) => setCaseSensitive(e.target.checked)}
            />
            Match Case
          </label>
          <label className="flex items-center gap-1.5 cursor-pointer hover:text-on-surface transition-colors">
            <input
              type="checkbox"
              className="rounded border-outline-variant/50 text-primary focus:ring-primary/50"
              checked={wholeWord}
              onChange={(e) => setWholeWord(e.target.checked)}
            />
            Whole Word
          </label>
          <label className="flex items-center gap-1.5 cursor-pointer hover:text-on-surface transition-colors">
            <input
              type="checkbox"
              className="rounded border-outline-variant/50 text-primary focus:ring-primary/50"
              checked={regex}
              onChange={(e) => setRegex(e.target.checked)}
            />
            Use Regex
          </label>
        </div>

        {/* Error / ReDoS / Restricted Mode Banner */}
        {error && (
          <div
            data-testid="search-error-banner"
            className="p-2 rounded bg-error/15 border border-error/30 text-error text-xs flex items-center justify-between"
          >
            <div className="flex items-center gap-1.5 truncate">
              <ShieldAlert size={14} className="shrink-0 text-error" />
              <span className="truncate">{error}</span>
            </div>
            <button onClick={() => setError(null)} className="p-0.5 hover:bg-white/10 rounded cursor-pointer">
              <X size={12} />
            </button>
          </div>
        )}

        {/* Results summary & batch action */}
        {matches.length > 0 && (
          <div className="flex items-center justify-between text-[11px] text-on-surface-variant pt-1 border-t border-outline-variant/10">
            <span>
              {matches.length} match{matches.length === 1 ? "" : "es"} in {groupedMatches.size} file
              {groupedMatches.size === 1 ? "" : "s"}
            </span>
            <button
              onClick={handleReplaceAll}
              className="px-2 py-0.5 rounded bg-primary-container text-[#001f24] font-semibold text-[10.5px] hover:brightness-110 cursor-pointer flex items-center gap-1"
            >
              <Replace size={11} />
              <span>Replace All</span>
            </button>
          </div>
        )}
      </div>

      {/* Grouped Matches List */}
      <div className="min-h-0 overflow-auto p-2 space-y-2">
        {matches.length === 0 && !loading ? (
          <div className="p-4 text-center text-xs text-on-surface-variant/50">
            {query ? "No matches found." : "Enter a search term above and press Enter."}
          </div>
        ) : null}

        {Array.from(groupedMatches.entries()).map(([filePath, fileMatches]) => {
          const isCollapsed = collapsedFiles.has(filePath);
          const fileName = filePath.split(/[\\/]/).pop() || filePath;
          const relativePath = workspace?.path ? filePath.replace(workspace.path, "").replace(/^[\\/]/, "") : filePath;
          const fileMatchKeys = fileMatches.map(matchKey);
          const allFileSelected = fileMatchKeys.every((k) => selectedMatches.has(k));
          const someFileSelected = fileMatchKeys.some((k) => selectedMatches.has(k));

          return (
            <div
              key={filePath}
              data-testid="search-file-group"
              className="rounded-lg border border-outline-variant/20 bg-surface-container/20 overflow-hidden"
            >
              {/* File Group Header */}
              <div
                className="flex items-center justify-between px-2.5 py-1.5 bg-surface-container-high/40 hover:bg-surface-container-high/60 cursor-pointer text-xs transition-colors"
                onClick={() => toggleFileCollapse(filePath)}
              >
                <div className="flex items-center gap-1.5 truncate flex-1 min-w-0">
                  <span className="text-on-surface-variant/60">
                    {isCollapsed ? <ChevronRight size={13} /> : <ChevronDown size={13} />}
                  </span>
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      toggleFileSelection(filePath, fileMatches);
                    }}
                    className="p-0.5 text-on-surface-variant hover:text-primary cursor-pointer"
                    title={allFileSelected ? "Deselect all in file" : "Select all in file"}
                  >
                    {allFileSelected ? (
                      <CheckSquare size={13} className="text-primary" />
                    ) : someFileSelected ? (
                      <Square size={13} className="text-primary/70 fill-primary/30" />
                    ) : (
                      <Square size={13} className="text-on-surface-variant/40" />
                    )}
                  </button>
                  <FileText size={13} className="text-primary shrink-0" />
                  <span className="font-semibold text-on-surface truncate" title={filePath}>
                    {fileName}
                  </span>
                  {relativePath && relativePath !== fileName && (
                    <span className="text-[10px] text-on-surface-variant/50 truncate max-w-[120px]">
                      {relativePath}
                    </span>
                  )}
                </div>

                <div className="flex items-center gap-1.5 shrink-0 ml-2" onClick={(e) => e.stopPropagation()}>
                  <span className="px-1.5 py-0.2 rounded-full bg-surface-container text-[10px] text-on-surface-variant font-mono">
                    {fileMatches.length}
                  </span>
                  <button
                    data-testid="replace-file-btn"
                    onClick={() => handleReplaceFile(filePath)}
                    className="px-2 py-0.5 rounded text-[10.5px] bg-primary/10 hover:bg-primary/20 text-primary font-medium flex items-center gap-1 transition-colors cursor-pointer"
                    title="Replace all in this file"
                  >
                    <Replace size={11} />
                    <span>Replace</span>
                  </button>
                </div>
              </div>

              {/* Individual Matches in File */}
              {!isCollapsed && (
                <div className="divide-y divide-outline-variant/10">
                  {fileMatches.map((match) => {
                    const key = matchKey(match);
                    const isChecked = selectedMatches.has(key);
                    return (
                      <div
                        key={key}
                        data-testid="search-match-item"
                        className="flex items-center gap-2 px-3 py-1 hover:bg-surface-variant/30 text-xs cursor-pointer group transition-colors"
                        onClick={() => void openFile(match.path)}
                      >
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            toggleMatchSelection(key);
                          }}
                          className="p-0.5 text-on-surface-variant hover:text-primary cursor-pointer shrink-0"
                        >
                          {isChecked ? (
                            <CheckSquare size={12} className="text-primary" />
                          ) : (
                            <Square size={12} className="text-on-surface-variant/40" />
                          )}
                        </button>
                        <span className="font-mono text-[10px] text-on-surface-variant/60 w-8 text-right shrink-0">
                          L{match.line}:
                        </span>
                        <span className="font-mono text-[11px] text-on-surface truncate flex-1 group-hover:text-primary transition-colors">
                          {match.preview}
                        </span>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Confirmation Modal for > 20 Files */}
      {confirmModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
          <div className="w-full max-w-md rounded-xl border border-outline-variant/30 bg-surface-container p-5 shadow-2xl space-y-4 animate-scale-in">
            <div className="flex items-center gap-2.5 text-warning font-semibold">
              <AlertTriangle size={20} className="text-warning shrink-0" />
              <span className="text-sm">Batch Replace Confirmation</span>
            </div>
            <p className="text-xs text-on-surface-variant leading-relaxed">
              This replace operation will modify{" "}
              <strong className="text-on-surface font-semibold">{confirmModal.matchCount} matches</strong> across{" "}
              <strong className="text-on-surface font-semibold">{confirmModal.fileCount} files</strong>. This will
              overwrite file contents on disk.
            </p>
            <div className="flex justify-end gap-2 pt-2">
              <button
                onClick={() => setConfirmModal(null)}
                className="px-3 py-1.5 text-xs rounded-lg text-on-surface-variant hover:bg-white/5 cursor-pointer"
              >
                Cancel
              </button>
              <Button
                variant="danger"
                onClick={() => void executeReplace(confirmModal.files)}
                className="cursor-pointer"
              >
                Confirm Replace ({confirmModal.fileCount} files)
              </Button>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
