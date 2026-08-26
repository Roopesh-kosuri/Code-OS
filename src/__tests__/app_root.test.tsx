import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { App } from "../App";
import { ErrorBoundary } from "../components/ErrorBoundary";
import { useBackendStore } from "../stores/backendStore";
import { useWorkspaceStore } from "../stores/workspaceStore";
import { useAIStore } from "../stores/aiStore";
import { api } from "../lib/api";

function ProblematicComponent({ shouldThrow }: { shouldThrow: boolean }) {
  if (shouldThrow) {
    throw new Error("Simulated Crash");
  }
  return <div>Healthy Component</div>;
}

describe("Frontend App Root & Error Boundary Suite", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.spyOn(api, "get").mockResolvedValue([]);
    vi.spyOn(api, "post").mockResolvedValue({});

    useWorkspaceStore.setState({
      currentWorkspace: { path: "D:/ws", name: "ws", is_current: true },
      activeWorkspaces: [{ path: "D:/ws", name: "ws", is_current: true }],
      fileTrees: { "D:/ws": { path: "D:/ws", name: "ws", is_dir: true, children: [] } },
      recentWorkspaces: [],
      loading: false,
    });
    useAIStore.setState({
      messages: [],
      streaming: false,
      agentMode: false,
    });
  });

  describe("<ErrorBoundary />", () => {
    it("catches render errors and provides recovery option", () => {
      const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});

      render(
        <ErrorBoundary>
          <ProblematicComponent shouldThrow={true} />
        </ErrorBoundary>
      );

      expect(screen.getAllByText(/Something went wrong/i).length).toBeGreaterThanOrEqual(1);
      expect(screen.getByText(/Simulated Crash/i)).toBeDefined();

      const reloadBtn = screen.getByRole("button", { name: /Try Again/i });
      expect(reloadBtn).toBeDefined();

      consoleSpy.mockRestore();
    });

    it("renders healthy children normally", () => {
      render(
        <ErrorBoundary>
          <ProblematicComponent shouldThrow={false} />
        </ErrorBoundary>
      );

      expect(screen.getByText("Healthy Component")).toBeDefined();
    });
  });

  describe("<App /> & BackendStatusBanner", () => {
    it("renders backend warning banner when disconnected", () => {
      useBackendStore.setState({
        status: "disconnected",
        nextRetryInSeconds: 5,
      });

      render(<App />);

      expect(screen.getByText(/Backend not running/i)).toBeDefined();
      expect(screen.getByText(/Retrying in 5s/i)).toBeDefined();
    });

    it("renders connected workspace shell when backend is online", () => {
      useBackendStore.setState({
        status: "connected",
        nextRetryInSeconds: 0,
      });

      render(<App />);

      expect(screen.queryByText(/Backend not running/i)).toBeNull();
      expect(screen.getAllByText(/CODE/i).length).toBeGreaterThanOrEqual(1);
    });
  });
});
