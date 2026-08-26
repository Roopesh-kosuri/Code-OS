import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import React from "react";
import { SearchPanel } from "../features/search/SearchPanel";
import { useWorkspaceStore } from "../stores/workspaceStore";
import { api } from "../lib/api";

vi.mock("../lib/api", () => ({
  api: {
    get: vi.fn(),
    post: vi.fn(),
  },
}));

describe("Phase 1: Search & Replace Across Files", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useWorkspaceStore.setState({
      currentWorkspace: { path: "/workspace/my-project", name: "my-project", last_opened_at: "" },
      trustedWorkspaces: { "/workspace/my-project": true },
      restrictedMode: false,
    });
  });

  it("renders search and replace inputs and options", () => {
    render(<SearchPanel />);
    expect(screen.getByTestId("search-query-input")).toBeTruthy();
    expect(screen.getByTestId("replace-query-input")).toBeTruthy();
    expect(screen.getByLabelText(/Match Case/i)).toBeTruthy();
    expect(screen.getByLabelText(/Whole Word/i)).toBeTruthy();
    expect(screen.getByLabelText(/Use Regex/i)).toBeTruthy();
  });

  it("performs search and displays matches grouped by file with selection checkboxes", async () => {
    vi.mocked(api.get).mockResolvedValue([
      { path: "/workspace/my-project/src/index.ts", line: 10, column: 5, preview: "const x = 'test';" },
      { path: "/workspace/my-project/src/index.ts", line: 20, column: 1, preview: "console.log('test');" },
      { path: "/workspace/my-project/docs/README.md", line: 5, column: 1, preview: "# test project" },
    ]);

    render(<SearchPanel />);
    const searchInput = screen.getByTestId("search-query-input");
    fireEvent.change(searchInput, { target: { value: "test" } });
    fireEvent.click(screen.getByTestId("search-submit-btn"));

    await waitFor(() => {
      expect(api.get).toHaveBeenCalledWith("/api/search/text", expect.objectContaining({
        query: "test",
        workspace: "/workspace/my-project",
      }));
    });

    // File group headers rendered
    expect(await screen.findByText("index.ts")).toBeTruthy();
    expect(await screen.findByText("README.md")).toBeTruthy();

    // Matches rendered
    expect(await screen.findByText("const x = 'test';")).toBeTruthy();
    expect(await screen.findByText("console.log('test');")).toBeTruthy();
  });

  it("executes single-file replace on replace button click", async () => {
    vi.mocked(api.get).mockResolvedValue([
      { path: "/workspace/my-project/src/index.ts", line: 10, column: 5, preview: "const x = 'test';" },
    ]);
    vi.mocked(api.post).mockResolvedValue([{ path: "/workspace/my-project/src/index.ts", replacements: 1 }]);

    render(<SearchPanel />);
    const searchInput = screen.getByTestId("search-query-input");
    const replaceInput = screen.getByTestId("replace-query-input");

    fireEvent.change(searchInput, { target: { value: "test" } });
    fireEvent.change(replaceInput, { target: { value: "prod" } });
    fireEvent.click(screen.getByTestId("search-submit-btn"));

    const replaceFileBtn = await screen.findByTestId("replace-file-btn");
    fireEvent.click(replaceFileBtn);

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith("/api/search/replace", expect.objectContaining({
        workspace: "/workspace/my-project",
        query: "test",
        replacement: "prod",
        apply: true,
        files: ["/workspace/my-project/src/index.ts"],
      }));
    });
  });

  it("displays error banner when replace is blocked in Restricted Mode (403)", async () => {
    vi.mocked(api.get).mockResolvedValue([
      { path: "/workspace/my-project/src/index.ts", line: 10, column: 5, preview: "const x = 'test';" },
    ]);
    vi.mocked(api.post).mockRejectedValue(new Error("Workspace in Restricted Mode (403 Forbidden)"));

    render(<SearchPanel />);
    fireEvent.change(screen.getByTestId("search-query-input"), { target: { value: "test" } });
    fireEvent.change(screen.getByTestId("replace-query-input"), { target: { value: "prod" } });
    fireEvent.click(screen.getByTestId("search-submit-btn"));

    const replaceFileBtn = await screen.findByTestId("replace-file-btn");
    fireEvent.click(replaceFileBtn);

    expect(await screen.findByTestId("search-error-banner")).toBeTruthy();
    expect(await screen.findByText(/Action blocked: Workspace is in Restricted Mode/i)).toBeTruthy();
  });

  it("shows confirmation modal if more than 20 files are affected", async () => {
    const multiMatches = Array.from({ length: 25 }, (_, i) => ({
      path: `/workspace/my-project/src/file_${i}.ts`,
      line: 1,
      column: 1,
      preview: `test content ${i}`,
    }));
    vi.mocked(api.get).mockResolvedValue(multiMatches);

    render(<SearchPanel />);
    fireEvent.change(screen.getByTestId("search-query-input"), { target: { value: "test" } });
    fireEvent.change(screen.getByTestId("replace-query-input"), { target: { value: "prod" } });
    fireEvent.click(screen.getByTestId("search-submit-btn"));

    expect(await screen.findByText("file_0.ts")).toBeTruthy();
    const replaceAllBtn = await screen.findByTestId("replace-all-btn");

    fireEvent.click(replaceAllBtn);

    // Confirmation modal appears
    expect(await screen.findByText(/Batch Replace Confirmation/i)).toBeTruthy();
    const filesElements = await screen.findAllByText(/25 files/i);
    expect(filesElements.length).toBeGreaterThan(0);
  });
});
