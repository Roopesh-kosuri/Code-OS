import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { LiquidGlassModelSelector } from "../components/ui/LiquidGlassModelSelector";
import { AgentConsole } from "../features/ai/AgentConsole";
import { useAIStore } from "../stores/aiStore";
import { useWorkspaceStore } from "../stores/workspaceStore";
import { api } from "../lib/api";

// Mock API
vi.mock("../lib/api", () => ({
  api: {
    get: vi.fn(),
    post: vi.fn(),
    delete: vi.fn(),
  },
}));

import { useBackendStore } from "../stores/backendStore";

describe("Liquid Glass Model Selector & Task Steering Chat", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useBackendStore.setState({ status: "connected" });
    useWorkspaceStore.setState({
      currentWorkspace: {
        id: "ws-test",
        name: "test-workspace",
        path: "D:/PROJECTS/test",
      } as any,
    });
    useAIStore.setState({
      preset: "anthropic",
      model: "claude-3-5-sonnet-latest",
    });
  });

  it("test_liquid_glass_model_selector_opens_and_filters: opens popover and filters models by search query", () => {
    const handleChange = vi.fn();
    render(
      <LiquidGlassModelSelector
        value="claude-3-5-sonnet-latest"
        provider="anthropic"
        onChange={handleChange}
        testId="test-model-trigger"
        inputTestId="test-model-input"
      />
    );

    // Initial trigger button renders model name
    expect(screen.getByTestId("test-model-trigger")).toBeDefined();
    expect(screen.getByText("Claude 3.5 Sonnet")).toBeDefined();

    // Click trigger to open popover
    fireEvent.click(screen.getByTestId("test-model-trigger"));

    // Search input is rendered
    const searchInput = screen.getByPlaceholderText(/Search anthropic models/i);
    expect(searchInput).toBeDefined();

    // Type query to filter
    fireEvent.change(searchInput, { target: { value: "haiku" } });

    // Haiku model is visible
    expect(screen.getByText("Claude 3.5 Haiku")).toBeDefined();

    // Click Haiku model to select it
    fireEvent.click(screen.getByText("Claude 3.5 Haiku"));
    expect(handleChange).toHaveBeenCalledWith(
      expect.stringContaining("haiku"),
      "anthropic"
    );
  });

  it("test_liquid_glass_model_selector_custom_entry: allows typing and applying custom model ID", () => {
    const handleChange = vi.fn();
    render(
      <LiquidGlassModelSelector
        value="claude-3-5-sonnet-latest"
        provider="anthropic"
        onChange={handleChange}
        testId="test-custom-trigger"
      />
    );

    fireEvent.click(screen.getByTestId("test-custom-trigger"));

    // Click "+ Custom Model ID" button
    const customBtn = screen.getByText(/Custom Model ID/i);
    fireEvent.click(customBtn);

    // Input custom ID
    const customInput = screen.getByPlaceholderText(/Enter custom model ID/i);
    fireEvent.change(customInput, { target: { value: "custom-org/my-fine-tuned-model" } });

    // Click Apply
    const applyBtn = screen.getByText("Apply");
    fireEvent.click(applyBtn);

    expect(handleChange).toHaveBeenCalledWith("custom-org/my-fine-tuned-model", "anthropic");
  });

  it("test_agent_console_steering_tab_and_action: switches to steering tab and sends steer action", async () => {
    (api.get as any).mockImplementation((url: string) => {
      if (url === "/api/agents/jobs") {
        return Promise.resolve([
          { id: "job-test-123", status: "paused", workflow: "Implement authentication" },
        ]);
      }
      if (url.includes("/api/agents/jobs/job-test-123")) {
        return Promise.resolve({
          id: "job-test-123",
          workspace: "D:/PROJECTS/test",
          workflow: "Implement authentication",
          status: "paused",
          tasks: [
            { id: "t1", title: "Write auth handler", agent_role: "coder", status: "paused" },
          ],
          logs: ["[02:00:00] INFO: Step paused awaiting operator"],
        });
      }
      return Promise.resolve([]);
    });

    (api.post as any).mockResolvedValue({ status: "steered_and_resumed" });

    render(<AgentConsole />);

    // Wait for active job to populate
    await waitFor(() => {
      expect(screen.getByText(/Live Logs/i)).toBeDefined();
    });

    // Click Steering Chat tab
    const steerTab = screen.getByTestId("tab-task-steering");
    fireEvent.click(steerTab);

    // Paused alert banner and quick chips should be visible
    expect(screen.getByText(/Workflow paused. Ready for operator steering/i)).toBeDefined();
    expect(screen.getByText(/Continue what you stopped/i)).toBeDefined();
    expect(screen.getByText(/Retry current step/i)).toBeDefined();

    // Click "Continue what you stopped" chip
    const continueChip = screen.getByText(/Continue what you stopped/i);
    fireEvent.click(continueChip);

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith(
        "/api/agents/jobs/job-test-123/steer",
        expect.objectContaining({
          action: "continue",
        })
      );
    });

    // Verify directive history logged
    await waitFor(() => {
      expect(screen.getByText("CONTINUE")).toBeDefined();
    });
  });
});
