import React, { useState, useEffect, useCallback } from "react";
import {
  Server,
  Plus,
  Trash2,
  RotateCw,
  Eye,
  Terminal,
  Check,
  AlertCircle,
  Play,
  Square,
  ChevronDown,
  ChevronRight,
  ShieldAlert,
  ShieldCheck,
  Globe,
  Settings,
  X,
  FileCode,
  Search,
  FolderSearch,
  Github,
  Command,
  Activity,
  Cpu,
  RefreshCw,
  Info,
} from "lucide-react";
import { api } from "../../lib/api";

export interface MCPServerDto {
  id: string;
  name: string;
  type: "stdio" | "http";
  status: "running" | "stopped" | "crashed" | "starting" | "error";
  enabled: boolean;
  restart_count: number;
  tool_count: number;
  error?: string | null;
  command: string;
  args: string[];
  env: Record<string, string>;
  url?: string | null;
  auto_approve_read_only: boolean;
}

export interface MCPToolDto {
  server_id: string;
  name: string;
  namespaced_name: string;
  description: string;
  input_schema: Record<string, any>;
  read_only: boolean;
}

export function McpServersSection() {
  const [servers, setServers] = useState<MCPServerDto[]>([]);
  const [loading, setLoading] = useState(false);
  const [activeModal, setActiveModal] = useState<"add" | "edit" | "logs" | "tools" | "scan" | null>(null);
  const [selectedServer, setSelectedServer] = useState<MCPServerDto | null>(null);
  const [serverTools, setServerTools] = useState<MCPToolDto[]>([]);
  const [serverLogs, setServerLogs] = useState<string[]>([]);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [restartingIds, setRestartingIds] = useState<Record<string, boolean>>({});

  // Form State for Add / Edit
  const [formId, setFormId] = useState("");
  const [formName, setFormName] = useState("");
  const [formType, setFormType] = useState<"stdio" | "http">("stdio");
  const [formCommand, setFormCommand] = useState("");
  const [formArgs, setFormArgs] = useState("");
  const [formUrl, setFormUrl] = useState("");
  const [formEnv, setFormEnv] = useState<Array<{ key: string; value: string }>>([{ key: "", value: "" }]);
  const [formAutoApprove, setFormAutoApprove] = useState(true);

  // Scanner State
  const [scanType, setScanType] = useState<"command_spec" | "github" | "json_file" | "workspace">("command_spec");
  const [scanTarget, setScanTarget] = useState("");
  const [scanLoading, setScanLoading] = useState(false);
  const [discoveredServers, setDiscoveredServers] = useState<MCPServerDto[]>([]);

  const showFeedback = (msg: string) => {
    setFeedback(msg);
    setTimeout(() => setFeedback(null), 3500);
  };

  const fetchServers = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.get<MCPServerDto[]>("/api/mcp/servers");
      if (Array.isArray(res)) {
        setServers(res);
      }
    } catch {
      // fallback
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchServers();
  }, [fetchServers]);

  const handleToggle = async (server: MCPServerDto) => {
    const nextEnabled = !server.enabled;
    // Optimistic UI update
    setServers((prev) =>
      prev.map((s) =>
        s.id === server.id
          ? { ...s, enabled: nextEnabled, status: nextEnabled ? "starting" : "stopped" }
          : s
      )
    );

    try {
      await api.post<{ status: string; enabled: boolean; server_status: string; error?: string }>(
        `/api/mcp/servers/${server.id}/toggle`,
        { enabled: nextEnabled }
      );
      showFeedback(`MCP Server '${server.name}' ${nextEnabled ? "started" : "stopped"}`);
      await fetchServers();
    } catch (e: any) {
      showFeedback(`Failed to toggle server: ${e?.message || "Error"}`);
      await fetchServers();
    }
  };

  const handleRestart = async (server: MCPServerDto) => {
    setRestartingIds((prev) => ({ ...prev, [server.id]: true }));
    try {
      await api.post(`/api/mcp/servers/${server.id}/restart`);
      showFeedback(`Restarted '${server.name}'`);
      await fetchServers();
    } catch (e: any) {
      showFeedback(`Failed to restart: ${e?.message || "Error"}`);
    } finally {
      setTimeout(() => {
        setRestartingIds((prev) => ({ ...prev, [server.id]: false }));
      }, 600);
    }
  };

  const handleDelete = async (server: MCPServerDto) => {
    if (!confirm(`Are you sure you want to remove MCP server '${server.name}'?`)) return;
    try {
      await api.delete(`/api/mcp/servers/${server.id}`);
      showFeedback(`Removed '${server.name}'`);
      await fetchServers();
    } catch (e: any) {
      showFeedback(`Failed to remove server: ${e?.message || "Error"}`);
    }
  };

  const openAddModal = () => {
    setFormId("");
    setFormName("");
    setFormType("stdio");
    setFormCommand("npx");
    setFormArgs("-y @modelcontextprotocol/server-filesystem");
    setFormUrl("");
    setFormEnv([{ key: "", value: "" }]);
    setFormAutoApprove(true);
    setSelectedServer(null);
    setActiveModal("add");
  };

  const openEditModal = (server: MCPServerDto) => {
    setSelectedServer(server);
    setFormId(server.id);
    setFormName(server.name);
    setFormType(server.type);
    setFormCommand(server.command || "");
    setFormArgs((server.args || []).join(" "));
    setFormUrl(server.url || "");
    const envList = Object.entries(server.env || {}).map(([k, v]) => ({ key: k, value: v }));
    setFormEnv(envList.length > 0 ? envList : [{ key: "", value: "" }]);
    setFormAutoApprove(server.auto_approve_read_only);
    setActiveModal("edit");
  };

  const handleSaveForm = async (e: React.FormEvent) => {
    e.preventDefault();
    const id = formId.trim() || formName.trim().toLowerCase().replace(/\s+/g, "_");
    if (!id || !formName.trim()) {
      alert("Please provide a name and valid server ID.");
      return;
    }

    const envMap: Record<string, string> = {};
    for (const pair of formEnv) {
      if (pair.key.trim()) {
        envMap[pair.key.trim()] = pair.value;
      }
    }

    const payload = {
      id,
      name: formName.trim(),
      type: formType,
      command: formType === "stdio" ? formCommand.trim() : "",
      args: formType === "stdio" ? formArgs.trim().split(/\s+/).filter(Boolean) : [],
      env: envMap,
      url: formType === "http" ? formUrl.trim() : null,
      enabled: true,
      auto_approve_read_only: formAutoApprove,
    };

    try {
      await api.post("/api/mcp/servers", payload);
      showFeedback(`MCP Server '${formName}' configured`);
      setActiveModal(null);
      await fetchServers();
    } catch (err: any) {
      alert(`Failed to save server: ${err?.message || "Error"}`);
    }
  };

  const handleRunScan = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!scanTarget.trim()) return;
    setScanLoading(true);
    setDiscoveredServers([]);
    try {
      const res = await api.post<MCPServerDto[]>("/api/mcp/scan", {
        source_type: scanType,
        target: scanTarget.trim(),
      });
      setDiscoveredServers(Array.isArray(res) ? res : []);
      if (!res || res.length === 0) {
        showFeedback("No MCP servers found in source.");
      }
    } catch (err: any) {
      alert(`Scan failed: ${err?.message || "Error"}`);
    } finally {
      setScanLoading(false);
    }
  };

  const addDiscoveredServer = async (discovered: MCPServerDto) => {
    try {
      await api.post("/api/mcp/servers", {
        ...discovered,
        enabled: true,
      });
      showFeedback(`Server '${discovered.name}' added`);
      setDiscoveredServers(discoveredServers.filter((s) => s.id !== discovered.id));
      await fetchServers();
    } catch (err: any) {
      alert(`Failed to add server: ${err?.message || "Error"}`);
    }
  };

  const viewTools = async (server: MCPServerDto) => {
    setSelectedServer(server);
    setActiveModal("tools");
    try {
      const res = await api.get<MCPToolDto[]>(`/api/mcp/servers/${server.id}/tools`);
      setServerTools(Array.isArray(res) ? res : []);
    } catch {
      setServerTools([]);
    }
  };

  const viewLogs = async (server: MCPServerDto) => {
    setSelectedServer(server);
    setActiveModal("logs");
    try {
      const res = await api.get<{ logs: string[] }>(`/api/mcp/servers/${server.id}/logs`);
      setServerLogs(res?.logs || []);
    } catch {
      setServerLogs([]);
    }
  };

  return (
    <div className="space-y-6 select-none max-w-4xl" data-testid="mcp-servers-section">
      {/* Header Banner */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-4 border-b border-white/10">
        <div className="space-y-1">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-lg bg-cyan-500/10 border border-cyan-500/30 flex items-center justify-center text-cyan-400 shadow-[0_0_15px_rgba(6,182,212,0.15)]">
              <Server size={18} />
            </div>
            <div>
              <h3 className="text-base font-semibold text-white tracking-tight flex items-center gap-2">
                Model Context Protocol (MCP)
                <span className="text-[10px] px-2 py-0.5 rounded-full font-mono font-normal bg-cyan-500/10 border border-cyan-500/30 text-cyan-300">
                  v2024-11-05
                </span>
              </h3>
            </div>
          </div>
          <p className="text-xs text-neutral-400 pl-10.5 leading-relaxed">
            Connect local stdio and remote HTTP MCP servers to dynamically expose real tools, filesystems, and databases to the Rony Agent.
          </p>
        </div>

        <div className="flex items-center gap-2.5 shrink-0 pl-10.5 sm:pl-0">
          <button
            onClick={() => {
              setDiscoveredServers([]);
              setScanTarget("");
              setActiveModal("scan");
            }}
            data-testid="scan-mcp-btn"
            className="h-9 px-3.5 rounded-xl bg-white/[0.04] hover:bg-white/[0.08] border border-white/10 hover:border-white/20 text-neutral-300 hover:text-white text-xs font-mono flex items-center gap-2 transition-all cursor-pointer"
          >
            <FolderSearch size={14} className="text-cyan-400" />
            <span>Scan Sources</span>
          </button>

          <button
            onClick={openAddModal}
            data-testid="add-mcp-server-btn"
            className="h-9 px-4 rounded-xl bg-gradient-to-r from-cyan-500 to-teal-400 hover:from-cyan-400 hover:to-teal-300 text-[#001b22] font-semibold text-xs flex items-center gap-2 transition-all cursor-pointer shadow-[0_0_20px_rgba(6,182,212,0.25)] hover:shadow-[0_0_25px_rgba(6,182,212,0.4)]"
          >
            <Plus size={15} strokeWidth={2.5} />
            <span>Add MCP Server</span>
          </button>
        </div>
      </div>

      {/* Floating Alert Feedback */}
      {feedback && (
        <div className="p-3 rounded-xl bg-cyan-950/40 border border-cyan-500/30 text-xs text-cyan-300 font-mono flex items-center gap-2.5 shadow-lg animate-fade-in backdrop-blur-md">
          <Check size={15} className="text-cyan-400 shrink-0" />
          <span>{feedback}</span>
        </div>
      )}

      {/* Server List */}
      {servers.length === 0 ? (
        <div className="text-center py-14 border border-dashed border-white/10 rounded-2xl bg-white/[0.01]">
          <Server size={36} className="mx-auto text-neutral-600 mb-3" />
          <h4 className="text-sm font-medium text-neutral-300">No MCP Servers Configured</h4>
          <p className="text-xs text-neutral-500 mt-1 max-w-sm mx-auto">
            Click "Add MCP Server" to configure a local filesystem, database, or Git MCP server.
          </p>
        </div>
      ) : (
        <div className="space-y-3.5">
          {servers.map((server) => {
            const isRunning = server.status === "running";
            const isError = server.status === "error" || server.status === "crashed";
            const isStarting = server.status === "starting";
            const isRestarting = restartingIds[server.id] || false;

            return (
              <div
                key={server.id}
                data-testid={`mcp-server-card-${server.id}`}
                className={`p-4 sm:p-5 rounded-2xl border transition-all backdrop-blur-md ${
                  isRunning
                    ? "bg-[#10131d]/90 border-cyan-500/20 shadow-[0_4px_20px_rgba(0,0,0,0.3)] hover:border-cyan-500/40"
                    : isError
                    ? "bg-[#181116]/90 border-rose-500/20 shadow-[0_4px_20px_rgba(0,0,0,0.3)] hover:border-rose-500/40"
                    : "bg-[#111219]/80 border-white/[0.08] hover:border-white/15"
                }`}
              >
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
                  {/* Left Side: Status Dot, Name, Transport, Command */}
                  <div className="flex items-start sm:items-center gap-3.5 min-w-0">
                    {/* Status Orb Badge */}
                    <div className="mt-1 sm:mt-0 relative flex items-center justify-center shrink-0">
                      <div
                        className={`w-3 h-3 rounded-full transition-all ${
                          isRunning
                            ? "bg-emerald-400 shadow-[0_0_12px_rgba(52,211,153,0.8)]"
                            : isError
                            ? "bg-rose-500 shadow-[0_0_12px_rgba(244,63,94,0.8)]"
                            : isStarting
                            ? "bg-amber-400 animate-ping"
                            : "bg-neutral-600"
                        }`}
                      />
                      {isRunning && (
                        <div className="absolute w-5 h-5 rounded-full bg-emerald-400/20 animate-pulse" />
                      )}
                    </div>

                    <div className="min-w-0 space-y-1.5">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="text-sm font-semibold text-white tracking-wide">
                          {server.name}
                        </span>

                        {/* Status Label Pill */}
                        <span
                          className={`text-[10px] px-2 py-0.5 rounded-full font-mono uppercase font-medium border ${
                            isRunning
                              ? "bg-emerald-500/10 border-emerald-500/30 text-emerald-300"
                              : isError
                              ? "bg-rose-500/10 border-rose-500/30 text-rose-300"
                              : isStarting
                              ? "bg-amber-500/10 border-amber-500/30 text-amber-300"
                              : "bg-neutral-800/80 border-neutral-700/50 text-neutral-400"
                          }`}
                        >
                          {server.status}
                        </span>

                        <span className="text-[10px] px-2 py-0.5 rounded-md font-mono uppercase font-medium bg-cyan-500/10 text-cyan-400 border border-cyan-500/20">
                          {server.type}
                        </span>

                        <span className="text-[11px] font-mono text-neutral-500">
                          id: {server.id}
                        </span>

                        {server.auto_approve_read_only && (
                          <span
                            title="Auto-Approve Read-Only Tools Enabled"
                            className="flex items-center gap-1 text-[10px] font-mono text-emerald-400/80 bg-emerald-500/5 px-1.5 py-0.5 rounded"
                          >
                            <ShieldCheck size={11} />
                            <span>auto-read</span>
                          </span>
                        )}
                      </div>

                      {/* Command / URL preview */}
                      <div className="flex items-center gap-2">
                        <div className="text-[11.5px] font-mono text-neutral-400 bg-black/40 border border-white/5 px-2.5 py-1 rounded-lg truncate max-w-md select-all">
                          {server.type === "stdio"
                            ? `${server.command} ${(server.args || []).join(" ")}`
                            : server.url}
                        </div>
                      </div>
                    </div>
                  </div>

                  {/* Right Side: Action Buttons & Modern Toggle Switch */}
                  <div className="flex items-center gap-2 shrink-0 self-end sm:self-center pt-2 sm:pt-0 border-t sm:border-t-0 border-white/5 w-full sm:w-auto justify-end">
                    {/* View Tools */}
                    <button
                      onClick={() => void viewTools(server)}
                      className="h-8 px-2.5 rounded-lg bg-white/[0.04] hover:bg-white/[0.08] border border-white/10 hover:border-white/20 text-neutral-300 hover:text-white text-xs font-mono flex items-center gap-1.5 cursor-pointer transition-colors"
                      title="View Discovered Tools"
                    >
                      <Eye size={13} className="text-cyan-400" />
                      <span>Tools ({server.tool_count})</span>
                    </button>

                    {/* View Logs */}
                    <button
                      onClick={() => void viewLogs(server)}
                      className="h-8 px-2.5 rounded-lg bg-white/[0.04] hover:bg-white/[0.08] border border-white/10 hover:border-white/20 text-neutral-300 hover:text-white text-xs font-mono flex items-center gap-1.5 cursor-pointer transition-colors"
                      title="View Raw Logs"
                    >
                      <Terminal size={13} className="text-amber-400" />
                      <span>Logs</span>
                    </button>

                    {/* Restart Button */}
                    <button
                      onClick={() => void handleRestart(server)}
                      disabled={isRestarting}
                      className="w-8 h-8 rounded-lg bg-white/[0.04] hover:bg-white/[0.08] border border-white/10 hover:border-white/20 text-neutral-300 hover:text-white flex items-center justify-center cursor-pointer transition-colors"
                      title="Restart Server"
                    >
                      <RotateCw
                        size={13}
                        className={isRestarting ? "animate-spin text-cyan-400" : ""}
                      />
                    </button>

                    {/* Edit Config */}
                    <button
                      onClick={() => openEditModal(server)}
                      className="w-8 h-8 rounded-lg bg-white/[0.04] hover:bg-white/[0.08] border border-white/10 hover:border-white/20 text-neutral-300 hover:text-white flex items-center justify-center cursor-pointer transition-colors"
                      title="Edit Configuration"
                    >
                      <Settings size={13} />
                    </button>

                    {/* Delete */}
                    <button
                      onClick={() => void handleDelete(server)}
                      className="w-8 h-8 rounded-lg bg-rose-500/10 hover:bg-rose-500/20 border border-rose-500/20 text-rose-400 flex items-center justify-center cursor-pointer transition-colors"
                      title="Delete Server"
                    >
                      <Trash2 size={13} />
                    </button>

                    {/* Modern Custom Toggle Switch Button */}
                    <div className="pl-2 border-l border-white/10 flex items-center">
                      <button
                        type="button"
                        role="switch"
                        aria-checked={server.enabled}
                        onClick={() => void handleToggle(server)}
                        className={`relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none ${
                          server.enabled
                            ? "bg-cyan-500 shadow-[0_0_12px_rgba(6,182,212,0.5)]"
                            : "bg-neutral-800 hover:bg-neutral-700"
                        }`}
                        title={server.enabled ? "Turn Off Server" : "Turn On Server"}
                      >
                        <span
                          className={`pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow-lg ring-0 transition duration-200 ease-in-out ${
                            server.enabled ? "translate-x-5" : "translate-x-0"
                          }`}
                        />
                      </button>
                    </div>
                  </div>
                </div>

                {/* Subprocess Error Banner */}
                {server.error && (
                  <div className="mt-3 p-3 rounded-xl bg-rose-950/30 border border-rose-500/30 text-xs font-mono text-rose-300 flex items-start gap-2.5">
                    <AlertCircle size={15} className="text-rose-400 shrink-0 mt-0.5" />
                    <div className="flex-1 min-w-0">
                      <div className="font-semibold text-rose-200">Execution Error</div>
                      <div className="text-[11px] text-rose-300/80 mt-0.5 break-all select-text">{server.error}</div>
                    </div>
                    <button
                      onClick={() => void handleRestart(server)}
                      className="px-2 py-1 rounded bg-rose-500/20 hover:bg-rose-500/30 text-[11px] text-rose-200 font-semibold cursor-pointer shrink-0 transition-colors"
                    >
                      Retry
                    </button>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* Discovery Scanner Modal */}
      {activeModal === "scan" && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 backdrop-blur-md p-4 animate-fade-in">
          <div className="w-full max-w-xl rounded-2xl border border-white/15 bg-[#12141c] p-6 shadow-2xl space-y-5">
            <div className="flex items-center justify-between pb-3.5 border-b border-white/10">
              <h3 className="text-sm font-bold text-white flex items-center gap-2">
                <FolderSearch size={17} className="text-cyan-400" />
                Scan Sources for MCP Servers
              </h3>
              <button
                onClick={() => setActiveModal(null)}
                className="w-7 h-7 rounded-lg hover:bg-white/10 text-neutral-400 hover:text-white flex items-center justify-center transition-colors cursor-pointer"
              >
                <X size={16} />
              </button>
            </div>

            <form onSubmit={handleRunScan} className="space-y-4 text-xs font-mono">
              <div className="flex flex-wrap gap-2 border-b border-white/10 pb-3">
                {[
                  { id: "command_spec", label: "Command Spec", icon: Command },
                  { id: "github", label: "GitHub Repo", icon: Github },
                  { id: "json_file", label: "JSON File", icon: FileCode },
                  { id: "workspace", label: "Workspace .mcp.json", icon: FolderSearch },
                ].map((item) => {
                  const Icon = item.icon;
                  const isActive = scanType === item.id;
                  return (
                    <button
                      key={item.id}
                      type="button"
                      onClick={() => setScanType(item.id as any)}
                      className={`px-3 py-1.5 rounded-xl flex items-center gap-1.5 transition-all cursor-pointer text-[11px] ${
                        isActive
                          ? "bg-cyan-500 text-[#001b22] font-bold shadow-[0_0_12px_rgba(6,182,212,0.3)]"
                          : "bg-white/[0.03] text-neutral-400 hover:text-white hover:bg-white/[0.07] border border-white/5"
                      }`}
                    >
                      <Icon size={13} />
                      <span>{item.label}</span>
                    </button>
                  );
                })}
              </div>

              <div>
                <label className="text-neutral-400 block mb-1.5 text-[11px]">
                  {scanType === "command_spec" && "Command Spec (e.g. Postgres:npx -y @modelcontextprotocol/server-postgres ...)"}
                  {scanType === "github" && "GitHub Repository URL (e.g. https://github.com/modelcontextprotocol/servers)"}
                  {scanType === "json_file" && "Absolute Path to Claude / Cursor JSON File"}
                  {scanType === "workspace" && "Workspace Directory Path"}
                </label>
                <div className="flex gap-2">
                  <input
                    required
                    value={scanTarget}
                    onChange={(e) => setScanTarget(e.target.value)}
                    placeholder={
                      scanType === "command_spec"
                        ? "Postgres:npx -y @modelcontextprotocol/server-postgres"
                        : scanType === "github"
                        ? "https://github.com/modelcontextprotocol/servers"
                        : "C:\\path\\to\\.mcp.json"
                    }
                    className="flex-1 h-9 rounded-xl bg-black/50 border border-white/15 px-3 text-white focus:outline-none focus:border-cyan-400 font-mono text-xs transition-colors"
                  />
                  <button
                    type="submit"
                    disabled={scanLoading}
                    className="h-9 px-4 rounded-xl bg-gradient-to-r from-cyan-500 to-teal-400 hover:from-cyan-400 hover:to-teal-300 text-[#001b22] font-bold cursor-pointer transition-all disabled:opacity-50"
                  >
                    {scanLoading ? "Scanning..." : "Scan"}
                  </button>
                </div>
              </div>

              {/* Discovered Server Proposals */}
              {discoveredServers.length > 0 && (
                <div className="space-y-2.5 pt-3 border-t border-white/10">
                  <div className="text-[11px] font-bold text-cyan-400 flex items-center gap-1.5">
                    <Check size={13} />
                    <span>Discovered {discoveredServers.length} MCP Server Configuration(s):</span>
                  </div>
                  <div className="max-h-56 overflow-y-auto space-y-2 pr-1">
                    {discoveredServers.map((disc) => (
                      <div
                        key={disc.id}
                        className="p-3.5 rounded-xl bg-[#181a24] border border-white/10 flex items-center justify-between gap-3 shadow-md"
                      >
                        <div className="min-w-0 space-y-0.5">
                          <div className="font-bold text-white text-xs">{disc.name}</div>
                          <div className="text-[10.5px] text-neutral-400 font-mono truncate max-w-sm select-all">
                            {disc.type === "stdio" ? `${disc.command} ${disc.args.join(" ")}` : disc.url}
                          </div>
                        </div>

                        <button
                          type="button"
                          onClick={() => void addDiscoveredServer(disc)}
                          className="h-7 px-3 rounded-lg bg-cyan-500/20 hover:bg-cyan-500/30 text-cyan-300 border border-cyan-500/40 font-bold text-[11px] cursor-pointer transition-colors shrink-0"
                        >
                          Add to Config
                        </button>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </form>
          </div>
        </div>
      )}

      {/* Add / Edit Server Modal */}
      {(activeModal === "add" || activeModal === "edit") && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 backdrop-blur-md p-4 animate-fade-in">
          <div className="w-full max-w-lg rounded-2xl border border-white/15 bg-[#12141c] p-6 shadow-2xl space-y-5">
            <div className="flex items-center justify-between pb-3.5 border-b border-white/10">
              <h3 className="text-sm font-bold text-white flex items-center gap-2">
                <Server size={17} className="text-cyan-400" />
                {activeModal === "add" ? "Add MCP Server" : "Edit MCP Server"}
              </h3>
              <button
                onClick={() => setActiveModal(null)}
                className="w-7 h-7 rounded-lg hover:bg-white/10 text-neutral-400 hover:text-white flex items-center justify-center transition-colors cursor-pointer"
              >
                <X size={16} />
              </button>
            </div>

            <form onSubmit={handleSaveForm} className="space-y-4 text-xs font-mono">
              <div className="grid grid-cols-2 gap-3.5">
                <div>
                  <label className="text-neutral-400 block mb-1 text-[11px]">Server Name</label>
                  <input
                    required
                    value={formName}
                    onChange={(e) => setFormName(e.target.value)}
                    placeholder="e.g. Postgres MCP"
                    className="w-full h-9 rounded-xl bg-black/50 border border-white/15 px-3 text-white focus:outline-none focus:border-cyan-400 text-xs"
                  />
                </div>

                <div>
                  <label className="text-neutral-400 block mb-1 text-[11px]">Server ID</label>
                  <input
                    required
                    disabled={activeModal === "edit"}
                    value={formId}
                    onChange={(e) => setFormId(e.target.value)}
                    placeholder="e.g. postgres"
                    className="w-full h-9 rounded-xl bg-black/50 border border-white/15 px-3 text-white focus:outline-none focus:border-cyan-400 text-xs disabled:opacity-50"
                  />
                </div>
              </div>

              <div>
                <label className="text-neutral-400 block mb-1.5 text-[11px]">Transport Type</label>
                <div className="flex gap-4 p-2 rounded-xl bg-black/30 border border-white/5">
                  <label className="flex items-center gap-2 cursor-pointer text-white">
                    <input
                      type="radio"
                      name="transport_type"
                      value="stdio"
                      checked={formType === "stdio"}
                      onChange={() => setFormType("stdio")}
                      className="accent-cyan-400"
                    />
                    <span>stdio (local subprocess)</span>
                  </label>
                  <label className="flex items-center gap-2 cursor-pointer text-white">
                    <input
                      type="radio"
                      name="transport_type"
                      value="http"
                      checked={formType === "http"}
                      onChange={() => setFormType("http")}
                      className="accent-cyan-400"
                    />
                    <span>HTTP / URL</span>
                  </label>
                </div>
              </div>

              {formType === "stdio" ? (
                <>
                  <div className="grid grid-cols-3 gap-3.5">
                    <div>
                      <label className="text-neutral-400 block mb-1 text-[11px]">Command</label>
                      <input
                        required
                        value={formCommand}
                        onChange={(e) => setFormCommand(e.target.value)}
                        placeholder="npx / uvx / python"
                        className="w-full h-9 rounded-xl bg-black/50 border border-white/15 px-3 text-white focus:outline-none focus:border-cyan-400 text-xs"
                      />
                    </div>
                    <div className="col-span-2">
                      <label className="text-neutral-400 block mb-1 text-[11px]">Arguments</label>
                      <input
                        value={formArgs}
                        onChange={(e) => setFormArgs(e.target.value)}
                        placeholder="-y @modelcontextprotocol/server-postgres ..."
                        className="w-full h-9 rounded-xl bg-black/50 border border-white/15 px-3 text-white focus:outline-none focus:border-cyan-400 text-xs"
                      />
                    </div>
                  </div>

                  {/* Isolated Env Vars Editor */}
                  <div className="space-y-1.5">
                    <div className="flex items-center justify-between">
                      <label className="text-neutral-400 text-[11px]">Environment Variables (Isolated)</label>
                      <button
                        type="button"
                        onClick={() => setFormEnv([...formEnv, { key: "", value: "" }])}
                        className="text-[10.5px] text-cyan-400 hover:underline cursor-pointer"
                      >
                        + Add Variable
                      </button>
                    </div>
                    <div className="space-y-1.5 max-h-28 overflow-y-auto pr-1">
                      {formEnv.map((item, idx) => (
                        <div key={idx} className="flex gap-2 items-center">
                          <input
                            placeholder="KEY"
                            value={item.key}
                            onChange={(e) => {
                              const updated = [...formEnv];
                              updated[idx].key = e.target.value;
                              setFormEnv(updated);
                            }}
                            className="w-1/2 h-8 rounded-lg bg-black/50 border border-white/15 px-2.5 text-white text-[11px]"
                          />
                          <input
                            placeholder="VALUE"
                            value={item.value}
                            onChange={(e) => {
                              const updated = [...formEnv];
                              updated[idx].value = e.target.value;
                              setFormEnv(updated);
                            }}
                            className="w-1/2 h-8 rounded-lg bg-black/50 border border-white/15 px-2.5 text-white text-[11px]"
                          />
                          <button
                            type="button"
                            onClick={() => setFormEnv(formEnv.filter((_, i) => i !== idx))}
                            className="text-neutral-500 hover:text-rose-400 p-1 cursor-pointer"
                          >
                            <X size={13} />
                          </button>
                        </div>
                      ))}
                    </div>
                  </div>
                </>
              ) : (
                <div>
                  <label className="text-neutral-400 block mb-1 text-[11px]">Server URL</label>
                  <input
                    required
                    value={formUrl}
                    onChange={(e) => setFormUrl(e.target.value)}
                    placeholder="http://localhost:3000/mcp"
                    className="w-full h-9 rounded-xl bg-black/50 border border-white/15 px-3 text-white focus:outline-none focus:border-cyan-400 text-xs"
                  />
                </div>
              )}

              <div className="p-3.5 rounded-xl bg-black/30 border border-white/10 flex items-center justify-between">
                <div>
                  <div className="text-xs font-semibold text-white">Auto-Approve Read-Only Tools</div>
                  <div className="text-[10px] text-neutral-400">
                    Execute safe read tools without approval cards. Mutating tools still require approval.
                  </div>
                </div>
                <input
                  type="checkbox"
                  checked={formAutoApprove}
                  onChange={(e) => setFormAutoApprove(e.target.checked)}
                  className="w-4 h-4 accent-cyan-400 rounded cursor-pointer"
                />
              </div>

              <div className="flex justify-end gap-2.5 pt-3 border-t border-white/10">
                <button
                  type="button"
                  onClick={() => setActiveModal(null)}
                  className="h-9 px-4 rounded-xl text-neutral-400 hover:text-white hover:bg-white/5 cursor-pointer transition-colors"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="h-9 px-5 rounded-xl bg-gradient-to-r from-cyan-500 to-teal-400 hover:from-cyan-400 hover:to-teal-300 text-[#001b22] font-semibold cursor-pointer shadow-md"
                >
                  Save Server
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Discovered Tools Modal */}
      {activeModal === "tools" && selectedServer && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 backdrop-blur-md p-4 animate-fade-in">
          <div className="w-full max-w-xl rounded-2xl border border-white/15 bg-[#12141c] p-6 shadow-2xl space-y-4">
            <div className="flex items-center justify-between pb-3.5 border-b border-white/10">
              <h3 className="text-sm font-bold text-white flex items-center gap-2">
                <FileCode size={17} className="text-cyan-400" />
                Tools for '{selectedServer.name}' ({serverTools.length})
              </h3>
              <button
                onClick={() => setActiveModal(null)}
                className="w-7 h-7 rounded-lg hover:bg-white/10 text-neutral-400 hover:text-white flex items-center justify-center transition-colors cursor-pointer"
              >
                <X size={16} />
              </button>
            </div>

            <div className="max-h-96 overflow-y-auto space-y-2.5 font-mono text-xs pr-1">
              {serverTools.length === 0 ? (
                <div className="text-center py-10 text-neutral-500">No tools discovered from this server yet. Ensure the server is turned on.</div>
              ) : (
                serverTools.map((tool) => (
                  <div key={tool.name} className="p-3.5 rounded-xl bg-[#181a24] border border-white/10 space-y-1.5 shadow-md">
                    <div className="flex items-center justify-between">
                      <span className="font-bold text-cyan-300">{tool.namespaced_name}</span>
                      <span
                        className={`text-[10px] px-2 py-0.5 rounded-full font-mono uppercase font-semibold border ${
                          tool.read_only
                            ? "bg-emerald-500/10 border-emerald-500/30 text-emerald-400"
                            : "bg-amber-500/10 border-amber-500/30 text-amber-400"
                        }`}
                      >
                        {tool.read_only ? "Read-Only" : "Mutating"}
                      </span>
                    </div>
                    <p className="text-neutral-400 text-[11px] font-sans leading-relaxed">{tool.description || "No description provided."}</p>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      )}

      {/* Raw Logs Viewer Modal */}
      {activeModal === "logs" && selectedServer && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 backdrop-blur-md p-4 animate-fade-in">
          <div className="w-full max-w-2xl rounded-2xl border border-white/15 bg-[#12141c] p-6 shadow-2xl space-y-4">
            <div className="flex items-center justify-between pb-3.5 border-b border-white/10">
              <h3 className="text-sm font-bold text-white flex items-center gap-2">
                <Terminal size={17} className="text-cyan-400" />
                Logs: '{selectedServer.name}' (Last 200 lines)
              </h3>
              <button
                onClick={() => setActiveModal(null)}
                className="w-7 h-7 rounded-lg hover:bg-white/10 text-neutral-400 hover:text-white flex items-center justify-center transition-colors cursor-pointer"
              >
                <X size={16} />
              </button>
            </div>

            <div className="h-80 overflow-y-auto p-4 rounded-xl bg-[#08090d] border border-white/10 font-mono text-[11px] text-neutral-300 space-y-1 select-text">
              {serverLogs.length === 0 ? (
                <div className="text-neutral-600">No logs captured yet.</div>
              ) : (
                serverLogs.map((log, idx) => <div key={idx} className="break-all leading-tight">{log}</div>)
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
