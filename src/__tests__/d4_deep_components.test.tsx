import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { SettingsModal } from "../components/settings/SettingsModal";
import { DuoPanel } from "../features/duo/DuoPanel";
import { AgentConsole } from "../features/ai/AgentConsole";
import { useWorkspaceStore } from "../stores/workspaceStore";
import { useSettingsStore } from "../stores/settingsStore";
import { useBackendStore } from "../stores/backendStore";
import { useAIStore } from "../stores/aiStore";
import { api } from "../lib/api";

describe("D4 Deep Components Suite (SettingsModal, DuoPanel, AgentConsole)", () => {
  const mockDetailedJob = {
    id: "job-1",
    agent_type: "coder",
    workflow: "Refactor auth middleware",
    status: "running",
    created_at: "2026-08-26T20:00:00Z",
    tasks: [
      {
        id: "t-1",
        title: "Extract token check",
        status: "completed",
        agent_role: "coder",
      },
    ],
  };

  const mockSession = {
    id: "duo-session-456",
    workspace: "D:/ws_test",
    task_description: "Implement JWT validation",
    status: "running",
    current_round: 1,
    max_rounds: 3,
    generator: { provider: "ollama", model: "qwen2.5-coder:7b" },
    critic: { provider: "anthropic", model: "claude-3-5-sonnet" },
    rounds: [
      {
        round_number: 1,
        generator_output: "def validate_token(token): pass",
        proposal_id: "prop-1",
        critic_verdict: {
          approved: false,
          issues: [
            { description: "Missing expiration check", severity: "high", suggested_fix: "Verify exp claim" },
          ],
          reasoning: "The token validator does not verify exp claim.",
        },
        created_at: "2026-08-26T20:00:00Z",
      },
    ],
    created_at: "2026-08-26T20:00:00Z",
  };

  beforeEach(() => {
    vi.restoreAllMocks();

    useBackendStore.setState({
      status: "connected",
    });

    useWorkspaceStore.setState({
      currentWorkspace: { path: "D:/ws_test", name: "test_ws", is_current: true },
      activeWorkspaces: [{ path: "D:/ws_test", name: "test_ws", is_current: true }],
      restrictedMode: false,
    });

    useSettingsStore.setState({
      settings: {
        "editor.fontSize": "14",
        "editor.tabSize": "2",
        "terminal.fontFamily": "JetBrains Mono",
      },
    });

    useAIStore.setState({
      preset: "ollama",
      model: "qwen2.5-coder:7b",
      models: [{ name: "qwen2.5-coder:7b", provider: "ollama" }],
    });

    vi.spyOn(api, "get").mockImplementation((url: string) => {
      const u = String(url);
      if (u === "/api/settings") {
        return Promise.resolve([
          { key: "editor.fontSize", value: "14" },
          { key: "terminal.fontFamily", value: "JetBrains Mono" },
        ]);
      }
      if (u.includes("/api/settings/api-keys")) {
        return Promise.resolve([{ provider_id: "openai", configured: true }]);
      }
      if (u.includes("/api/terminal/toolchains")) {
        return Promise.resolve({ toolchains: [{ id: "python", name: "Python", available: true }] });
      }
      if (u.includes("/api/approvals/history")) {
        return Promise.resolve([]);
      }
      if (u.includes("/api/ai/chat-agent/activity-log")) {
        return Promise.resolve({ entries: [] });
      }
      if (u.includes("/api/duo/sessions/duo-session-456")) {
        return Promise.resolve(mockSession);
      }
      if (u.includes("/api/duo/sessions")) {
        return Promise.resolve([mockSession]);
      }
      if (u.includes("/api/agents/jobs/job-1")) {
        return Promise.resolve(mockDetailedJob);
      }
      if (u.includes("/api/agents/jobs")) {
        return Promise.resolve([mockDetailedJob]);
      }
      return Promise.resolve({});
    });

    vi.spyOn(api, "post").mockResolvedValue({});
  });

  describe("<SettingsModal /> Navigation & Category Rendering", () => {
    it("navigates through all settings categories cleanly", async () => {
      const onClose = vi.fn();
      render(<SettingsModal isOpen={true} onClose={onClose} />);

      expect(screen.getByRole("heading", { name: /^settings$/i })).toBeDefined();

      const categories = [
        "Providers & Models",
        "Editor",
        "Terminal",
        "Toolchains & Runtimes",
        "Git & Source Control",
        "Agents & Approval Memory",
        "Activity Timeline",
        "Theme & Palette",
        "Security & Privacy",
        "About",
      ];

      for (const cat of categories) {
        const catBtn = screen.getByRole("button", { name: new RegExp(cat, "i") });
        fireEvent.click(catBtn);
        await waitFor(() => {
          expect(catBtn).toBeDefined();
        });
      }

      const closeBtn = screen.getByTitle("Close Settings (Esc)");
      fireEvent.click(closeBtn);
      expect(onClose).toHaveBeenCalled();
    });
  });

  describe("<DuoPanel /> Orchestration & Actions", () => {
    it("renders initial form and initiates Duo session", async () => {
      vi.spyOn(api, "get").mockImplementation((url: string) => {
        if (String(url).includes("/api/duo/sessions")) return Promise.resolve([]);
        return Promise.resolve({});
      });

      const postSpy = vi.spyOn(api, "post").mockResolvedValue({
        id: "duo-session-123",
        status: "running",
        task_description: "Fix memory leak in websocket server",
        rounds: [],
      });

      render(<DuoPanel />);

      const taskInput = screen.getByPlaceholderText(/Define the primary objective/i);
      fireEvent.change(taskInput, { target: { value: "Fix memory leak in websocket server" } });

      const startBtn = screen.getByRole("button", { name: /launch duo loop/i });
      fireEvent.click(startBtn);

      await waitFor(() => {
        expect(postSpy).toHaveBeenCalledWith("/api/duo/sessions", expect.objectContaining({
          workspace: "D:/ws_test",
          task_description: "Fix memory leak in websocket server",
        }));
      });
    });

    it("displays active session rounds and critic verdict", async () => {
      render(<DuoPanel />);

      await waitFor(() => {
        expect(screen.getByText(/def validate_token/i)).toBeDefined();
        expect(screen.getByText(/Missing expiration check/i)).toBeDefined();
      });
    });
  });

  describe("<AgentConsole /> Monitoring", () => {
    it("renders running agent jobs with tasks breakdown", async () => {
      render(<AgentConsole />);

      await waitFor(() => {
        expect(screen.getByText(/Extract token check/i)).toBeDefined();
      });
    });
  });
});

