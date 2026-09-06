import React from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { RefactorAssistantPanel } from "../features/refactoring/RefactorAssistantPanel";
import { useRefactorStore } from "../features/refactoring/refactorStore";
import { useWorkspaceStore } from "../stores/workspaceStore";

// Mock api
vi.mock("../lib/api", () => ({
  api: {
    get: vi.fn(),
    post: vi.fn(),
  },
}));

import { api } from "../lib/api";

describe("Refactoring Assistant Frontend Suite", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useRefactorStore.getState().reset();
    useWorkspaceStore.setState({
      currentWorkspace: { path: "D:/TestWorkspace", name: "TestWorkspace" } as any,
    });
  });

  it("test_analyze_button_triggers_code_quality_scan", async () => {
    const mockAnalyzeResponse = {
      code_smells: [
        {
          id: "smell-1",
          ruleId: "long_function",
          filePath: "src/utils/parser.ts",
          line: 45,
          endLine: 120,
          symbolName: "processPayload",
          severity: "Critical",
          message: "Function 'processPayload' exceeds 75 lines",
          suggestion: "Extract sub-routines into helper functions",
        },
        {
          id: "smell-2",
          ruleId: "duplicated_code",
          filePath: "src/utils/formatter.ts",
          line: 12,
          endLine: 35,
          symbolName: "formatDate",
          severity: "Warning",
          message: "Duplicated block found in 2 locations",
          suggestion: "Consolidate into shared date utility",
        },
      ],
      duplicates: [
        {
          code_snippet: "const formatted = date.toISOString();",
          locations: [
            { file: "src/utils/formatter.ts", lines: [12, 18] },
            { file: "src/utils/logger.ts", lines: [40, 46] },
          ],
          line_count: 6,
          similarity: 1.0,
        },
      ],
      complexity: [],
      total_smells: 2,
    };

    (api.post as any).mockResolvedValueOnce(mockAnalyzeResponse);

    render(<RefactorAssistantPanel />);

    const analyzeBtn = screen.getByTestId("analyze-code-quality-button");
    fireEvent.click(analyzeBtn);

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith("/api/refactor/analyze", {
        workspace: "D:/TestWorkspace",
      });
    });

    expect(screen.getByText(/Function 'processPayload' exceeds 75 lines/i)).toBeTruthy();
  });

  it("test_severity_filtering_narrows_displayed_smells", () => {
    useRefactorStore.setState({
      codeSmells: [
        {
          id: "smell-1",
          ruleId: "long_function",
          filePath: "src/utils/parser.ts",
          line: 45,
          severity: "Critical",
          message: "Function exceeds length",
        },
        {
          id: "smell-2",
          ruleId: "unused_imports",
          filePath: "src/utils/helper.ts",
          line: 5,
          severity: "Warning",
          message: "Unused import found",
        },
      ] as any,
    });

    render(<RefactorAssistantPanel />);

    expect(screen.getByText("long_function")).toBeTruthy();
    expect(screen.getByText("unused_imports")).toBeTruthy();

    const criticalFilter = screen.getByRole("button", { name: /^critical$/i });
    fireEvent.click(criticalFilter);

    expect(screen.getByText("long_function")).toBeTruthy();
    expect(screen.queryByText("unused_imports")).toBeNull();
  });

  it("test_quick_fix_triggers_refactor_preview", async () => {
    const mockSmell = {
      id: "smell-1",
      ruleId: "long_function",
      filePath: "src/utils/parser.ts",
      line: 45,
      endLine: 120,
      symbolName: "processPayload",
      severity: "Critical" as const,
      message: "Function exceeds length",
    };

    const mockPreviewResponse = {
      type: "extract_function",
      filePath: "src/utils/parser.ts",
      diff: "@@ -45,10 +45,6 @@\n- old_code\n+ new_code",
      explanation: "Extracted helper sub_processPayload to reduce cognitive complexity",
      impact: {
        complexity_before: 18,
        complexity_after: 8,
        lines_delta: -10,
        estimated_risk: "low",
      },
      changes: [
        {
          file: "src/utils/parser.ts",
          diff: "@@ -45,10 +45,6 @@\n- old_code\n+ new_code",
        },
      ],
    };

    (api.post as any).mockResolvedValueOnce(mockPreviewResponse);

    useRefactorStore.setState({
      codeSmells: [mockSmell] as any,
    });

    render(<RefactorAssistantPanel />);

    const quickFixBtn = screen.getByTestId("quick-fix-btn-smell-1");
    fireEvent.click(quickFixBtn);

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith("/api/refactor/preview", expect.objectContaining({
        type: "extract_function",
        filePath: "src/utils/parser.ts",
      }));
    });

    expect(screen.getByTestId("quick-fix-dialog")).toBeTruthy();
    expect(screen.getByText(/Extracted helper sub_processPayload/i)).toBeTruthy();
  });

  it("test_verification_badge_and_apply_flow", async () => {
    (api.post as any).mockResolvedValueOnce({
      success: true,
      modified_files: ["src/utils/parser.ts"],
    });

    useRefactorStore.setState({
      refactorPreview: {
        type: "extract_function",
        filePath: "src/utils/parser.ts",
        diff: "@@ -1 +1 @@",
        explanation: "Extracted function safely",
        changes: [{ file: "src/utils/parser.ts", diff: "@@ -1 +1 @@" }],
      } as any,
      verificationStatus: {
        safe: true,
        passed: true,
        message: "Sandbox test suite passed (14/14 tests green)",
        details: {
          test_summary: { passed: 14, failed: 0 },
        },
      },
      isQuickFixOpen: true,
    });

    render(<RefactorAssistantPanel />);

    expect(screen.getByTestId("verification-status-badge")).toBeTruthy();
    expect(screen.getByText(/Safe \(Tests Passed\)/i)).toBeTruthy();

    const applyBtn = screen.getByTestId("apply-refactor-button");
    fireEvent.click(applyBtn);

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith("/api/refactor/apply", expect.objectContaining({
        workspace: "D:/TestWorkspace",
      }));
    });
  });

  it("test_toggles_for_ghost_text_and_smart_staging", () => {
    render(<RefactorAssistantPanel />);

    const ghostTextToggle = screen.getByRole("button", { name: /ghost text/i });
    const smartStagingToggle = screen.getByRole("button", { name: /smart staging/i });

    expect(useRefactorStore.getState().ghostTextEnabled).toBe(true);
    fireEvent.click(ghostTextToggle);
    expect(useRefactorStore.getState().ghostTextEnabled).toBe(false);

    expect(useRefactorStore.getState().smartStagingEnabled).toBe(true);
    fireEvent.click(smartStagingToggle);
    expect(useRefactorStore.getState().smartStagingEnabled).toBe(false);
  });
});
