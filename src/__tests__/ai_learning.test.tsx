import React from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { AgentMemoryPanel } from "../features/memory/AgentMemoryPanel";
import { useMemoryStore } from "../features/memory/memoryStore";
import { useWorkspaceStore } from "../stores/workspaceStore";

// Mock api
vi.mock("../lib/api", () => ({
  api: {
    get: vi.fn(),
    post: vi.fn(),
    delete: vi.fn(),
  },
}));

import { api } from "../lib/api";

describe("AI Learns from Mistakes — Frontend Suite", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useMemoryStore.getState().reset();
    useWorkspaceStore.setState({
      currentWorkspace: { path: "D:/TestWorkspace", name: "TestWorkspace" } as any,
    });
  });

  it("test_renders_memory_panel_with_empty_state", async () => {
    (api.get as any).mockResolvedValueOnce([]);

    render(<AgentMemoryPanel />);

    expect(screen.getByText(/Agent Memory & Feedback/i)).toBeTruthy();
    expect(screen.getByText(/Self-Improving/i)).toBeTruthy();

    await waitFor(() => {
      expect(screen.getByText(/No mistakes or lessons recorded yet/i)).toBeTruthy();
    });
  });

  it("test_displays_loaded_memories_with_badges_and_confidence", async () => {
    const mockMemories = [
      {
        id: "mem-1",
        workspace: "D:/TestWorkspace",
        category: "failed_test",
        lesson: "Always mock network calls in unit tests to prevent timeouts.",
        raw_event: "TimeoutError in test_api",
        confidence: 90,
        times_applied: 4,
        created_at: new Date().toISOString(),
      },
      {
        id: "mem-2",
        workspace: "D:/TestWorkspace",
        category: "rejected_edit",
        lesson: "Never modify protected files in automation loops.",
        confidence: 85,
        times_applied: 1,
        created_at: new Date().toISOString(),
      },
    ];

    (api.get as any).mockResolvedValueOnce(mockMemories);

    render(<AgentMemoryPanel />);

    await waitFor(() => {
      expect(screen.getByText(/Always mock network calls in unit tests/i)).toBeTruthy();
      expect(screen.getByText(/Never modify protected files in automation loops/i)).toBeTruthy();
    });

    expect(screen.getByText("90% conf")).toBeTruthy();
    expect(screen.getByText("Applied 4x")).toBeTruthy();
    expect(screen.getByText("Applied 1x")).toBeTruthy();
  });

  it("test_teach_agent_adds_manual_memory", async () => {
    (api.get as any).mockResolvedValueOnce([]);

    const newMem = {
      id: "mem-new-1",
      workspace: "D:/TestWorkspace",
      category: "manual",
      lesson: "Always validate request schemas with Pydantic.",
      confidence: 100,
      times_applied: 0,
      created_at: new Date().toISOString(),
    };

    (api.post as any).mockResolvedValueOnce(newMem);

    render(<AgentMemoryPanel />);

    const input = screen.getByPlaceholderText(/Always use parameterized queries/i);
    fireEvent.change(input, {
      target: { value: "Always validate request schemas with Pydantic." },
    });

    const submitBtn = screen.getByRole("button", { name: /Save to Memory/i });
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith("/api/memories", {
        workspace: "D:/TestWorkspace",
        lesson: "Always validate request schemas with Pydantic.",
        category: "manual",
        confidence: 100,
      });
    });

    await waitFor(() => {
      expect(screen.getByText(/Always validate request schemas with Pydantic/i)).toBeTruthy();
    });
  });

  it("test_filter_by_category_and_search", async () => {
    const mockMemories = [
      {
        id: "mem-1",
        workspace: "D:/TestWorkspace",
        category: "failed_test",
        lesson: "Always mock network calls in unit tests.",
        confidence: 90,
        times_applied: 2,
      },
      {
        id: "mem-2",
        workspace: "D:/TestWorkspace",
        category: "security_fix",
        lesson: "Always sanitize SVG uploads to prevent stored XSS.",
        confidence: 95,
        times_applied: 5,
      },
    ];

    (api.get as any).mockResolvedValueOnce(mockMemories);

    render(<AgentMemoryPanel />);

    await waitFor(() => {
      expect(screen.getByText(/Always mock network calls/i)).toBeTruthy();
      expect(screen.getByText(/Always sanitize SVG uploads/i)).toBeTruthy();
    });

    // Filter by Security Fix category pill
    const secPill = screen.getByRole("button", { name: /Security Fix/i });
    fireEvent.click(secPill);

    await waitFor(() => {
      expect(screen.queryByText(/Always mock network calls/i)).toBeNull();
      expect(screen.getByText(/Always sanitize SVG uploads/i)).toBeTruthy();
    });

    // Reset category to all
    const allPill = screen.getByRole("button", { name: /All Memories/i });
    fireEvent.click(allPill);

    // Search query
    const searchInput = screen.getByPlaceholderText(/Search lessons or mistakes/i);
    fireEvent.change(searchInput, { target: { value: "mock" } });

    await waitFor(() => {
      expect(screen.getByText(/Always mock network calls/i)).toBeTruthy();
      expect(screen.queryByText(/Always sanitize SVG uploads/i)).toBeNull();
    });
  });

  it("test_boost_and_forget_memory_actions", async () => {
    const mockMemories = [
      {
        id: "mem-boost-1",
        workspace: "D:/TestWorkspace",
        category: "manual",
        lesson: "Always format code before committing.",
        confidence: 70,
        times_applied: 1,
      },
    ];

    (api.get as any).mockResolvedValueOnce(mockMemories);
    (api.post as any).mockResolvedValueOnce({
      ...mockMemories[0],
      confidence: 80,
    });
    (api.delete as any).mockResolvedValueOnce({ success: true });

    render(<AgentMemoryPanel />);

    await waitFor(() => {
      expect(screen.getByText("70% conf")).toBeTruthy();
    });

    // Click Boost
    const boostBtn = screen.getByRole("button", { name: /Boost/i });
    fireEvent.click(boostBtn);

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith("/api/memories/mem-boost-1/boost", { amount: 10 });
    });

    await waitFor(() => {
      expect(screen.getByText("80% conf")).toBeTruthy();
    });

    // Click Forget
    const forgetBtn = screen.getByRole("button", { name: /Forget/i });
    fireEvent.click(forgetBtn);

    await waitFor(() => {
      expect(api.delete).toHaveBeenCalledWith("/api/memories/mem-boost-1");
    });

    await waitFor(() => {
      expect(screen.queryByText(/Always format code before committing/i)).toBeNull();
    });
  });
});
