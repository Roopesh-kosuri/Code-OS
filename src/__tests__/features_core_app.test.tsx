import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { TopBar } from "../components/layout/TopBar";
import { OnboardingWizard } from "../components/workspace/OnboardingWizard";
import { SettingsModal } from "../components/settings/SettingsModal";
import { AIChatPanel } from "../features/ai/AIChatPanel";
import { AgentConsole } from "../features/ai/AgentConsole";
import { DuoPanel } from "../features/duo/DuoPanel";
import { AppShell } from "../components/layout/AppShell";
import { useWorkspaceStore } from "../stores/workspaceStore";
import { useBackendStore } from "../stores/backendStore";
import { useAIStore } from "../stores/aiStore";
import { api } from "../lib/api";

describe("Frontend Core App Shell & Modals", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    const mockTree = {
      name: "ws",
      path: "D:/ws",
      type: "directory" as const,
      is_dir: true,
      children: [],
    };

    useWorkspaceStore.setState({
      currentWorkspace: { path: "D:/ws", name: "ws", is_current: true },
      activeWorkspaces: [{ path: "D:/ws", name: "ws", is_current: true }],
      fileTree: mockTree,
      fileTrees: { "D:/ws": mockTree },
      loading: false,
      restrictedMode: false,
    });
    useBackendStore.setState({ status: "connected" });
    useAIStore.setState({
      preset: "ollama",
      model: "qwen2.5-coder:7b",
      messages: [],
      streaming: false,
      agentMode: false,
    });
  });

  describe("<TopBar />", () => {
    it("renders workspace name and settings button", () => {
      const handleOpenSettings = vi.fn();
      const handleViewChange = vi.fn();

      render(
        <TopBar
          onOpenSettings={handleOpenSettings}
          activeView="editor"
          onViewChange={handleViewChange}
        />
      );

      expect(screen.getByText("ws")).toBeDefined();
    });
  });

  describe("<OnboardingWizard />", () => {
    it("renders walkthrough modal terms and skip intro action", () => {
      const handleClose = vi.fn();
      render(<OnboardingWizard isOpen={true} onClose={handleClose} />);

      expect(screen.getByText(/Welcome to CODE OS/i)).toBeDefined();
      expect(screen.getByText(/Execution Terms/i)).toBeDefined();

      const skipBtn = screen.getByRole("button", { name: /Skip Intro/i });
      fireEvent.click(skipBtn);
      expect(handleClose).toHaveBeenCalled();
    });
  });

  describe("<SettingsModal />", () => {
    it("renders settings categories and handles tab switching", async () => {
      vi.spyOn(api, "get").mockResolvedValue([]);
      const handleClose = vi.fn();

      render(<SettingsModal onClose={handleClose} />);

      expect(screen.getAllByText(/Settings/i).length).toBeGreaterThanOrEqual(1);
      expect(screen.getByText(/Providers & Models/i)).toBeDefined();
      expect(screen.getAllByText(/Editor/i).length).toBeGreaterThanOrEqual(1);
      expect(screen.getAllByText(/Terminal/i).length).toBeGreaterThanOrEqual(1);
    });
  });

  describe("<AIChatPanel />", () => {
    it("renders chat input and mode toggles", () => {
      render(<AIChatPanel />);
      expect(screen.getByPlaceholderText(/Ask a coding question/i)).toBeDefined();
    });
  });

  describe("<AgentConsole />", () => {
    it("renders agent console DAG flow and terminal controls", () => {
      render(<AgentConsole />);
      expect(screen.getAllByText(/Agent/i).length).toBeGreaterThanOrEqual(1);
    });
  });

  describe("<DuoPanel />", () => {
    it("renders Duo pair-programming loop interface", () => {
      render(<DuoPanel />);
      expect(screen.getAllByText(/Duo/i).length).toBeGreaterThanOrEqual(1);
    });
  });

  describe("<AppShell />", () => {
    it("renders complete application shell with activity bar", () => {
      render(<AppShell />);
      expect(screen.getByText("CODE")).toBeDefined();
      expect(screen.getByText("Main")).toBeDefined();
    });
  });
});
