/**
 * agentic_terminal.test.tsx — Frontend unit and integration tests for Agentic Terminal.
 *
 * Required Tests:
 * 1. test_terminal_tab_renders
 * 2. test_xterm_renders_output
 * 3. test_stream_output_updates_terminal
 * 4. test_kill_button_sends_signal
 * 5. test_terminal_selector_switches_sessions
 */

import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";

import { AgenticTerminalPanel } from "../features/terminal/AgenticTerminalPanel";
import { useAgenticTerminalStore, TerminalEvent } from "../features/terminal/agenticTerminalStore";
import { useWorkspaceStore } from "../stores/workspaceStore";
import { api } from "../lib/api";

// Mock EventSource for Vitest environment
class MockEventSource {
  url: string;
  onmessage: ((event: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  close = vi.fn();

  constructor(url: string) {
    this.url = url;
    MockEventSource.instances.push(this);
  }

  static instances: MockEventSource[] = [];
  static reset() {
    MockEventSource.instances = [];
  }
}

describe("Agentic Terminal Frontend", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    MockEventSource.reset();
    (global as any).EventSource = MockEventSource;

    vi.spyOn(api, "get").mockImplementation(async (url) => {
      if (String(url).includes("/active-sessions")) {
        return { ok: true, sessions: [] };
      }
      return { ok: true };
    });

    useWorkspaceStore.setState({
      currentWorkspace: { path: "D:/project", name: "project", is_current: true },
    });

    useAgenticTerminalStore.setState({
      sessions: {},
      activeTerminalId: null,
      streamingOutputs: {},
      isProcessRunning: {},
      isLoading: false,
      error: null,
    });
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  // Test 1: Tab / Panel renders
  it("test_terminal_tab_renders: renders agentic terminal panel, controls, and session elements", async () => {
    const termId = "term_render_test";
    useAgenticTerminalStore.setState({
      sessions: {
        [termId]: {
          terminal_id: termId,
          job_id: "job_1",
          workspace: "D:/project",
          status: "idle",
          created_at: Date.now() / 1000,
          history: [],
        },
      },
      activeTerminalId: termId,
      streamingOutputs: { [termId]: [] },
      isProcessRunning: { [termId]: false },
    });

    await act(async () => {
      render(<AgenticTerminalPanel />);
    });

    // Assert main container and control buttons
    expect(screen.getByTestId("agentic-terminal-panel")).toBeDefined();
    expect(screen.getByTestId("terminal-session-selector")).toBeDefined();
    expect(screen.getByTestId("kill-process-btn")).toBeDefined();
    expect(screen.getByTestId("clear-terminal-btn")).toBeDefined();
    expect(screen.getByTestId("new-terminal-btn")).toBeDefined();
    expect(screen.getByTestId("close-terminal-btn")).toBeDefined();
    expect(screen.getByTestId("terminal-status-badge")).toBeDefined();
    expect(screen.getByTestId("xterm-container")).toBeDefined();
  });

  // Test 2: xterm renders output and commands
  it("test_xterm_renders_output: displays command input and stdout lines", async () => {
    const termId = "term_output_test";
    const initialEvents: TerminalEvent[] = [
      { type: "input", command: "npm test", timestamp: Date.now() },
      { type: "output", line: "PASS src/test.ts", stream: "stdout", timestamp: Date.now() },
      { type: "exit", code: 0, duration_ms: 120, timestamp: Date.now() },
    ];

    useAgenticTerminalStore.setState({
      sessions: {
        [termId]: {
          terminal_id: termId,
          job_id: "job_test",
          workspace: "D:/project",
          status: "idle",
          created_at: Date.now() / 1000,
          history: [
            {
              command: "npm test",
              stdout: "PASS src/test.ts",
              stderr: "",
              exit_code: 0,
              duration_ms: 120,
              timestamp: Date.now(),
            },
          ],
        },
      },
      activeTerminalId: termId,
      streamingOutputs: { [termId]: initialEvents },
      isProcessRunning: { [termId]: false },
    });

    await act(async () => {
      render(<AgenticTerminalPanel />);
    });

    // Inspect feed elements
    const feed = screen.getByTestId("terminal-output-feed");
    expect(feed.textContent).toContain("agent@code-os:~$ npm test");
    expect(feed.textContent).toContain("PASS src/test.ts");
    expect(feed.textContent).toContain("Process exited with code 0");
  });

  // Test 3: Streaming output updates terminal state
  it("test_stream_output_updates_terminal: live SSE stream events update store and feed", async () => {
    const termId = "term_stream_test";
    useAgenticTerminalStore.setState({
      sessions: {
        [termId]: {
          terminal_id: termId,
          job_id: "job_stream",
          workspace: "D:/project",
          status: "idle",
          created_at: Date.now() / 1000,
          history: [],
        },
      },
      activeTerminalId: termId,
      streamingOutputs: { [termId]: [] },
      isProcessRunning: { [termId]: false },
    });

    await act(async () => {
      render(<AgenticTerminalPanel />);
    });

    // Verify initial state
    expect(screen.getByTestId("terminal-output-feed").textContent).toBe("");

    // Simulate incoming stream events
    act(() => {
      useAgenticTerminalStore.getState().appendEvent(termId, {
        type: "input",
        command: "python main.py",
        timestamp: Date.now(),
      });
      useAgenticTerminalStore.getState().appendEvent(termId, {
        type: "output",
        line: "Server running on port 8000",
        stream: "stdout",
        timestamp: Date.now(),
      });
    });

    // Check store state
    const currentEvents = useAgenticTerminalStore.getState().streamingOutputs[termId];
    expect(currentEvents.length).toBe(2);
    expect(currentEvents[0].command).toBe("python main.py");
    expect(currentEvents[1].line).toBe("Server running on port 8000");

    // Check DOM feed updated
    const feed = screen.getByTestId("terminal-output-feed");
    expect(feed.textContent).toContain("agent@code-os:~$ python main.py");
    expect(feed.textContent).toContain("Server running on port 8000");
  });

  // Test 4: Kill button sends signal
  it("test_kill_button_sends_signal: triggers sendSignal when process is running", async () => {
    const termId = "term_kill_test";
    const postSpy = vi.spyOn(api, "post").mockResolvedValue({ ok: true, signaled: true });

    useAgenticTerminalStore.setState({
      sessions: {
        [termId]: {
          terminal_id: termId,
          job_id: "job_kill",
          workspace: "D:/project",
          status: "running",
          created_at: Date.now() / 1000,
          history: [],
        },
      },
      activeTerminalId: termId,
      streamingOutputs: { [termId]: [] },
      isProcessRunning: { [termId]: true }, // active process running
    });

    await act(async () => {
      render(<AgenticTerminalPanel />);
    });

    const killBtn = screen.getByTestId("kill-process-btn");
    expect((killBtn as HTMLButtonElement).disabled).toBe(false);

    await act(async () => {
      fireEvent.click(killBtn);
    });

    expect(postSpy).toHaveBeenCalledWith("/api/terminal/signal", {
      terminal_id: termId,
      signal: "SIGINT",
    });
  });

  // Test 5: Terminal selector switches sessions
  it("test_terminal_selector_switches_sessions: changes active terminal ID in store and UI", async () => {
    const term1 = "term_alpha";
    const term2 = "term_beta";

    useAgenticTerminalStore.setState({
      sessions: {
        [term1]: {
          terminal_id: term1,
          job_id: "job_alpha",
          workspace: "D:/project",
          status: "idle",
          created_at: Date.now() / 1000,
          history: [],
        },
        [term2]: {
          terminal_id: term2,
          job_id: "job_beta",
          workspace: "D:/project",
          status: "idle",
          created_at: Date.now() / 1000,
          history: [],
        },
      },
      activeTerminalId: term1,
      streamingOutputs: {
        [term1]: [{ type: "output", line: "Hello from alpha", stream: "stdout", timestamp: Date.now() }],
        [term2]: [{ type: "output", line: "Hello from beta", stream: "stdout", timestamp: Date.now() }],
      },
      isProcessRunning: { [term1]: false, [term2]: false },
    });

    await act(async () => {
      render(<AgenticTerminalPanel />);
    });

    const selector = screen.getByTestId("terminal-session-selector") as HTMLSelectElement;
    expect(selector.value).toBe(term1);
    expect(screen.getByTestId("terminal-output-feed").textContent).toContain("Hello from alpha");

    // Change to term_beta
    act(() => {
      fireEvent.change(selector, { target: { value: term2 } });
    });

    expect(useAgenticTerminalStore.getState().activeTerminalId).toBe(term2);
  });
});
