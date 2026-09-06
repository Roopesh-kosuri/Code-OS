import React from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { PipelineGeneratorPanel } from "../features/cicd/PipelineGeneratorPanel";
import { useCicdStore } from "../features/cicd/cicdStore";
import { useWorkspaceStore } from "../stores/workspaceStore";

// Mock Monaco Editor component
vi.mock("@monaco-editor/react", () => ({
  default: ({ value, options }: any) => (
    <div data-testid="mock-monaco-editor" data-readonly={String(options?.readOnly)}>
      <pre>{value}</pre>
    </div>
  ),
}));

// Mock api
vi.mock("../lib/api", () => ({
  api: {
    get: vi.fn(),
    post: vi.fn(),
  },
}));

import { api } from "../lib/api";

describe("CI/CD Pipeline Generator Frontend Suite", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useCicdStore.getState().reset();
    useWorkspaceStore.setState({
      currentWorkspace: { path: "D:/MyRepo", name: "MyRepo" } as any,
    });
  });

  it("test_analyze_button_detects_stack", async () => {
    const mockStack = {
      languages: ["python", "typescript"],
      frameworks: ["fastapi", "react"],
      test_runners: ["pytest", "vitest"],
      package_managers: ["pip", "npm"],
    };

    (api.post as any).mockResolvedValueOnce(mockStack);

    render(<PipelineGeneratorPanel />);

    const analyzeBtn = screen.getByTestId("analyze-stack-btn");
    fireEvent.click(analyzeBtn);

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith("/api/cicd/analyze", {
        workspace: "D:/MyRepo",
      });
    });

    expect(screen.getByTestId("detected-stack-info")).toBeTruthy();
    expect(screen.getByText("python")).toBeTruthy();
    expect(screen.getByText("fastapi")).toBeTruthy();
    expect(screen.getByText("pytest")).toBeTruthy();
  });

  it("test_provider_selector_works", async () => {
    render(<PipelineGeneratorPanel />);

    const gitlabBtn = screen.getByTestId("provider-gitlab-btn");
    fireEvent.click(gitlabBtn);

    expect(useCicdStore.getState().provider).toBe("gitlab");
    expect(useCicdStore.getState().filePath).toBe(".gitlab-ci.yml");

    const githubBtn = screen.getByTestId("provider-github-btn");
    fireEvent.click(githubBtn);

    expect(useCicdStore.getState().provider).toBe("github");
    expect(useCicdStore.getState().filePath).toBe(".github/workflows/ci.yml");
  });

  it("test_yaml_preview_renders_in_monaco", async () => {
    const mockYaml = "name: CI\non: [push]\njobs:\n  build:\n    runs-on: ubuntu-latest";

    useCicdStore.setState({
      yamlContent: mockYaml,
      provider: "github",
    });

    render(<PipelineGeneratorPanel />);

    expect(screen.getByTestId("monaco-yaml-preview")).toBeTruthy();
    expect(screen.getByTestId("mock-monaco-editor").textContent).toContain("name: CI");
  });

  it("test_save_button_writes_file", async () => {
    useCicdStore.setState({
      yamlContent: "name: CI Pipeline",
      filePath: ".github/workflows/ci.yml",
    });

    (api.post as any).mockResolvedValueOnce({
      success: true,
      file_path: ".github/workflows/ci.yml",
    });

    render(<PipelineGeneratorPanel />);

    const saveBtn = screen.getByTestId("save-pipeline-btn");
    fireEvent.click(saveBtn);

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith("/api/cicd/save", {
        workspace: "D:/MyRepo",
        yaml_content: "name: CI Pipeline",
        file_path: ".github/workflows/ci.yml",
      });
    });

    expect(screen.getByTestId("save-status-msg")).toBeTruthy();
  });

  it("test_edit_manually_toggle_enables_monaco", async () => {
    useCicdStore.setState({
      yamlContent: "name: Pipeline",
      isEditable: false,
    });

    render(<PipelineGeneratorPanel />);

    const monacoBefore = screen.getByTestId("mock-monaco-editor");
    expect(monacoBefore.getAttribute("data-readonly")).toBe("true");

    const editToggle = screen.getByTestId("edit-manually-toggle");
    fireEvent.click(editToggle);

    expect(useCicdStore.getState().isEditable).toBe(true);
    const monacoAfter = screen.getByTestId("mock-monaco-editor");
    expect(monacoAfter.getAttribute("data-readonly")).toBe("false");
  });
});
