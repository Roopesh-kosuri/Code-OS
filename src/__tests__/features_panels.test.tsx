import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { CustomSelect } from "../components/ui/CustomSelect";
import { ProviderSelector } from "../components/ui/ProviderSelector";
import { PerformanceDashboard } from "../features/diagnostics/PerformanceDashboard";
import { CodeVerifierPanel } from "../features/verifier/CodeVerifierPanel";
import { RepoUnderstanding } from "../features/explorer/RepoUnderstanding";
import { useWorkspaceStore } from "../stores/workspaceStore";
import { useBackendStore } from "../stores/backendStore";
import { api } from "../lib/api";

describe("Frontend Dashboard & Panels", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    useWorkspaceStore.setState({
      currentWorkspace: { path: "D:/ws", name: "ws", is_current: true },
    });
    useBackendStore.setState({ status: "connected" });
  });

  describe("<CustomSelect />", () => {
    it("renders selected option and handles item selection", () => {
      const handleChange = vi.fn();
      const options = [
        { value: "opt1", label: "Option 1", badge: "Fast" },
        { value: "opt2", label: "Option 2", description: "Detailed desc" },
      ];

      render(
        <CustomSelect
          value="opt1"
          onChange={handleChange}
          options={options}
        />
      );

      const trigger = screen.getByRole("button");
      expect(screen.getByText("Option 1")).toBeDefined();
      expect(screen.getByText("Fast")).toBeDefined();

      fireEvent.click(trigger);
      const opt2 = screen.getByText("Option 2");
      fireEvent.click(opt2);
      expect(handleChange).toHaveBeenCalledWith("opt2");
    });
  });

  describe("<ProviderSelector />", () => {
    it("renders provider and model inputs", () => {
      const handleChange = vi.fn();
      render(
        <ProviderSelector
          value={{
            provider: "ollama",
            preset: "ollama",
            model: "qwen2.5-coder:7b",
            base_url: "http://127.0.0.1:11434",
            api_key_provider: null,
          }}
          onChange={handleChange}
        />
      );

      expect(screen.getAllByText(/Provider/i).length).toBeGreaterThanOrEqual(1);
    });
  });

  describe("<PerformanceDashboard />", () => {
    it("renders dashboard and system performance metrics", async () => {
      vi.spyOn(api, "get").mockResolvedValue({
        system: {
          cpu_usage_percent: 24.5,
          memory_usage_percent: 48.2,
          memory_used_mb: 4096,
          memory_total_mb: 8192,
          active_threads: 12,
          active_agent_jobs: 0,
        },
        ai: {
          total_tokens: 1500,
          average_latency_sec: 0.8,
          total_requests: 10,
          estimated_cost_usd: 0.02,
        },
        plugins: {
          loaded_count: 3,
          load_times_ms: {},
        },
      });

      render(<PerformanceDashboard />);
      expect(screen.getAllByText(/System Metrics/i).length).toBeGreaterThanOrEqual(1);
    });
  });

  describe("<CodeVerifierPanel />", () => {
    it("renders code verifier panel with security audit controls", () => {
      render(<CodeVerifierPanel />);
      expect(screen.getAllByText(/Security/i).length).toBeGreaterThanOrEqual(1);
    });
  });

  describe("<RepoUnderstanding />", () => {
    it("renders repo understanding summary component", () => {
      render(<RepoUnderstanding />);
      expect(screen.getAllByText(/Repository Intelligence/i).length).toBeGreaterThanOrEqual(1);
    });
  });
});
