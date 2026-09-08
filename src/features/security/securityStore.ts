import { create } from "zustand";
import { api } from "../../lib/api";

export interface Vulnerability {
  id: string;
  file: string;
  line: number;
  severity: "Critical" | "High" | "Medium" | "Low" | string;
  description: string;
  status: "open" | "resolved" | "fixing" | string;
  cve_id?: string | null;
  code_snippet?: string;
  patch_diff?: string;
  explanation?: string;
  workspace?: string;
}

export interface DependencyIssue {
  package: string;
  current_version: string;
  safe_version: string;
  cve: string;
  severity?: string;
  description?: string;
}

interface SecurityState {
  vulnerabilities: Vulnerability[];
  dependencyIssues: DependencyIssue[];
  isScanning: boolean;
  isFixing: boolean;
  activeFixId: string | null;
  scanSummary: {
    critical: number;
    high: number;
    medium: number;
    low: number;
  };

  // Actions
  scanWorkspace: (workspace: string) => Promise<void>;
  generateFix: (vulnerabilityId: string, workspace?: string) => Promise<string | null>;
  applyFix: (vulnerabilityId: string, patch?: string, workspace?: string) => Promise<boolean>;
  fixAll: (workspace?: string) => Promise<void>;
  reset: () => void;
}

export const useSecurityStore = create<SecurityState>((set, get) => ({
  vulnerabilities: [],
  dependencyIssues: [],
  isScanning: false,
  isFixing: false,
  activeFixId: null,
  scanSummary: {
    critical: 0,
    high: 0,
    medium: 0,
    low: 0,
  },

  scanWorkspace: async (workspace: string) => {
    if (!workspace) return;
    set({ isScanning: true });
    try {
      const res = await api.post<{
        vulnerabilities: Vulnerability[];
        dependency_issues: DependencyIssue[];
      }>("/api/security/scan", { workspace });

      const vulns = (res.vulnerabilities || []).map((v) => ({
        ...v,
        status: v.status || "open",
      }));

      const summary = {
        critical: vulns.filter((v) => v.severity.toLowerCase() === "critical").length,
        high: vulns.filter((v) => v.severity.toLowerCase() === "high").length,
        medium: vulns.filter((v) => v.severity.toLowerCase() === "medium").length,
        low: vulns.filter((v) => v.severity.toLowerCase() === "low").length,
      };

      set({
        vulnerabilities: vulns,
        dependencyIssues: res.dependency_issues || [],
        scanSummary: summary,
        isScanning: false,
      });
    } catch (err) {
      console.error("[securityStore] scanWorkspace error:", err);
      set({ isScanning: false });
    }
  },

  generateFix: async (vulnerabilityId: string, workspace?: string) => {
    const vuln = get().vulnerabilities.find((v) => v.id === vulnerabilityId);
    if (!vuln) return null;

    set({ activeFixId: vulnerabilityId });
    try {
      // Fall back to workspace embedded in vuln object by the scanner
      const effectiveWorkspace = workspace || vuln.workspace;
      const res = await api.post<{
        patch_diff: string;
        explanation: string;
      }>("/api/security/generate-fix", {
        vulnerability_id: vulnerabilityId,
        vulnerability: { ...vuln, workspace: effectiveWorkspace },
        workspace: effectiveWorkspace,
      });

      set((state) => ({
        vulnerabilities: state.vulnerabilities.map((v) =>
          v.id === vulnerabilityId
            ? { ...v, patch_diff: res.patch_diff, explanation: res.explanation }
            : v
        ),
      }));

      return res.patch_diff;
    } catch (err) {
      console.error("[securityStore] generateFix error:", err);
      return null;
    }
  },

  applyFix: async (vulnerabilityId: string, patch?: string, workspace?: string) => {
    const vuln = get().vulnerabilities.find((v) => v.id === vulnerabilityId);
    if (!vuln) return false;

    const patchToApply = patch || vuln.patch_diff;
    if (!patchToApply) return false;

    set({ isFixing: true });
    try {
      const res = await api.post<{
        success: boolean;
        resolved: boolean;
        status: string;
      }>("/api/security/apply-fix", {
        vulnerability_id: vulnerabilityId,
        patch: patchToApply,
        workspace,
      });

      if (res.success) {
        set((state) => {
          const updated = state.vulnerabilities.map((v) =>
            v.id === vulnerabilityId
              ? { ...v, status: res.resolved ? "resolved" : "applied" }
              : v
          );
          return {
            vulnerabilities: updated,
            scanSummary: {
              critical: updated.filter(
                (v) => v.status === "open" && v.severity.toLowerCase() === "critical"
              ).length,
              high: updated.filter(
                (v) => v.status === "open" && v.severity.toLowerCase() === "high"
              ).length,
              medium: updated.filter(
                (v) => v.status === "open" && v.severity.toLowerCase() === "medium"
              ).length,
              low: updated.filter(
                (v) => v.status === "open" && v.severity.toLowerCase() === "low"
              ).length,
            },
            isFixing: false,
          };
        });
        return true;
      }
      set({ isFixing: false });
      return false;
    } catch (err) {
      console.error("[securityStore] applyFix error:", err);
      set({ isFixing: false });
      return false;
    }
  },

  fixAll: async (workspace?: string) => {
    const criticals = get().vulnerabilities.filter(
      (v) => v.severity.toLowerCase() === "critical" && v.status === "open"
    );
    for (const vuln of criticals) {
      const patch = await get().generateFix(vuln.id, workspace);
      if (patch) {
        await get().applyFix(vuln.id, patch, workspace);
      }
    }
  },

  reset: () =>
    set({
      vulnerabilities: [],
      dependencyIssues: [],
      isScanning: false,
      isFixing: false,
      activeFixId: null,
      scanSummary: { critical: 0, high: 0, medium: 0, low: 0 },
    }),
}));
