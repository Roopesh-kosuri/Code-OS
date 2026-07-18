import { useEffect, useState } from "react";
import { Landmark, Compass, GitMerge, FileText } from "lucide-react";
import { api } from "../../lib/api";
import { useWorkspaceStore } from "../../stores/workspaceStore";

type RepoSummary = {
  project_type: string;
  total_files: number;
  languages: Record<string, number>;
  frameworks: string[];
  entry_points: string[];
  architecture_summary: string;
  key_symbols: Array<{ path: string; name: string; kind: string; language: string }>;
};

type RepoGraph = {
  nodes: Array<{ id: string }>;
  edges: Array<{ source: string; target: string; module: string }>;
};

export function RepoUnderstanding() {
  const [summary, setSummary] = useState<RepoSummary | null>(null);
  const [graph, setGraph] = useState<RepoGraph | null>(null);
  const [activeTab, setActiveTab] = useState<"architecture" | "dependencies">("architecture");
  const workspace = useWorkspaceStore((state) => state.currentWorkspace);

  const fetchRepoData = async () => {
    if (!workspace) return;
    try {
      const summaryData = await api.get<RepoSummary>("/api/index/repo/summary", { workspace: workspace.path });
      setSummary(summaryData);
      
      const graphData = await api.get<RepoGraph>("/api/index/repo/graph", { workspace: workspace.path });
      setGraph(graphData);
    } catch {
      setSummary(null);
      setGraph(null);
    }
  };

  useEffect(() => {
    void fetchRepoData();
    const interval = setInterval(() => void fetchRepoData(), 5000);
    return () => clearInterval(interval);
  }, [workspace?.path]);

  if (!workspace) {
    return <div className="p-3 text-sm text-slate-500">Open a workspace to view repository understanding.</div>;
  }

  return (
    <section className="grid h-full min-h-0 w-full min-w-0 grid-cols-1 grid-rows-[38px_30px_1fr] border-b border-surface-700">
      <div className="flex items-center gap-2 border-b border-surface-700 px-3 py-1">
        <Landmark size={15} className="text-slate-400" />
        <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">Repository Intelligence</span>
      </div>
      
      {/* Tab Switcher */}
      <div className="flex border-b border-surface-800 text-[10px] uppercase font-semibold">
        <button
          onClick={() => setActiveTab("architecture")}
          className={`flex-1 text-center py-1 border-r border-surface-800 ${activeTab === "architecture" ? "bg-surface-800 text-white" : "text-slate-400 hover:text-slate-200"}`}
        >
          <span className="flex items-center justify-center gap-1"><Compass size={11} /> Overview</span>
        </button>
        <button
          onClick={() => setActiveTab("dependencies")}
          className={`flex-1 text-center py-1 ${activeTab === "dependencies" ? "bg-surface-800 text-white" : "text-slate-400 hover:text-slate-200"}`}
        >
          <span className="flex items-center justify-center gap-1"><GitMerge size={11} /> Imports Graph</span>
        </button>
      </div>

      <div className="overflow-auto p-3 text-xs space-y-3 min-h-0">
        {summary ? (
          activeTab === "architecture" ? (
            <div className="space-y-3">
              {/* Stats Block */}
              <div className="grid grid-cols-2 gap-2 bg-surface-850 p-2 rounded">
                <div>
                  <span className="text-slate-500 block text-[9px] uppercase">Project Type</span>
                  <span className="font-semibold text-slate-200 truncate block">{summary.project_type.toUpperCase()}</span>
                </div>
                <div>
                  <span className="text-slate-500 block text-[9px] uppercase">Total Files</span>
                  <span className="font-semibold text-slate-200 block">{summary.total_files}</span>
                </div>
              </div>

              {/* Architecture Summary Text */}
              <div className="bg-surface-900/50 border border-surface-800 p-2 rounded text-slate-300 whitespace-pre-wrap leading-relaxed">
                {summary.architecture_summary}
              </div>

              {/* Language counts */}
              {Object.keys(summary.languages).length > 0 && (
                <div>
                  <div className="text-[10px] text-slate-500 uppercase font-semibold mb-1">Language Distribution</div>
                  <div className="space-y-1">
                    {Object.entries(summary.languages).map(([lang, count]) => (
                      <div key={lang} className="flex items-center justify-between text-slate-400">
                        <span className="capitalize">{lang}</span>
                        <span>{count} files</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Key Symbols */}
              {summary.key_symbols.length > 0 && (
                <div>
                  <div className="text-[10px] text-slate-500 uppercase font-semibold mb-1">Key Declarations</div>
                  <div className="max-h-28 overflow-auto border border-surface-800 rounded bg-surface-900/30 p-1 space-y-0.5">
                    {summary.key_symbols.slice(0, 15).map((sym, idx) => (
                      <div key={idx} className="flex justify-between items-center text-[10px] py-0.5 px-1 hover:bg-surface-800 rounded text-slate-300">
                        <span className="font-mono text-accent-400 truncate max-w-[120px]">{sym.name}</span>
                        <span className="text-[9px] text-slate-500 font-mono uppercase bg-surface-800 px-1 rounded">{sym.kind}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          ) : (
            // Import Dependency Graph list representation
            <div className="space-y-2">
              <div className="text-[10px] text-slate-500 uppercase font-semibold">Import Connections</div>
              {graph && graph.edges.length > 0 ? (
                <div className="space-y-1.5 max-h-60 overflow-auto pr-1">
                  {graph.edges.map((edge, idx) => (
                    <div key={idx} className="bg-surface-850 p-2 rounded border border-surface-800 font-mono text-[10px]">
                      <div className="flex items-center justify-between">
                        <span className="text-rose-400 truncate max-w-[100px]" title={edge.source}>{edge.source}</span>
                        <span className="text-slate-600 px-1">import➔</span>
                        <span className="text-emerald-400 truncate max-w-[100px]" title={edge.target}>{edge.target}</span>
                      </div>
                      <div className="text-[9px] text-slate-500 mt-1 truncate">Module: {edge.module}</div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="text-slate-500 italic text-center py-4">No import linkages detected in workspace.</div>
              )}
            </div>
          )
        ) : (
          <div className="text-slate-500 text-center py-6">
            <Compass className="mx-auto mb-2 animate-spin text-slate-600" size={20} />
            Loading repository intelligence data...
          </div>
        )}
      </div>
    </section>
  );
}
