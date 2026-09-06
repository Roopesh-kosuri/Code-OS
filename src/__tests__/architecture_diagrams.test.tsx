import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import { DiagramGeneratorPanel } from "../features/diagrams/DiagramGeneratorPanel";
import { useDiagramStore } from "../features/diagrams/diagramStore";
import { useWorkspaceStore } from "../stores/workspaceStore";
import { useEditorStore } from "../stores/editorStore";
import { api } from "../lib/api";

vi.mock("../lib/api", () => ({
  api: {
    get: vi.fn(),
    post: vi.fn(),
    blob: vi.fn(),
  },
}));

// Mock mermaid module to avoid canvas/DOM errors in jsdom
vi.mock("mermaid", () => ({
  default: {
    initialize: vi.fn(),
    render: vi.fn().mockResolvedValue({
      svg: '<svg data-testid="mermaid-svg"><g class="nodes"><text>Mock Diagram SVG</text></g></svg>',
    }),
  },
}));

describe("Architecture Diagrams Frontend Test Suite", () => {
  const mockWorkspace = {
    id: "ws-test",
    path: "D:/PROJECTS/TestApp",
    name: "TestApp",
  };

  const mockAnalysis = {
    components: [
      { id: "c1", name: "AuthController", path: "auth.py", type: "controller", language: "python" },
      { id: "c2", name: "AuthService", path: "auth_service.py", type: "service", language: "python" },
      { id: "c3", name: "UserModel", path: "models.py", type: "model", language: "python" },
      { id: "c4", name: "Database", path: "db.py", type: "infrastructure", language: "python" },
    ],
    relationships: [
      { source: "AuthController", target: "AuthService", type: "calls_service", label: "authenticates" },
      { source: "AuthService", target: "UserModel", type: "uses_model", label: "queries" },
      { source: "AuthService", target: "Database", type: "connects_to", label: "connects" },
    ],
    apis: [
      { method: "POST", path: "/api/login", handler: "login", file: "auth.py", resource: "auth" },
      { method: "GET", path: "/api/profile", handler: "get_profile", file: "auth.py", resource: "auth" },
    ],
    models: [
      { name: "User", fields: [{ name: "id", type: "int" }, { name: "email", type: "str" }] },
    ],
    stats: {
      components: 4,
      relationships: 3,
      apis: 2,
      models: 1,
    },
  };

  let createObjectURLMock: any;

  beforeEach(() => {
    vi.clearAllMocks();

    createObjectURLMock = vi.fn().mockReturnValue("blob:mock-url");
    window.URL.createObjectURL = createObjectURLMock;
    if (typeof globalThis !== "undefined" && globalThis.URL) {
      globalThis.URL.createObjectURL = createObjectURLMock;
    }
    window.URL.revokeObjectURL = vi.fn();

    Object.assign(navigator, {
      clipboard: {
        writeText: vi.fn().mockResolvedValue(undefined),
      },
    });

    act(() => {
      useWorkspaceStore.setState({
        currentWorkspace: mockWorkspace as any,
      });

      useDiagramStore.getState().reset();
      useEditorStore.setState({
        openFiles: [],
        activePath: null,
      });
    });

    vi.mocked(api.post).mockImplementation(async (url: string) => {
      if (url === "/api/diagrams/analyze") {
        return mockAnalysis;
      }
      if (url === "/api/diagrams/generate") {
        return {
          diagram_id: "diag-101",
          type: "component",
          diagram_code: "graph TD\n    AuthController-->AuthService\n    AuthService-->UserModel",
          preview_svg: '<svg data-testid="generated-preview-svg"><g><text>Rendered SVG Component</text></g></svg>',
          stats: mockAnalysis.stats,
        };
      }
      return {};
    });

    vi.mocked(api.blob).mockResolvedValue(new Blob(["mock-png-data"], { type: "image/png" }));
  });

  it("test_analyze_button_triggers_scan: clicking analyze scans workspace and updates summary", async () => {
    render(<DiagramGeneratorPanel />);

    const analyzeBtn = screen.getByRole("button", { name: /analyze codebase/i });
    expect(analyzeBtn).toBeTruthy();

    await act(async () => {
      fireEvent.click(analyzeBtn);
    });

    expect(api.post).toHaveBeenCalledWith("/api/diagrams/analyze", {
      workspace: "D:/PROJECTS/TestApp",
    });

    await waitFor(() => {
      const summary = screen.getByTestId("analysis-summary");
      expect(summary.textContent).toContain("Found 4 components, 3 relationships, 2 API endpoints");
    });
  });

  it("test_diagram_type_selector_works: allows switching between diagram types", async () => {
    render(<DiagramGeneratorPanel />);

    const dataFlowBtn = screen.getByText("Data Flow Diagram");
    expect(dataFlowBtn).toBeTruthy();

    await act(async () => {
      fireEvent.click(dataFlowBtn);
    });

    expect(useDiagramStore.getState().activeType).toBe("data_flow");

    const erBtn = screen.getByText("Entity Relationship");
    await act(async () => {
      fireEvent.click(erBtn);
    });

    expect(useDiagramStore.getState().activeType).toBe("er");
  });

  it("test_preview_renders_svg: renders generated SVG diagram in preview canvas", async () => {
    act(() => {
      useDiagramStore.setState({
        diagrams: {
          component: {
            diagram_id: "diag-101",
            type: "component",
            code: "graph TD\n    A-->B",
            preview_svg: '<svg data-testid="active-svg-canvas"><text>Component Diagram Active</text></svg>',
          },
          data_flow: null,
          api: null,
          er: null,
        },
        activeType: "component",
      });
    });

    render(<DiagramGeneratorPanel />);

    await waitFor(() => {
      const pane = screen.getByTestId("diagram-preview-pane");
      expect(pane.innerHTML).toContain("<svg");
    });
  });

  it("test_export_buttons_download_files: triggers PNG, SVG download and code copying", async () => {
    act(() => {
      useDiagramStore.setState({
        diagrams: {
          component: {
            diagram_id: "diag-101",
            type: "component",
            code: "graph TD\n    A-->B",
            preview_svg: "<svg><text>Component Export</text></svg>",
          },
          data_flow: null,
          api: null,
          er: null,
        },
        activeType: "component",
      });
    });

    render(<DiagramGeneratorPanel />);

    const pngBtn = screen.getByRole("button", { name: /png/i });
    const svgBtn = screen.getByRole("button", { name: /svg/i });
    const copyBtn = screen.getByRole("button", { name: /copy/i });

    expect(pngBtn.hasAttribute("disabled")).toBe(false);
    expect(svgBtn.hasAttribute("disabled")).toBe(false);
    expect(copyBtn.hasAttribute("disabled")).toBe(false);

    await act(async () => {
      fireEvent.click(svgBtn);
    });
    expect(createObjectURLMock).toHaveBeenCalled();

    await act(async () => {
      fireEvent.click(copyBtn);
    });
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith("graph TD\n    A-->B");
  });

  it("test_open_in_editor_opens_mermaid: opens architecture mermaid file in editor store", async () => {
    act(() => {
      useDiagramStore.setState({
        diagrams: {
          component: {
            diagram_id: "diag-101",
            type: "component",
            code: "graph TD\n    Client-->API\n    API-->DB",
            preview_svg: "<svg></svg>",
          },
          data_flow: null,
          api: null,
          er: null,
        },
        activeType: "component",
      });
    });

    render(<DiagramGeneratorPanel />);

    const openEditorBtn = screen.getByRole("button", { name: /open in editor/i });
    expect(openEditorBtn).toBeTruthy();

    await act(async () => {
      fireEvent.click(openEditorBtn);
    });

    const editorFiles = useEditorStore.getState().openFiles;
    expect(editorFiles.length).toBeGreaterThan(0);
    const mmdFile = editorFiles.find((f) => f.name.includes("architecture"));
    expect(mmdFile).toBeDefined();
    expect(mmdFile?.content).toContain("graph TD");
    expect(useEditorStore.getState().activePath).toBe(mmdFile?.path);
  });
});
