import React, { useEffect, useState } from "react";
import {
  Database,
  Search,
  RefreshCw,
  FileCode,
  ArrowUpRight,
  Sparkles,
  Layers,
  AlertCircle,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
} from "lucide-react";
import { useRAGStore, RAGChunkResult } from "./ragStore";
import { useWorkspaceStore } from "../../stores/workspaceStore";
import { useEditorStore } from "../../stores/editorStore";

export function SemanticSearchPanel() {
  const currentWorkspace = useWorkspaceStore((s) => s.currentWorkspace);
  const indexStatus = useRAGStore((s) => s.indexStatus);
  const searchResults = useRAGStore((s) => s.searchResults);
  const searchQuery = useRAGStore((s) => s.searchQuery);
  const setSearchQuery = useRAGStore((s) => s.setSearchQuery);
  const isIndexing = useRAGStore((s) => s.isIndexing);
  const isSearching = useRAGStore((s) => s.isSearching);
  const error = useRAGStore((s) => s.error);
  const indexWorkspace = useRAGStore((s) => s.indexWorkspace);
  const search = useRAGStore((s) => s.search);
  const checkStatus = useRAGStore((s) => s.checkStatus);
  const openFile = useEditorStore((s) => s.openFile);

  const [expandedChunk, setExpandedChunk] = useState<number | null>(null);

  const wsPath = currentWorkspace?.path || "";

  useEffect(() => {
    if (wsPath) {
      void checkStatus(wsPath);
    }
  }, [wsPath, checkStatus]);

  const handleSearch = (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    if (!searchQuery.trim() || !wsPath) return;
    void search(wsPath, searchQuery, 6);
  };

  const handleIndex = () => {
    if (!wsPath) return;
    void indexWorkspace(wsPath);
  };

  const handleResultClick = async (filePath: string) => {
    if (!filePath) return;
    await openFile(filePath);
  };

  return (
    <div
      data-testid="semantic-search-panel"
      className="flex flex-col h-full w-full bg-[#0d0f17] text-slate-200 overflow-hidden select-none"
    >
      {/* ── Top Header ──────────────────────────────────────────────────────── */}
      <div className="flex items-center justify-between px-3.5 py-3 border-b border-white/10 bg-[#141724]/70 shrink-0">
        <div className="flex items-center gap-2">
          <Database size={16} className="text-primary" />
          <span className="font-semibold text-xs text-white tracking-wide uppercase">
            Knowledge Base
          </span>
        </div>
        <button
          onClick={handleIndex}
          disabled={isIndexing || !wsPath}
          data-testid="rag-index-btn"
          className="px-2.5 py-1 rounded bg-white/5 hover:bg-white/10 border border-white/10 text-[11px] font-medium text-slate-300 flex items-center gap-1.5 transition-colors cursor-pointer disabled:opacity-40"
          title="Index or re-index entire workspace into vector database"
        >
          <RefreshCw size={11} className={isIndexing ? "animate-spin text-primary" : ""} />
          <span>{isIndexing ? "Indexing..." : "Index Workspace"}</span>
        </button>
      </div>

      {/* ── Index Status Badge Bar ─────────────────────────────────────────── */}
      <div className="px-3.5 py-2 bg-black/20 border-b border-white/5 flex items-center justify-between text-[11px] text-slate-400 shrink-0">
        <div data-testid="rag-status-badge" className="flex items-center gap-1.5">
          <Layers size={13} className="text-cyan-400 shrink-0" />
          <span className="font-mono text-slate-300">
            {indexStatus.indexed_files} files indexed, {indexStatus.total_chunks} chunks
          </span>
        </div>
        {indexStatus.last_indexed_at && (
          <span className="text-[10px] text-slate-500 font-mono">
            {new Date(indexStatus.last_indexed_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
          </span>
        )}
      </div>

      {/* ── Search Input Box ────────────────────────────────────────────────── */}
      <form onSubmit={handleSearch} className="p-3 border-b border-white/10 flex flex-col gap-2 shrink-0">
        <div className="relative">
          <textarea
            data-testid="rag-search-input"
            rows={2}
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                handleSearch();
              }
            }}
            placeholder="Ask about your codebase (e.g., Where is authentication verified?)..."
            className="w-full rounded-xl border border-white/10 bg-[#07090e] px-3 py-2 text-xs text-slate-200 placeholder-slate-500 outline-none focus:border-primary/50 focus:ring-1 focus:ring-primary/50 transition-all resize-none"
          />
        </div>
        <button
          type="submit"
          data-testid="rag-search-btn"
          disabled={isSearching || !searchQuery.trim() || !wsPath}
          className="w-full py-1.5 rounded-lg bg-primary/20 hover:bg-primary/30 border border-primary/40 text-primary text-xs font-semibold flex items-center justify-center gap-1.5 transition-colors cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {isSearching ? (
            <RefreshCw size={12} className="animate-spin text-primary" />
          ) : (
            <Search size={12} />
          )}
          <span>{isSearching ? "Searching..." : "Semantic Search"}</span>
        </button>
      </form>

      {/* ── Error Banner ────────────────────────────────────────────────────── */}
      {error && (
        <div className="px-3.5 py-2 bg-rose-500/10 border-b border-rose-500/20 text-rose-300 text-xs flex items-center gap-2 shrink-0">
          <AlertCircle size={14} className="shrink-0 text-rose-400" />
          <span className="truncate">{error}</span>
        </div>
      )}

      {/* ── Search Results List ─────────────────────────────────────────────── */}
      <div className="flex-1 overflow-y-auto divide-y divide-white/5 p-2 space-y-2">
        {searchResults.length === 0 ? (
          <div className="flex flex-col items-center justify-center p-8 text-center text-slate-500 space-y-2">
            {indexStatus.indexed_files === 0 ? (
              <>
                <Database size={24} className="text-slate-600 mb-1" />
                <span className="text-xs text-slate-400 font-medium">Knowledge Base not indexed</span>
                <span className="text-[11px] text-slate-500 max-w-[180px] leading-relaxed">
                  Click <span className="text-primary font-semibold">Index Workspace</span> above to scan your files and enable semantic search.
                </span>
                <button
                  onClick={handleIndex}
                  disabled={isIndexing || !wsPath}
                  className="mt-2 px-3 py-1.5 text-xs rounded-lg bg-primary/20 hover:bg-primary/30 border border-primary/40 text-primary font-semibold transition-colors disabled:opacity-40 cursor-pointer"
                >
                  {isIndexing ? "Indexing..." : "Index Workspace Now"}
                </button>
              </>
            ) : (
              <>
                <Sparkles size={24} className="text-slate-600 mb-1" />
                <span className="text-xs">
                  {searchQuery.trim()
                    ? "No matching code chunks found for this query."
                    : "Ask questions to search codebase semantics using local vector embeddings."}
                </span>
              </>
            )}
          </div>
        ) : (
          searchResults.map((result: RAGChunkResult, idx: number) => {
            const isExpanded = expandedChunk === idx;
            const previewText = result.chunk_text.slice(0, 200);
            const hasMore = result.chunk_text.length > 200;
            const scorePct = Math.round(result.score * 100);

            return (
              <div
                key={`${result.file_path}-${idx}`}
                data-testid="rag-result-item"
                className="rounded-xl border border-white/5 bg-white/[0.02] hover:bg-white/[0.04] p-2.5 transition-colors flex flex-col gap-1.5 cursor-pointer group"
                onClick={() => void handleResultClick(result.file_path)}
              >
                {/* Result Item Header */}
                <div className="flex items-center justify-between text-xs gap-2">
                  <div className="flex items-center gap-1.5 min-w-0 flex-1">
                    <FileCode size={13} className="text-primary shrink-0" />
                    <span
                      data-testid="rag-file-path"
                      className="font-mono text-slate-300 truncate font-medium group-hover:text-primary transition-colors"
                      title={result.file_path}
                    >
                      {result.file_path}
                    </span>
                  </div>

                  <div className="flex items-center gap-1.5 shrink-0 font-mono text-[10px]">
                    <span
                      data-testid="rag-line-range"
                      className="px-1.5 py-0.2 rounded bg-white/5 border border-white/10 text-slate-400"
                    >
                      L{result.line_range}
                    </span>
                    <span
                      data-testid="rag-score-badge"
                      className={`px-1.5 py-0.2 rounded font-semibold border ${
                        scorePct >= 80
                          ? "bg-emerald-500/15 text-emerald-400 border-emerald-500/30"
                          : scorePct >= 60
                          ? "bg-cyan-500/15 text-cyan-400 border-cyan-500/30"
                          : "bg-amber-500/15 text-amber-400 border-amber-500/30"
                      }`}
                      title={`Similarity score: ${result.score}`}
                    >
                      {scorePct}%
                    </span>
                  </div>
                </div>

                {/* Chunk text snippet */}
                <div className="relative">
                  <pre className="text-[11px] font-mono text-slate-400 bg-black/40 rounded p-2 overflow-x-auto whitespace-pre-wrap leading-relaxed border border-white/5">
                    {isExpanded ? result.chunk_text : previewText}
                    {!isExpanded && hasMore && "..."}
                  </pre>
                  {hasMore && (
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        setExpandedChunk(isExpanded ? null : idx);
                      }}
                      className="text-[10px] text-primary/80 hover:text-primary flex items-center gap-0.5 mt-1 cursor-pointer"
                    >
                      <span>{isExpanded ? "Collapse" : "Expand chunk"}</span>
                      {isExpanded ? <ChevronUp size={10} /> : <ChevronDown size={10} />}
                    </button>
                  )}
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
