import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import React from "react";
import { McpServersSection } from "../components/settings/McpServersSection";
import { api } from "../lib/api";

describe("Phase 4: MCP Settings UI", () => {
  const mockServers = [
    {
      id: "filesystem",
      name: "Filesystem MCP",
      type: "stdio",
      status: "running",
      enabled: true,
      restart_count: 0,
      tool_count: 5,
      command: "npx",
      args: ["-y", "@modelcontextprotocol/server-filesystem"],
      env: {},
      url: null,
      auto_approve_read_only: true,
    },
    {
      id: "postgres",
      name: "Postgres Database",
      type: "http",
      status: "stopped",
      enabled: false,
      restart_count: 0,
      tool_count: 0,
      command: "",
      args: [],
      env: { PG_USER: "admin" },
      url: "http://localhost:5432/mcp",
      auto_approve_read_only: false,
    },
  ];

  beforeEach(() => {
    vi.restoreAllMocks();
    vi.spyOn(api, "get").mockImplementation((url: string) => {
      if (url === "/api/mcp/servers") return Promise.resolve(mockServers);
      if (url.includes("/tools")) {
        return Promise.resolve([
          {
            server_id: "filesystem",
            name: "read_file",
            namespaced_name: "mcp__filesystem__read_file",
            description: "Read a file from disk",
            input_schema: {},
            read_only: true,
          },
          {
            server_id: "filesystem",
            name: "write_file",
            namespaced_name: "mcp__filesystem__write_file",
            description: "Write content to a file",
            input_schema: {},
            read_only: false,
          },
        ]);
      }
      if (url.includes("/logs")) {
        return Promise.resolve({
          server_id: "filesystem",
          logs: ["[12:00:00] Server started", "[12:00:01] Tools registered"],
        });
      }
      return Promise.resolve([]);
    });

    vi.spyOn(api, "post").mockResolvedValue({ status: "ok" });
    vi.spyOn(api, "delete").mockResolvedValue({ status: "ok" });
  });

  it("renders MCP servers list with status badges and server cards", async () => {
    render(<McpServersSection />);

    await waitFor(() => {
      expect(screen.getByText("Filesystem MCP")).toBeTruthy();
      expect(screen.getByText("Postgres Database")).toBeTruthy();
    });

    expect(screen.getByText("id: filesystem")).toBeTruthy();
    expect(screen.getByText("Tools (5)")).toBeTruthy();
  });

  it("opens add server modal and submits new stdio server config", async () => {
    const postSpy = vi.spyOn(api, "post");
    render(<McpServersSection />);

    const addBtn = screen.getByTestId("add-mcp-server-btn");
    fireEvent.click(addBtn);

    expect(screen.getAllByText("Add MCP Server").length).toBeGreaterThanOrEqual(1);

    const nameInput = screen.getByPlaceholderText("e.g. Postgres MCP");
    fireEvent.change(nameInput, { target: { value: "Custom Git Server" } });

    const idInput = screen.getByPlaceholderText("e.g. postgres");
    fireEvent.change(idInput, { target: { value: "custom_git" } });

    const saveBtn = screen.getByText("Save Server");
    fireEvent.click(saveBtn);

    await waitFor(() => {
      expect(postSpy).toHaveBeenCalledWith(
        "/api/mcp/servers",
        expect.objectContaining({
          id: "custom_git",
          name: "Custom Git Server",
          type: "stdio",
        })
      );
    });
  });

  it("restarts an MCP server and triggers restart endpoint", async () => {
    const postSpy = vi.spyOn(api, "post");
    render(<McpServersSection />);

    await waitFor(() => {
      expect(screen.getByText("Filesystem MCP")).toBeTruthy();
    });

    const restartBtns = screen.getAllByTitle("Restart Server");
    fireEvent.click(restartBtns[0]);

    await waitFor(() => {
      expect(postSpy).toHaveBeenCalledWith("/api/mcp/servers/filesystem/restart");
    });
  });

  it("opens discovered tools modal and renders namespaced tools", async () => {
    render(<McpServersSection />);

    await waitFor(() => {
      expect(screen.getByText("Tools (5)")).toBeTruthy();
    });

    fireEvent.click(screen.getByText("Tools (5)"));

    await waitFor(() => {
      expect(screen.getByText("mcp__filesystem__read_file")).toBeTruthy();
      expect(screen.getByText("Read-Only")).toBeTruthy();
      expect(screen.getByText("mcp__filesystem__write_file")).toBeTruthy();
      expect(screen.getByText("Mutating")).toBeTruthy();
    });
  });

  it("opens raw logs modal and renders recent log lines", async () => {
    render(<McpServersSection />);

    await waitFor(() => {
      expect(screen.getByText("Filesystem MCP")).toBeTruthy();
    });

    const logsBtns = screen.getAllByTitle("View Raw Logs");
    fireEvent.click(logsBtns[0]);

    await waitFor(() => {
      expect(screen.getByText("[12:00:00] Server started")).toBeTruthy();
      expect(screen.getByText("[12:00:01] Tools registered")).toBeTruthy();
    });
  });
});
