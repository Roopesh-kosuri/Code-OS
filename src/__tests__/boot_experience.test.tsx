import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, act } from "@testing-library/react";
import { App } from "../App";
import { useBackendStore } from "../stores/backendStore";
import { useWorkspaceStore } from "../stores/workspaceStore";
import { useAIStore } from "../stores/aiStore";
import { api } from "../lib/api";

describe("Phase 0: Boot Experience & Smart Offline Banner Suite", () => {
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

  it("test_boot_overlay_shows_during_initial_connect", () => {
    useBackendStore.setState({
      status: "connecting",
      bootPhase: "booting",
      bootStartTime: Date.now(),
      nextRetryInSeconds: 0,
      retryCount: 0,
    });

    render(<App />);

    // Boot overlay MUST be present
    const overlay = screen.getByTestId("boot-overlay");
    expect(overlay).toBeDefined();
    expect(overlay.textContent).toContain("CODE OS");
    expect(overlay.textContent).toContain("Initializing workspace");

    // Red banner MUST NOT be present during initial boot
    expect(screen.queryByTestId("backend-offline-banner")).toBeNull();
  });

  it("test_red_banner_only_after_grace_period_failure", () => {
    // 1. Initial boot state: 1st failure does not trigger red banner
    useBackendStore.setState({
      status: "connecting",
      bootPhase: "booting",
      bootStartTime: Date.now(),
      retryCount: 0,
    });

    // 1st failure within grace period
    act(() => {
      useBackendStore.getState().recordFailure(new Error("Connection refused"));
    });
    expect(useBackendStore.getState().bootPhase).toBe("booting");

    // 2nd failure within grace period
    act(() => {
      useBackendStore.getState().recordFailure(new Error("Connection refused"));
    });
    expect(useBackendStore.getState().bootPhase).toBe("booting");

    // 3rd failure: threshold reached (3 consecutive retries during boot) -> triggers 'failed'
    act(() => {
      useBackendStore.getState().recordFailure(new Error("Connection refused"));
    });
    expect(useBackendStore.getState().bootPhase).toBe("failed");
    expect(useBackendStore.getState().status).toBe("disconnected");

    render(<App />);

    // Now red banner must appear with test ID
    const banner = screen.getByTestId("backend-offline-banner");
    expect(banner).toBeDefined();
    expect(banner.textContent).toContain("Backend not running");
  });

  it("test_overlay_hides_on_connected", async () => {
    vi.useFakeTimers();

    useBackendStore.setState({
      status: "connecting",
      bootPhase: "booting",
      bootStartTime: Date.now(),
    });

    const { rerender } = render(<App />);
    expect(screen.getByTestId("boot-overlay")).toBeDefined();

    // Backend comes online -> transition to 'ready'
    act(() => {
      useBackendStore.getState().recordSuccess();
    });
    expect(useBackendStore.getState().bootPhase).toBe("ready");
    expect(useBackendStore.getState().status).toBe("connected");

    rerender(<App />);

    // Advance 300ms fade-out transition timer
    act(() => {
      vi.advanceTimersByTime(350);
    });

    // Overlay unmounted
    expect(screen.queryByTestId("boot-overlay")).toBeNull();
    expect(screen.queryByTestId("backend-offline-banner")).toBeNull();

    vi.useRealTimers();
  });

  it("test_banner_returns_for_post_boot_disconnect", () => {
    // Backend was already booted and ready
    useBackendStore.setState({
      status: "connected",
      bootPhase: "ready",
      nextRetryInSeconds: 0,
      retryCount: 0,
    });

    // Post-boot disconnect occurs
    act(() => {
      useBackendStore.getState().recordFailure(new Error("Backend killed"));
    });

    expect(useBackendStore.getState().status).toBe("disconnected");
    expect(useBackendStore.getState().bootPhase).toBe("ready");

    render(<App />);

    // Red banner must return immediately for post-boot disconnect
    const banner = screen.getByTestId("backend-offline-banner");
    expect(banner).toBeDefined();
    expect(banner.textContent).toContain("Backend not running");
  });
});
