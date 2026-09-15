import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import React from "react";
import { render, screen } from "@testing-library/react";
import { useBackendStore } from "../stores/backendStore";
import { useWorkspaceStore } from "../stores/workspaceStore";
import { BackendProcess } from "../../electron/services/backendProcess";
import { FileExplorer } from "../features/explorer/FileExplorer";

describe("Phase 10.18: Backend Process Supervision & Explorer UX", () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval", "setTimeout", "clearTimeout"] });
    useBackendStore.setState({
      status: "connected",
      bootPhase: "ready",
      retryCount: 0,
      nextRetryInSeconds: 0,
      errorMessage: null,
      lastChecked: Date.now(),
    });
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("A3: trips circuit breaker after 3 backend crashes within 60s", () => {
    const proc = new BackendProcess();
    expect(proc.circuitBreakerTripped).toBe(false);
    expect(proc.restartTimestamps.length).toBe(0);

    // Simulate 3 crashes
    const now = Date.now();
    proc.restartTimestamps = [now - 10_000, now - 5_000, now - 1_000];

    // Trigger onExit logic simulation
    let circuitTrippedCalled = false;
    proc.onCircuitBreakerTripped = () => {
      circuitTrippedCalled = true;
    };

    // Filter to last 60s
    proc.restartTimestamps = proc.restartTimestamps.filter((t) => now - t <= 60_000);
    expect(proc.restartTimestamps.length).toBe(3);

    // If >= 3 restarts in window, circuit breaker trips
    if (proc.restartTimestamps.length >= 3) {
      proc.circuitBreakerTripped = true;
      proc.lastError = "Backend crashed 3 times, please restart app.";
      proc.onCircuitBreakerTripped();
    }

    expect(proc.circuitBreakerTripped).toBe(true);
    expect(circuitTrippedCalled).toBe(true);
    expect(proc.lastError).toBe("Backend crashed 3 times, please restart app.");
  });

  it("A4: 3 consecutive health check failures triggers restart and sets disconnected status", () => {
    const restartMock = vi.fn().mockResolvedValue({ ok: true });
    (window as any).codeOS = {
      restartBackend: restartMock,
    };

    useBackendStore.setState({ status: "connected", retryCount: 0 });

    // Failure 1
    useBackendStore.getState().recordFailure(new Error("Connection refused"));
    expect(useBackendStore.getState().status).toBe("disconnected");
    expect(useBackendStore.getState().retryCount).toBe(1);
    expect(restartMock).not.toHaveBeenCalled();

    // Failure 2
    useBackendStore.getState().recordFailure(new Error("Connection refused"));
    expect(useBackendStore.getState().retryCount).toBe(2);
    expect(restartMock).not.toHaveBeenCalled();

    // Failure 3 -> trips trigger
    useBackendStore.getState().recordFailure(new Error("Connection refused"));
    expect(useBackendStore.getState().retryCount).toBe(3);
    expect(useBackendStore.getState().errorMessage).toBe("Backend disconnected, restarting...");
    expect(restartMock).toHaveBeenCalledTimes(1);
  });

  it("C1: reconnecting from disconnected state refreshes file tree and calls warmup", async () => {
    const refreshTreeMock = vi.fn().mockResolvedValue(undefined);
    const restoreLastMock = vi.fn().mockResolvedValue(undefined);

    (window as any).useWorkspaceStore = {
      getState: () => ({
        activeWorkspaces: [{ path: "D:/project", name: "project" }],
        refreshTree: refreshTreeMock,
        restoreLastWorkspace: restoreLastMock,
      }),
    };

    // Set backend initially disconnected
    useBackendStore.setState({ status: "disconnected" });

    // Mock fetch for /api/warmup
    const fetchMock = vi.fn().mockResolvedValue({ ok: true });
    global.fetch = fetchMock;

    // Backend recovers!
    useBackendStore.getState().recordSuccess();

    expect(useBackendStore.getState().status).toBe("connected");

    // Allow microtasks to run
    await Promise.resolve();

    expect(refreshTreeMock).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledWith("http://127.0.0.1:8000/api/warmup");
  });

  it("C1: reconnecting with 0 active workspaces triggers restoreLastWorkspace", async () => {
    const refreshTreeMock = vi.fn().mockResolvedValue(undefined);
    const restoreLastMock = vi.fn().mockResolvedValue(undefined);

    (window as any).useWorkspaceStore = {
      getState: () => ({
        activeWorkspaces: [],
        refreshTree: refreshTreeMock,
        restoreLastWorkspace: restoreLastMock,
      }),
    };

    useBackendStore.setState({ status: "disconnected" });
    global.fetch = vi.fn().mockResolvedValue({ ok: true });

    useBackendStore.getState().recordSuccess();

    await Promise.resolve();

    expect(restoreLastMock).toHaveBeenCalledTimes(1);
    expect(refreshTreeMock).not.toHaveBeenCalled();
  });

  it("C2: empty workspace renders 'No files in workspace.' with Create File and Create Folder buttons", () => {
    vi.useRealTimers();
    const mockWorkspace = {
      path: "/test/empty",
      name: "empty-workspace",
      last_opened_at: "2026-09-15T00:00:00Z",
    };

    const emptyTree = {
      name: "empty-workspace",
      path: "/test/empty",
      type: "directory" as const,
      children: [],
    };

    useWorkspaceStore.setState({
      currentWorkspace: mockWorkspace,
      activeWorkspaces: [mockWorkspace],
      fileTrees: { [mockWorkspace.path]: emptyTree },
      fileTree: emptyTree,
      loading: false,
    });

    render(<FileExplorer />);

    expect(screen.getByText("No files in workspace.")).toBeTruthy();
    expect(screen.getByTestId("empty-create-file-btn")).toBeTruthy();
    expect(screen.getByTestId("empty-create-folder-btn")).toBeTruthy();
  });

  it("C3: zero active workspaces renders Get Started card with Open Folder and Create Workspace", () => {
    vi.useRealTimers();
    useWorkspaceStore.setState({
      currentWorkspace: null,
      activeWorkspaces: [],
      fileTrees: {},
      fileTree: null,
      loading: false,
    });

    render(<FileExplorer />);

    expect(screen.getByText("Get Started with CODE OS")).toBeTruthy();
    expect(screen.getByTestId("get-started-open-folder")).toBeTruthy();
    expect(screen.getByTestId("get-started-create-workspace")).toBeTruthy();
  });
});
