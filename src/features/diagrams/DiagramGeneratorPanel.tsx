import React, { useEffect, useRef, useState } from "react";
import {
  Network,
  Layers,
  GitBranch,
  Database,
  Download,
  Copy,
  Check,
  Code,
  Sparkles,
  RefreshCw,
  FileCode,
  Maximize2,
  ZoomIn,
  ZoomOut,
  RotateCcw,
  ArrowRight,
} from "lucide-react";
import {
  useDiagramStore,
  DiagramType,
} from "./diagramStore";
import { useEditorStore } from "../../stores/editorStore";
import { useWorkspaceStore } from "../../stores/workspaceStore";

export const DiagramGeneratorPanel: React.FC = () => {
  const {
    analysisResults,
    diagrams,
    activeType,
    isAnalyzing,
    isRendering,
    error,
    analyzeCodebase,
    generateDiagram,
    exportDiagram,
    setActiveType,
  } = useDiagramStore();

  const currentWorkspace = useWorkspaceStore((s) => s.currentWorkspace);

  const [copied, setCopied] = useState(false);
  const [zoom, setZoom] = useState(1);
  const [renderedSvg, setRenderedSvg] = useState<string>("");
  const previewRef = useRef<HTMLDivElement>(null);

  const currentDiagram = diagrams[activeType];
  const stats = analysisResults?.stats || {
    components: 0,
    relationships: 0,
    apis: 0,
    models: 0,
  };

  const diagramTypes: {
    id: DiagramType;
    label: string;
    description: string;
    icon: React.ComponentType<{ className?: string }>;
  }[] = [
    {
      id: "component",
      label: "Component Diagram",
      description: "Boxes & dependency arrows",
      icon: Layers,
    },
    {
      id: "data_flow",
      label: "Data Flow Diagram",
      description: "Request → Service → DB flow",
      icon: GitBranch,
    },
    {
      id: "api",
      label: "API Sequence",
      description: "Client → Router → Database",
      icon: Network,
    },
    {
      id: "er",
      label: "Entity Relationship",
      description: "Database models & schemas",
      icon: Database,
    },
  ];

  // Try rendering with client-side Mermaid if available, otherwise fallback to server SVG
  useEffect(() => {
    let isCancelled = false;

    const render = async () => {
      if (!currentDiagram?.code) {
        setRenderedSvg(currentDiagram?.preview_svg || "");
        return;
      }

      try {
        const mermaidModule = await import("mermaid");
        const mermaid = mermaidModule.default || mermaidModule;
        mermaid.initialize({
          startOnLoad: false,
          theme: "dark",
          securityLevel: "loose",
          themeVariables: {
            darkMode: true,
            background: "#090d16",
            primaryColor: "#0f172a",
            primaryBorderColor: "#38bdf8",
            primaryTextColor: "#f8fafc",
            lineColor: "#64748b",
            textColor: "#f8fafc",
          },
        });

        const uniqueId = `mermaid-render-${Date.now()}`;
        const { svg } = await mermaid.render(uniqueId, currentDiagram.code);
        if (!isCancelled) {
          setRenderedSvg(svg);
        }
      } catch (err) {
        // Fallback to server generated dark SVG
        if (!isCancelled) {
          setRenderedSvg(currentDiagram.preview_svg || "");
        }
      }
    };

    void render();

    return () => {
      isCancelled = true;
    };
  }, [currentDiagram?.code, currentDiagram?.preview_svg]);

  const handleCopyCode = async () => {
    if (!currentDiagram?.code) return;
    try {
      await navigator.clipboard.writeText(currentDiagram.code);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Fallback
    }
  };

  const handleOpenInEditor = () => {
    if (!currentDiagram?.code) return;
    const fileName = `architecture-${activeType}.mmd`;
    const openFiles = useEditorStore.getState().openFiles;
    const existing = openFiles.find((f) => f.path === fileName);

    if (!existing) {
      useEditorStore.setState((state) => ({
        openFiles: [
          ...state.openFiles,
          {
            path: fileName,
            name: fileName,
            content: currentDiagram.code,
            language: "markdown",
            dirty: true,
          },
        ],
        activePath: fileName,
      }));
    } else {
      useEditorStore.getState().updateContent(fileName, currentDiagram.code);
      useEditorStore.setState({ activePath: fileName });
    }
  };

  return (
    <div className="flex flex-col h-full bg-slate-950/90 text-slate-100 backdrop-blur-xl border-r border-white/5 overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between p-4 border-b border-white/10 bg-slate-900/40">
        <div className="flex items-center gap-2.5">
          <div className="p-1.5 rounded-lg bg-cyan-500/10 border border-cyan-500/20 text-cyan-400">
            <Network className="w-5 h-5" />
          </div>
          <div>
            <h2 className="text-sm font-semibold tracking-wide text-white">
              Architecture Diagrams
            </h2>
            <p className="text-xs text-slate-400">
              Codebase to Mermaid Generator
            </p>
          </div>
        </div>

        <button
          onClick={() => void analyzeCodebase(currentWorkspace?.path)}
          disabled={isAnalyzing}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md bg-cyan-600/20 hover:bg-cyan-600/30 text-cyan-300 border border-cyan-500/30 transition-all disabled:opacity-50 disabled:cursor-not-allowed shadow-sm"
          title="Run AST scan on workspace files"
        >
          {isAnalyzing ? (
            <RefreshCw className="w-3.5 h-3.5 animate-spin" />
          ) : (
            <Sparkles className="w-3.5 h-3.5 text-cyan-400" />
          )}
          <span>{isAnalyzing ? "Analyzing..." : "Analyze Codebase"}</span>
        </button>
      </div>

      {/* Analysis Summary Bar */}
      <div className="px-4 py-2.5 bg-slate-900/60 border-b border-white/5 text-xs flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2 text-slate-300">
          <span className="inline-block w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
          <span data-testid="analysis-summary">
            {analysisResults
              ? `Found ${stats.components} components, ${stats.relationships} relationships, ${stats.apis} API endpoints`
              : "Ready to analyze workspace components & dependencies"}
          </span>
        </div>
        {analysisResults && (
          <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-cyan-950/80 text-cyan-400 border border-cyan-800/40">
            {stats.models} Models
          </span>
        )}
      </div>

      {error && (
        <div className="p-3 m-3 text-xs rounded-lg bg-red-950/60 border border-red-800/40 text-red-200">
          {error}
        </div>
      )}

      {/* Diagram Type Selector */}
      <div className="p-3 border-b border-white/10 bg-slate-900/20">
        <label className="text-[11px] font-medium text-slate-400 uppercase tracking-wider block mb-2">
          Select Diagram Type
        </label>
        <div className="grid grid-cols-2 gap-2">
          {diagramTypes.map((tab) => {
            const Icon = tab.icon;
            const isActive = activeType === tab.id;
            return (
              <button
                key={tab.id}
                onClick={() => setActiveType(tab.id)}
                className={`flex flex-col items-start p-2.5 rounded-lg border text-left transition-all ${
                  isActive
                    ? "bg-cyan-500/10 border-cyan-500/50 text-white shadow-sm shadow-cyan-500/10"
                    : "bg-slate-900/40 border-white/5 text-slate-400 hover:text-slate-200 hover:bg-slate-800/40"
                }`}
              >
                <div className="flex items-center gap-2 mb-1">
                  <Icon
                    className={`w-4 h-4 ${
                      isActive ? "text-cyan-400" : "text-slate-400"
                    }`}
                  />
                  <span className="text-xs font-semibold">{tab.label}</span>
                </div>
                <span className="text-[10px] text-slate-500 line-clamp-1">
                  {tab.description}
                </span>
              </button>
            );
          })}
        </div>
      </div>

      {/* Generate & Actions Toolbar */}
      <div className="px-4 py-2 flex items-center justify-between border-b border-white/10 bg-slate-900/30">
        <button
          onClick={() => void generateDiagram(activeType)}
          disabled={isRendering}
          className="flex items-center gap-1.5 px-3 py-1 text-xs font-medium rounded bg-indigo-600/30 hover:bg-indigo-600/40 text-indigo-200 border border-indigo-500/40 transition-all disabled:opacity-50"
        >
          {isRendering ? (
            <RefreshCw className="w-3.5 h-3.5 animate-spin" />
          ) : (
            <Sparkles className="w-3.5 h-3.5 text-indigo-400" />
          )}
          <span>{isRendering ? "Generating..." : "Generate Diagram"}</span>
        </button>

        {/* Export & Editor Actions */}
        <div className="flex items-center gap-1">
          <button
            onClick={() => void exportDiagram("png")}
            disabled={!currentDiagram}
            className="flex items-center gap-1 px-2 py-1 text-xs rounded bg-slate-800 hover:bg-slate-700 text-slate-300 border border-white/5 transition-all disabled:opacity-40"
            title="Download PNG image"
          >
            <Download className="w-3.5 h-3.5" />
            <span>PNG</span>
          </button>

          <button
            onClick={() => void exportDiagram("svg")}
            disabled={!currentDiagram}
            className="flex items-center gap-1 px-2 py-1 text-xs rounded bg-slate-800 hover:bg-slate-700 text-slate-300 border border-white/5 transition-all disabled:opacity-40"
            title="Download SVG vector"
          >
            <Download className="w-3.5 h-3.5" />
            <span>SVG</span>
          </button>

          <button
            onClick={handleCopyCode}
            disabled={!currentDiagram}
            className="flex items-center gap-1 px-2 py-1 text-xs rounded bg-slate-800 hover:bg-slate-700 text-slate-300 border border-white/5 transition-all disabled:opacity-40"
            title="Copy Mermaid syntax"
          >
            {copied ? (
              <Check className="w-3.5 h-3.5 text-emerald-400" />
            ) : (
              <Copy className="w-3.5 h-3.5" />
            )}
            <span>{copied ? "Copied" : "Copy"}</span>
          </button>

          <button
            onClick={handleOpenInEditor}
            disabled={!currentDiagram}
            className="flex items-center gap-1 px-2.5 py-1 text-xs rounded bg-cyan-950/60 hover:bg-cyan-900/60 text-cyan-300 border border-cyan-800/40 transition-all disabled:opacity-40"
            title="Open in Monaco editor"
          >
            <FileCode className="w-3.5 h-3.5" />
            <span>Open in Editor</span>
          </button>
        </div>
      </div>

      {/* Interactive Diagram Preview Pane */}
      <div className="flex-1 flex flex-col relative bg-slate-950 p-3 overflow-hidden">
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-1.5 text-xs text-slate-400">
            <Code className="w-3.5 h-3.5 text-slate-500" />
            <span>Preview & Architecture Canvas</span>
          </div>

          <div className="flex items-center gap-1 bg-slate-900/80 px-1.5 py-0.5 rounded border border-white/5 text-xs text-slate-400">
            <button
              onClick={() => setZoom((z) => Math.max(0.4, z - 0.1))}
              className="p-1 hover:text-white"
              title="Zoom out"
            >
              <ZoomOut className="w-3 h-3" />
            </button>
            <span className="text-[10px] font-mono px-1">
              {Math.round(zoom * 100)}%
            </span>
            <button
              onClick={() => setZoom((z) => Math.min(2.5, z + 0.1))}
              className="p-1 hover:text-white"
              title="Zoom in"
            >
              <ZoomIn className="w-3 h-3" />
            </button>
            <button
              onClick={() => setZoom(1)}
              className="p-1 hover:text-white"
              title="Reset zoom"
            >
              <RotateCcw className="w-3 h-3" />
            </button>
          </div>
        </div>

        <div
          ref={previewRef}
          data-testid="diagram-preview-pane"
          className="flex-1 w-full h-full rounded-xl border border-white/10 bg-slate-900/40 backdrop-blur-md flex items-center justify-center overflow-auto p-4 relative shadow-inner"
        >
          {isRendering ? (
            <div className="flex flex-col items-center gap-2 text-slate-400 animate-pulse">
              <RefreshCw className="w-6 h-6 animate-spin text-cyan-400" />
              <span className="text-xs">Rendering Mermaid diagram...</span>
            </div>
          ) : renderedSvg ? (
            <div
              className="w-full h-full flex items-center justify-center transition-transform duration-150"
              style={{ transform: `scale(${zoom})`, transformOrigin: "center center" }}
              dangerouslySetInnerHTML={{ __html: renderedSvg }}
            />
          ) : (
            <div className="flex flex-col items-center gap-3 text-slate-500 max-w-xs text-center p-6">
              <div className="p-3 rounded-full bg-slate-900 border border-white/5 text-slate-400">
                <Network className="w-8 h-8 opacity-60" />
              </div>
              <p className="text-xs">
                Click <span className="text-cyan-400 font-medium">"Analyze Codebase"</span> to scan files, then generate high-resolution architecture diagrams.
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
