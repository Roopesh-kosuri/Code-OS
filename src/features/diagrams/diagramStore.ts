import { create } from "zustand";
import { api } from "../../lib/api";
import { useWorkspaceStore } from "../../stores/workspaceStore";

export type DiagramType = "component" | "data_flow" | "api" | "er";

export interface ComponentItem {
  id: string;
  name: string;
  path: string;
  type: string;
  language: string;
  classes?: string[];
  functions?: string[];
  imports?: string[];
  external_calls?: string[];
}

export interface RelationshipItem {
  source: string;
  source_type?: string;
  target: string;
  target_type?: string;
  type: string;
  label?: string;
}

export interface ApiItem {
  method: string;
  path: string;
  handler: string;
  file: string;
  resource: string;
}

export interface AnalysisStats {
  components: number;
  relationships: number;
  apis: number;
  models: number;
}

export interface AnalysisResults {
  components: ComponentItem[];
  relationships: RelationshipItem[];
  apis: ApiItem[];
  models?: any[];
  stats: AnalysisStats;
}

export interface DiagramRecord {
  diagram_id?: string;
  type: DiagramType;
  code: string;
  preview_svg?: string;
  rendered_png?: string;
}

interface DiagramState {
  analysisResults: AnalysisResults | null;
  diagrams: Record<DiagramType, DiagramRecord | null>;
  activeType: DiagramType;
  activeDiagramId: string | null;
  isAnalyzing: boolean;
  isRendering: boolean;
  error: string | null;

  // Actions
  analyzeCodebase: (workspacePath?: string) => Promise<AnalysisResults | null>;
  generateDiagram: (type?: DiagramType, workspacePath?: string) => Promise<DiagramRecord | null>;
  exportDiagram: (format: "png" | "svg" | "mermaid") => Promise<void>;
  setActiveType: (type: DiagramType) => void;
  reset: () => void;
}

const defaultStats: AnalysisStats = {
  components: 0,
  relationships: 0,
  apis: 0,
  models: 0,
};

export const useDiagramStore = create<DiagramState>((set, get) => ({
  analysisResults: null,
  diagrams: {
    component: null,
    data_flow: null,
    api: null,
    er: null,
  },
  activeType: "component",
  activeDiagramId: null,
  isAnalyzing: false,
  isRendering: false,
  error: null,

  setActiveType: (type: DiagramType) => {
    set({ activeType: type });
    const current = get().diagrams[type];
    if (!current && get().analysisResults) {
      void get().generateDiagram(type);
    }
  },

  reset: () =>
    set({
      analysisResults: null,
      diagrams: { component: null, data_flow: null, api: null, er: null },
      activeType: "component",
      activeDiagramId: null,
      isAnalyzing: false,
      isRendering: false,
      error: null,
    }),

  analyzeCodebase: async (workspacePath?: string) => {
    const ws =
      workspacePath || useWorkspaceStore.getState().currentWorkspace?.path || "";
    set({ isAnalyzing: true, error: null });

    try {
      const data = await api.post<AnalysisResults>("/api/diagrams/analyze", {
        workspace: ws,
      });

      set({
        analysisResults: {
          components: data.components || [],
          relationships: data.relationships || [],
          apis: data.apis || [],
          models: data.models || [],
          stats: data.stats || defaultStats,
        },
        isAnalyzing: false,
      });

      // Auto-generate the currently active diagram
      await get().generateDiagram(get().activeType, ws);
      return data;
    } catch (err: any) {
      const msg = err?.message || "Failed to analyze codebase";
      set({ isAnalyzing: false, error: msg });
      return null;
    }
  },

  generateDiagram: async (type?: DiagramType, workspacePath?: string) => {
    const targetType = type || get().activeType;
    const ws =
      workspacePath || useWorkspaceStore.getState().currentWorkspace?.path || "";
    set({ isRendering: true, error: null });

    try {
      const res = await api.post<{
        diagram_id: string;
        type: DiagramType;
        diagram_code: string;
        preview_svg: string;
        diagrams?: Record<string, { code: string; svg: string }>;
        stats?: AnalysisStats;
      }>("/api/diagrams/generate", {
        workspace: ws,
        type: targetType,
      });

      const updatedRecord: DiagramRecord = {
        diagram_id: res.diagram_id,
        type: targetType,
        code: res.diagram_code,
        preview_svg: res.preview_svg,
      };

      set((state) => {
        const nextDiagrams = { ...state.diagrams, [targetType]: updatedRecord };
        if (res.diagrams) {
          for (const [key, val] of Object.entries(res.diagrams)) {
            if (key in nextDiagrams && val) {
              nextDiagrams[key as DiagramType] = {
                diagram_id: res.diagram_id,
                type: key as DiagramType,
                code: val.code,
                preview_svg: val.svg,
              };
            }
          }
        }
        return {
          diagrams: nextDiagrams,
          activeDiagramId: res.diagram_id,
          isRendering: false,
        };
      });

      return updatedRecord;
    } catch (err: any) {
      const msg = err?.message || "Failed to generate diagram";
      set({ isRendering: false, error: msg });
      return null;
    }
  },

  exportDiagram: async (format: "png" | "svg" | "mermaid") => {
    const { activeType, diagrams, activeDiagramId } = get();
    const current = diagrams[activeType];
    const diagId = activeDiagramId || current?.diagram_id || "diagram";

    try {
      let downloadUrl = "";
      let filename = `architecture-${activeType}-${Date.now()}`;

      if (format === "mermaid") {
        filename += ".mmd";
        const code = current?.code || "";
        const blob = new Blob([code], { type: "text/plain;charset=utf-8" });
        downloadUrl = URL.createObjectURL(blob);
      } else if (format === "svg") {
        filename += ".svg";
        const svgContent = current?.preview_svg || "";
        const blob = new Blob([svgContent], { type: "image/svg+xml;charset=utf-8" });
        downloadUrl = URL.createObjectURL(blob);
      } else {
        // PNG export
        filename += ".png";
        try {
          const blob = await api.blob(
            `/api/diagrams/export/${diagId}?format=png`
          );
          downloadUrl = URL.createObjectURL(blob);
        } catch {
          // Fallback in case backend blob export isn't directly reachable
          if (current?.preview_svg) {
            const blob = new Blob([current.preview_svg], {
              type: "image/svg+xml;charset=utf-8",
            });
            downloadUrl = URL.createObjectURL(blob);
          }
        }
      }

      if (typeof document !== "undefined" && downloadUrl) {
        const link = document.createElement("a");
        link.href = downloadUrl;
        link.download = filename;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        setTimeout(() => URL.revokeObjectURL(downloadUrl), 1000);
      }
    } catch (err: any) {
      console.error("[diagram.export] failed", err);
      set({ error: `Export failed: ${err.message}` });
    }
  },
}));
