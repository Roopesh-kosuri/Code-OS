import React from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { SecurityDashboardPanel } from "../features/security/SecurityDashboardPanel";
import { useSecurityStore } from "../features/security/securityStore";
import { useWorkspaceStore } from "../stores/workspaceStore";

// Mock api
vi.mock("../lib/api", () => ({
  api: {
    get: vi.fn(),
    post: vi.fn(),
  },
}));

import { api } from "../lib/api";

describe("Security Scanner Frontend Suite", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useSecurityStore.getState().reset();
    useWorkspaceStore.setState({
      currentWorkspace: { path: "D:/TestWorkspace", name: "TestWorkspace" } as any,
    });
  });

  it("test_scan_button_triggers_audit", async () => {
    const mockScanResponse = {
      vulnerabilities: [
        {
          id: "vuln-1",
          file: "backend/auth.py",
          line: 12,
          severity: "Critical",
          description: "Hardcoded API key exposed",
          code_snippet: 'API_KEY = "AKIA1111222233334444"',
          status: "open",
        },
      ],
      dependency_issues: [],
    };

    (api.post as any).mockResolvedValueOnce(mockScanResponse);

    render(<SecurityDashboardPanel />);

    const scanBtn = screen.getByTestId("scan-workspace-btn");
    fireEvent.click(scanBtn);

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith("/api/security/scan", {
        workspace: "D:/TestWorkspace",
      });
    });

    expect(screen.getByText(/Hardcoded API key exposed/i)).toBeTruthy();
  });

  it("test_vulnerability_list_renders_with_severity", async () => {
    useSecurityStore.setState({
      vulnerabilities: [
        {
          id: "vuln-critical-1",
          file: "src/db.ts",
          line: 45,
          severity: "Critical",
          description: "SQL Injection vector in query builder",
          code_snippet: 'db.query("SELECT * FROM users WHERE id = " + id)',
          status: "open",
        },
        {
          id: "vuln-high-1",
          file: "src/App.tsx",
          line: 88,
          severity: "High",
          description: "dangerouslySetInnerHTML without sanitization",
          code_snippet: "<div dangerouslySetInnerHTML={{ __html: rawContent }} />",
          status: "open",
        },
      ],
      scanSummary: { critical: 1, high: 1, medium: 0, low: 0 },
    });

    render(<SecurityDashboardPanel />);

    expect(screen.getAllByText(/Critical/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/High/i).length).toBeGreaterThan(0);
    expect(screen.getByText("src/db.ts:45")).toBeTruthy();
    expect(screen.getByText("src/App.tsx:88")).toBeTruthy();
  });

  it("test_generate_fix_shows_diff", async () => {
    useSecurityStore.setState({
      vulnerabilities: [
        {
          id: "vuln-fix-test",
          file: "src/queries.py",
          line: 10,
          severity: "Critical",
          description: "Raw SQL query concatenation",
          code_snippet: 'cursor.execute(f"SELECT * FROM items WHERE id = \'{item_id}\'")',
          status: "open",
        },
      ],
    });

    const mockPatch = "--- a/src/queries.py\n+++ b/src/queries.py\n-cursor.execute(f\"SELECT * FROM items WHERE id = '{item_id}'\")\n+cursor.execute(\"SELECT * FROM items WHERE id = %s\", (item_id,))";

    (api.post as any).mockResolvedValueOnce({
      patch_diff: mockPatch,
      explanation: "Replaced raw SQL formatting with parameterized query.",
    });

    render(<SecurityDashboardPanel />);

    const generateBtn = screen.getByTestId("generate-fix-btn-vuln-fix-test");
    fireEvent.click(generateBtn);

    await waitFor(() => {
      expect(screen.getByTestId("diff-preview-vuln-fix-test")).toBeTruthy();
    });

    expect(screen.getByText(/Suggested AI Patch/i)).toBeTruthy();
  });

  it("test_apply_fix_updates_status", async () => {
    useSecurityStore.setState({
      vulnerabilities: [
        {
          id: "vuln-apply-test",
          file: "src/auth.py",
          line: 5,
          severity: "Critical",
          description: "Exposed API key",
          code_snippet: 'API_KEY = "SECRET"',
          status: "open",
          patch_diff: "--- a/src/auth.py\n+++ b/src/auth.py\n-API_KEY = \"SECRET\"\n+API_KEY = os.environ.get(\"API_KEY\", \"\")",
        },
      ],
    });

    (api.post as any).mockResolvedValueOnce({
      success: true,
      resolved: true,
      status: "resolved",
    });

    render(<SecurityDashboardPanel />);

    const applyBtn = screen.getByTestId("apply-fix-btn-vuln-apply-test");
    fireEvent.click(applyBtn);

    await waitFor(() => {
      expect(screen.getByText(/Resolved/i)).toBeTruthy();
    });
  });

  it("test_shield_badge_shows_critical_count", () => {
    useSecurityStore.setState({
      vulnerabilities: [
        {
          id: "v1",
          file: "a.py",
          line: 1,
          severity: "Critical",
          description: "Critical finding 1",
          status: "open",
        },
        {
          id: "v2",
          file: "b.py",
          line: 2,
          severity: "High",
          description: "High finding 1",
          status: "open",
        },
      ],
      scanSummary: { critical: 1, high: 1, medium: 0, low: 0 },
    });

    render(<SecurityDashboardPanel />);

    const summaryBanner = screen.getByTestId("security-summary-banner");
    expect(summaryBanner.textContent).toContain("1 Critical");
    expect(summaryBanner.textContent).toContain("1 High");
  });
});
