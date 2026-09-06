import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { RonyVoicePanel } from "../features/rony/RonyVoicePanel";
import { useRonyVoiceStore } from "../features/rony/ronyVoiceStore";
import { api } from "../lib/api";

// Mock API
vi.mock("../lib/api", () => ({
  api: {
    get: vi.fn(),
    post: vi.fn(),
    delete: vi.fn(),
    streamSSE: vi.fn(),
  },
}));

describe("Rony Voice Frontend Test Suite", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useRonyVoiceStore.setState({
      isListening: false,
      isProcessing: false,
      isAutomating: false,
      systemControlEnabled: false,
      alwaysListening: false,
      wakeWord: "Hey Rony",
      wakeWordDetected: false,
      currentTranscript: "",
      activeAutomation: null,
      pendingApproval: null,
      commandHistory: [],
    });
  });

  // ── Test 1: System control toggle renders and toggles ──────────────────────
  it("test_system_control_toggle_renders: renders toggle and switches between Code OS and Laptop Control", () => {
    render(<RonyVoicePanel isOpen={true} />);

    const toggle = screen.getByTestId("system-control-toggle");
    expect(toggle).toBeDefined();
    expect(toggle.textContent).toContain("CODE OS ONLY (OFF)");
    expect(useRonyVoiceStore.getState().systemControlEnabled).toBe(false);

    // Click toggle
    fireEvent.click(toggle);

    expect(useRonyVoiceStore.getState().systemControlEnabled).toBe(true);
    expect(toggle.textContent).toContain("LAPTOP CONTROL (ON)");
  });

  // ── Test 2: Wake word indicator shows configured wake word ────────────────
  it("test_wake_word_indicator_shows: displays active wake word indicator", () => {
    render(<RonyVoicePanel isOpen={true} />);

    const indicator = screen.getByTestId("wake-word-indicator");
    expect(indicator).toBeDefined();
    expect(indicator.textContent).toContain("Hey Rony");
  });

  // ── Test 3: Automation status updates and displays progress ───────────────
  it("test_automation_status_updates: renders progress bar and multi-step description", () => {
    useRonyVoiceStore.setState({
      activeAutomation: {
        type: "research",
        progress: 65,
        current_step: 2,
        total_steps: 3,
        description: "Extracting web research findings and citations...",
      },
    });

    render(<RonyVoicePanel isOpen={true} />);

    const statusBar = screen.getByTestId("automation-status-bar");
    expect(statusBar).toBeDefined();
    expect(statusBar.textContent).toContain("Extracting web research findings");
    expect(statusBar.textContent).toContain("Step 2/3 (65%)");
  });

  // ── Test 4: Approval dialog appears for destructive action ─────────────────
  it("test_approval_dialog_appears: displays approval modal with Approve/Deny buttons", () => {
    useRonyVoiceStore.setState({
      pendingApproval: {
        id: "approval-42",
        title: "Destructive Action Warning",
        action: "delete_files",
        details: { file_count: 3 },
        message: "Rony wants to delete 3 files. Approve?",
      },
    });

    render(<RonyVoicePanel isOpen={true} />);

    const dialog = screen.getByTestId("approval-dialog");
    expect(dialog).toBeDefined();
    expect(dialog.textContent).toContain("Destructive Action Warning");
    expect(dialog.textContent).toContain("Rony wants to delete 3 files. Approve?");

    const denyBtn = screen.getByTestId("reject-action-btn");
    const approveBtn = screen.getByTestId("approve-action-btn");
    expect(denyBtn).toBeDefined();
    expect(approveBtn).toBeDefined();

    // Denying clears approval and logs in history
    fireEvent.click(denyBtn);

    expect(useRonyVoiceStore.getState().pendingApproval).toBeNull();
    const history = useRonyVoiceStore.getState().commandHistory;
    expect(history.length).toBe(1);
    expect(history[0].status).toBe("aborted");
    expect(history[0].command).toContain("Denied: delete_files");
  });

  // ── Test 5: Emergency stop button works ────────────────────────────────────
  it("test_emergency_stop_button_works: clicking Emergency Stop triggers API and resets automation", async () => {
    (api.post as any).mockResolvedValueOnce({ status: "emergency_stopped" });

    useRonyVoiceStore.setState({
      isListening: true,
      isAutomating: true,
      activeAutomation: {
        type: "booking",
        progress: 40,
        current_step: 2,
        total_steps: 4,
        description: "Booking in progress...",
      },
    });

    render(<RonyVoicePanel isOpen={true} />);

    const stopBtn = screen.getByTestId("emergency-stop-btn");
    fireEvent.click(stopBtn);

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith("/api/rony/emergency-stop");
    });

    const state = useRonyVoiceStore.getState();
    expect(state.isListening).toBe(false);
    expect(state.isAutomating).toBe(false);
    expect(state.activeAutomation).toBeNull();
  });

  // ── Test 6: Command history renders ────────────────────────────────────────
  it("test_command_history_renders: displays chronological log of commands and badges", () => {
    useRonyVoiceStore.setState({
      commandHistory: [
        {
          id: "cmd-1",
          command: "Hey Rony, open Chrome",
          timestamp: Date.now() - 5000,
          status: "success",
          result: "Opened Chrome browser",
        },
        {
          id: "cmd-2",
          command: "Hey Rony, delete temp directory",
          timestamp: Date.now() - 2000,
          status: "aborted",
          result: "User declined destructive operation.",
        },
      ],
    });

    render(<RonyVoicePanel isOpen={true} />);

    const historyList = screen.getByTestId("command-history-list");
    expect(historyList).toBeDefined();

    const item1 = screen.getByTestId("history-item-cmd-1");
    expect(item1.textContent).toContain("Hey Rony, open Chrome");
    expect(item1.textContent).toContain("success");

    const item2 = screen.getByTestId("history-item-cmd-2");
    expect(item2.textContent).toContain("Hey Rony, delete temp directory");
    expect(item2.textContent).toContain("aborted");
  });
});
