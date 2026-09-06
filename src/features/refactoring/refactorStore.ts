import { create } from "zustand";
import { api } from "../../lib/api";
import { useWorkspaceStore } from "../../stores/workspaceStore";

export type SmellSeverity = "Critical" | "Warning" | "Info";

export interface CodeSmellLocation {
  file: string;
  line: number;
  end_line?: number;
}

export interface CodeSmell {
  id?: string;
  type: string;
  location: CodeSmellLocation;
  severity: SmellSeverity;
  description?: string;
  message?: string;
  suggestion?: string;
  details?: string;
  ruleId?: string;
  filePath?: string;
  line?: number;
  endLine?: number;
  symbolName?: string;
}

export interface DuplicateLocation {
  file: string;
  lines: [number, number];
}

export interface DuplicateCode {
  code_snippet?: string;
  locations?: DuplicateLocation[];
  occurrences?: DuplicateLocation[];
  line_count?: number;
  similarity?: number;
  instances?: any[];
  lines?: any;
  snippet?: string;
}

export interface FunctionComplexity {
  name: string;
  line: number;
  cyclomatic: number;
  cognitive: number;
}

export interface ComplexityReport {
  file: string;
  functions: FunctionComplexity[];
  max_cyclomatic: number;
  max_cognitive: number;
}

export interface AnalyzeResult {
  code_smells: CodeSmell[];
  duplicates: DuplicateCode[];
  complexity: ComplexityReport[];
  total_smells: number;
}

export interface RefactorChange {
  file?: string;
  filePath?: string;
  original_content?: string;
  updated_content?: string;
  diff?: string;
  modifiedCode?: string;
  type?: string;
}

export interface RefactorImpact {
  complexity_before?: number;
  complexity_after?: number;
  lines_delta?: number;
  linesDelta?: number;
  complexityDelta?: number;
  estimated_risk?: "low" | "medium" | "high";
}

export interface RefactorPreview {
  refactor_type?: string;
  type?: string;
  changes?: RefactorChange[];
  explanation?: string;
  impact?: RefactorImpact;
  filePath?: string;
  diff?: string;
  modifiedCode?: string;
}

export interface TestResultDetails {
  passed: boolean;
  total_tests?: number;
  passed_tests?: number;
  failed_tests?: string[];
  output?: string;
  exit_code?: number;
}

export interface VerificationResult {
  safe?: boolean;
  test_results?: TestResultDetails;
  error?: string;
  passed?: boolean;
  message?: string;
  details?: any;
}

export interface RefactorRequest {
  refactor_type?: string;
  type?: string;
  file_path?: string;
  filePath?: string;
  selection_range?: [number, number];
  params?: Record<string, any>;
  workspace?: string;
  ruleId?: string;
  description?: string;
  symbolName?: string;
  startLine?: number;
  endLine?: number;
  [key: string]: any;
}

interface RefactorState {
  codeSmells: CodeSmell[];
  duplicates: DuplicateCode[];
  complexityReports: ComplexityReport[];
  complexityMetrics?: any;
  refactorPreview: RefactorPreview | null;
  verificationStatus: VerificationResult | null;
  selectedSmell: CodeSmell | null;
  activeSmell?: any;
  ghostTextEnabled?: boolean;
  smartStagingEnabled?: boolean;
  isAnalyzing: boolean;
  isVerifying: boolean;
  isApplying: boolean;
  isQuickFixOpen: boolean;
  activeSeverityFilter: "All" | SmellSeverity;
  error: string | null;

  // Actions
  analyzeCodebase: (workspacePath?: string) => Promise<AnalyzeResult | null>;
  previewRefactor: (request: RefactorRequest) => Promise<RefactorPreview | null>;
  verifyRefactor: (changes: RefactorChange[] | any, workspacePath?: string) => Promise<VerificationResult | null>;
  applyRefactor: (changes: RefactorChange[] | any, verified?: boolean, workspacePath?: string) => Promise<{ success: boolean; modified_files: string[] } | null>;
  openQuickFix: (smell: CodeSmell) => void;
  closeQuickFix: () => void;
  selectSmell: (smell: CodeSmell | null) => void;
  setActiveSmell: (smell: any) => void;
  setQuickFixOpen: (open: boolean) => void;
  toggleGhostText: () => void;
  toggleSmartStaging: () => void;
  setSeverityFilter: (filter: "All" | SmellSeverity) => void;
  clearPreview: () => void;
  reset: () => void;
}

export const useRefactorStore = create<RefactorState>((set, get) => ({
  codeSmells: [],
  duplicates: [],
  complexityReports: [],
  complexityMetrics: {},
  refactorPreview: null,
  verificationStatus: null,
  selectedSmell: null,
  activeSmell: null,
  ghostTextEnabled: true,
  smartStagingEnabled: true,
  isAnalyzing: false,
  isVerifying: false,
  isApplying: false,
  isQuickFixOpen: false,
  activeSeverityFilter: "All",
  error: null,

  setActiveSmell: (smell: any) => set({ activeSmell: smell, selectedSmell: smell }),
  setQuickFixOpen: (open: boolean) => set({ isQuickFixOpen: open }),
  toggleGhostText: () => set((s) => ({ ghostTextEnabled: !s.ghostTextEnabled })),
  toggleSmartStaging: () => set((s) => ({ smartStagingEnabled: !s.smartStagingEnabled })),

  analyzeCodebase: async (workspacePath?: string) => {
    const ws = workspacePath || useWorkspaceStore.getState().currentWorkspace?.path || "";
    set({ isAnalyzing: true, error: null });

    try {
      const response = await api.post<AnalyzeResult>("/api/refactor/analyze", {
        workspace: ws,
      });

      set({
        codeSmells: response.code_smells || [],
        duplicates: response.duplicates || [],
        complexityReports: response.complexity || [],
        isAnalyzing: false,
      });

      return response;
    } catch (err: any) {
      set({
        error: err?.message || "Failed to analyze codebase for code quality",
        isAnalyzing: false,
      });
      return null;
    }
  },

  previewRefactor: async (request: RefactorRequest) => {
    const ws = request.workspace || useWorkspaceStore.getState().currentWorkspace?.path || "";
    set({ error: null });

    try {
      const response = await api.post<RefactorPreview>("/api/refactor/preview", {
        ...request,
        workspace: ws,
      });

      set({
        refactorPreview: response,
        verificationStatus: null,
      });

      return response;
    } catch (err: any) {
      set({
        error: err?.message || "Failed to generate refactor preview",
      });
      return null;
    }
  },

  verifyRefactor: async (changes: RefactorChange[], workspacePath?: string) => {
    const ws = workspacePath || useWorkspaceStore.getState().currentWorkspace?.path || "";
    set({ isVerifying: true, error: null });

    try {
      const response = await api.post<VerificationResult>("/api/refactor/verify", {
        changes,
        workspace: ws,
      });

      set({
        verificationStatus: response,
        isVerifying: false,
      });

      return response;
    } catch (err: any) {
      set({
        verificationStatus: {
          safe: false,
          test_results: { passed: false, failed_tests: [err?.message || "Verification failed"] },
          error: err?.message || "Failed to verify refactor safety",
        },
        error: err?.message || "Failed to verify refactor safety",
        isVerifying: false,
      });
      return null;
    }
  },

  applyRefactor: async (changes: RefactorChange[], verified = false, workspacePath?: string) => {
    const ws = workspacePath || useWorkspaceStore.getState().currentWorkspace?.path || "";
    set({ isApplying: true, error: null });

    // CRITICAL SAFETY RULE: Always verify before applying if not already marked safe!
    const currentVerification = get().verificationStatus;
    if (!verified && (!currentVerification || !currentVerification.safe)) {
      set({ isVerifying: true });
      const verifyRes = await get().verifyRefactor(changes, ws);
      set({ isVerifying: false });
      if (!verifyRes || !verifyRes.safe) {
        set({
          isApplying: false,
          error: "Refactor verification failed. Unsafe refactors are blocked from being applied.",
        });
        return null;
      }
      verified = true;
    }

    try {
      const response = await api.post<{ success: boolean; modified_files: string[] }>("/api/refactor/apply", {
        changes,
        verified: true,
        workspace: ws,
      });

      set({
        isApplying: false,
        isQuickFixOpen: false,
        refactorPreview: null,
        verificationStatus: null,
      });

      // Re-scan code smells to reflect fresh state
      get().analyzeCodebase(ws);

      return response;
    } catch (err: any) {
      set({
        error: err?.message || "Failed to apply refactor",
        isApplying: false,
      });
      return null;
    }
  },

  openQuickFix: (smell: CodeSmell) => {
    set({
      selectedSmell: smell,
      isQuickFixOpen: true,
    });
    // Auto-request preview for the selected smell
    let refactorType = "extract_function";
    if (smell.type === "duplicated_code") refactorType = "deduplicate";
    else if (smell.type === "dead_code" || smell.type === "unused_imports") refactorType = "remove_dead_code";
    else if (smell.type === "complex_conditional" || smell.type === "deep_nesting") refactorType = "flatten_conditionals";
    else if (smell.type === "god_class") refactorType = "extract_class";

    const selectionRange: [number, number] = [
      smell.location.line,
      smell.location.end_line || smell.location.line + 5,
    ];

    get().previewRefactor({
      refactor_type: refactorType,
      file_path: smell.location.file,
      selection_range: selectionRange,
      params: { smell_type: smell.type },
    });
  },

  closeQuickFix: () => {
    set({
      isQuickFixOpen: false,
      selectedSmell: null,
      refactorPreview: null,
      verificationStatus: null,
    });
  },

  selectSmell: (smell: CodeSmell | null) => {
    set({ selectedSmell: smell });
  },

  setSeverityFilter: (filter: "All" | SmellSeverity) => {
    set({ activeSeverityFilter: filter });
  },

  clearPreview: () => {
    set({
      refactorPreview: null,
      verificationStatus: null,
    });
  },

  reset: () => {
    set({
      codeSmells: [],
      duplicates: [],
      complexityReports: [],
      refactorPreview: null,
      verificationStatus: null,
      selectedSmell: null,
      isAnalyzing: false,
      isVerifying: false,
      isApplying: false,
      isQuickFixOpen: false,
      activeSeverityFilter: "All",
      error: null,
    });
  },
}));
