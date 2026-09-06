import React from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { StandupGeneratorPanel } from "../features/standup/StandupGeneratorPanel";
import { useStandupStore } from "../features/standup/standupStore";
import { useWorkspaceStore } from "../stores/workspaceStore";

// Mock api
vi.mock("../lib/api", () => ({
  api: {
    get: vi.fn(),
    post: vi.fn(),
  },
}));

import { api } from "../lib/api";

describe("Daily Standup Generator Frontend Suite", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useStandupStore.getState().reset();
    useWorkspaceStore.setState({
      currentWorkspace: { path: "D:/MyProject", name: "MyProject" } as any,
    });
  });

  it("test_generate_button_triggers_synthesis", async () => {
    const mockReport = "🚀 *What I did yesterday:*\n• Shipped auth service\n\n📊 *Metrics:*\n• 3 files modified, 10 tests passed, $0.50 spent";
    const mockActivity = {
      jobs_completed: [{ id: "j1" }],
      files_modified: ["a.py", "b.py", "c.py"],
      commits_made: [{ hash: "abc", message: "initial commit" }],
      tests_passed: 10,
      total_cost: "$0.50",
    };

    (api.post as any).mockResolvedValueOnce({
      report: mockReport,
      raw_activity: mockActivity,
      format: "slack",
      id: "report-123",
    });

    render(<StandupGeneratorPanel />);

    const generateBtn = screen.getByTestId("generate-standup-btn");
    fireEvent.click(generateBtn);

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith(
        "/api/standup/generate",
        expect.objectContaining({
          workspace: "D:/MyProject",
          format: "slack",
        })
      );
    });

    expect(screen.getByTestId("generated-report-textarea")).toBeTruthy();
    const textarea = screen.getByTestId("generated-report-textarea") as HTMLTextAreaElement;
    expect(textarea.value).toContain("What I did yesterday");
  });

  it("test_format_toggle_switches_slack_markdown", async () => {
    useStandupStore.setState({
      generatedReport: "Initial Report",
      format: "slack",
    });

    (api.post as any).mockResolvedValueOnce({
      report: "## What I did yesterday:\n- Shipped auth",
      raw_activity: {},
      format: "markdown",
      id: "rep-markdown",
    });

    render(<StandupGeneratorPanel />);

    const markdownBtn = screen.getByTestId("format-markdown-btn");
    fireEvent.click(markdownBtn);

    await waitFor(() => {
      expect(useStandupStore.getState().format).toBe("markdown");
    });
  });

  it("test_copy_to_clipboard_works", async () => {
    const writeTextMock = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, {
      clipboard: {
        writeText: writeTextMock,
      },
    });

    useStandupStore.setState({
      generatedReport: "Report to copy",
    });

    render(<StandupGeneratorPanel />);

    const copyBtn = screen.getByTestId("copy-clipboard-btn");
    fireEvent.click(copyBtn);

    await waitFor(() => {
      expect(writeTextMock).toHaveBeenCalledWith("Report to copy");
      expect(screen.getByText("Copied!")).toBeTruthy();
    });
  });

  it("test_raw_activity_summary_renders", () => {
    useStandupStore.setState({
      rawActivity: {
        jobs_completed: [{}, {}, {}],
        files_modified: ["f1.ts", "f2.ts"],
        commits_made: [{}, {}],
        tests_passed: 12,
        total_cost: "$1.24",
      },
    });

    render(<StandupGeneratorPanel />);

    const summary = screen.getByTestId("raw-activity-summary");
    expect(summary.textContent).toContain("Completed 3 jobs");
    expect(summary.textContent).toContain("modified 2 files");
    expect(summary.textContent).toContain("2 git commits");
    expect(summary.textContent).toContain("spent $1.24");
  });
});
