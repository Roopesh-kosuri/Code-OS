import { useEffect, useState } from "react";
import { Gauge, Cpu, Activity, Coins, Puzzle, Terminal, RefreshCw, Plus, ShieldCheck, Check, Power } from "lucide-react";

import { Button } from "../../components/ui/Button";
import { api } from "../../lib/api";

type SystemMetrics = {
  cpu_usage_percent: number;
  memory_usage_percent: number;
  memory_used_mb: number;
  memory_total_mb: number;
  active_threads: number;
  active_agent_jobs: number;
};

type AIMetrics = {
  total_tokens: number;
  average_latency_sec: number;
  total_requests: number;
  estimated_cost_usd: number;
};

type DiagnosticsData = {
  system: SystemMetrics;
  ai: AIMetrics;
  plugins: {
    loaded_count: number;
    load_times_ms: Record<string, number>;
  };
};

type PluginItem = {
  id: string;
  name: string;
  version: string;
  description: string;
  author: string;
  entry: string;
  permissions: string[];
  enabled: boolean;
};

type MCPServerItem = {
  id: string;
  name: string;
  command: string;
  args: string[];
  enabled: boolean;
  running: boolean;
};

export function PerformanceDashboard() {
  const [metrics, setMetrics] = useState<DiagnosticsData | null>(null);
  const [plugins, setPlugins] = useState<PluginItem[]>([]);
  const [mcpServers, setMcpServers] = useState<MCPServerItem[]>([]);
  const [newPluginId, setNewPluginId] = useState("");
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);

  const fetchAll = async () => {
    try {
      const metricsData = await api.get<DiagnosticsData>("/api/diagnostics/metrics");
      setMetrics(metricsData);

      const pluginsData = await api.get<PluginItem[]>("/api/plugins");
      setPlugins(pluginsData);

      const mcpData = await api.get<MCPServerItem[]>("/api/mcp/servers");
      setMcpServers(mcpData);
    } catch (err) {
      console.error("Failed to fetch diagnostics metrics:", err);
    }
  };

  useEffect(() => {
    void fetchAll();
    const interval = setInterval(() => {
      void fetchAll();
    }, 3000);
    return () => clearInterval(interval);
  }, []);

  const handleRefresh = async () => {
    setRefreshing(true);
    await fetchAll();
    setRefreshing(false);
  };

  const handleTogglePlugin = async (pluginId: string, currentlyEnabled: boolean) => {
    try {
      if (currentlyEnabled) {
        await api.post(`/api/plugins/${pluginId}/disable`);
      } else {
        await api.post(`/api/plugins/${pluginId}/enable`);
      }
      await fetchAll();
    } catch (err) {
      console.error(`Failed to toggle plugin ${pluginId}:`, err);
    }
  };

  const handleInstallPlugin = async () => {
    if (!newPluginId.trim()) return;
    setLoading(true);
    try {
      await api.post("/api/plugins/install", { plugin_id: newPluginId.trim().toLowerCase() });
      setNewPluginId("");
      await fetchAll();
    } catch (err) {
      console.error("Failed to install marketplace plugin:", err);
      alert("Installation failed: " + (err instanceof Error ? err.message : String(err)));
    } finally {
      setLoading(false);
    }
  };

  const handleToggleMcp = async (serverId: string, currentlyEnabled: boolean) => {
    try {
      await api.post(`/api/mcp/servers/${serverId}/toggle`, { enabled: !currentlyEnabled });
      await fetchAll();
    } catch (err) {
      console.error(`Failed to toggle MCP server ${serverId}:`, err);
    }
  };

  return (
    <main className="flex-1 overflow-y-auto p-4 md:p-6 flex flex-col gap-6 bg-[#131314] text-on-surface h-full select-none">
      {/* Page Header */}
      <div className="flex justify-between items-center mb-2 pl-2">
        <h1 className="font-headline-lg text-headline-lg text-on-surface tracking-tight font-bold">System Metrics</h1>
        <button
          onClick={() => {
            setRefreshing(true);
            void fetchAll().then(() => setRefreshing(false));
          }}
          className="flex items-center gap-2 px-4 py-2 rounded-full border border-white/5 bg-surface-container-low hover:bg-surface-container-high transition-colors text-on-surface text-sm font-medium"
        >
          <span className={`material-symbols-outlined text-[18px] ${refreshing ? "animate-spin" : ""}`}>refresh</span>
          Refresh
        </button>
      </div>

      {/* Bento Grid Layout */}
      <div className="grid grid-cols-1 md:grid-cols-12 gap-4 auto-rows-[minmax(120px,auto)]">
        {/* CPU Sparkline */}
        <div className="glass-panel rounded-lg md:col-span-4 p-4 flex flex-col justify-between relative overflow-hidden group">
          <div className="flex justify-between items-start mb-2">
            <div className="flex items-center gap-2">
              <span className="material-symbols-outlined text-primary-container text-[20px]">memory</span>
              <span className="font-micro-label text-micro-label text-on-surface-variant uppercase">CPU Usage</span>
            </div>
            <span className="font-code-block text-code-block text-primary-container text-lg font-bold">
              {metrics ? `${metrics.system.cpu_usage_percent.toFixed(1)}%` : "--"}
            </span>
          </div>
          <div className="h-16 w-full mt-auto relative">
            <svg className="absolute bottom-0 w-full h-full" preserveAspectRatio="none" viewBox="0 0 100 40">
              <path d="M0 40 L0 30 L10 25 L20 35 L30 15 L40 20 L50 5 L60 25 L70 10 L80 30 L90 15 L100 20 L100 40 Z" fill="rgba(0, 229, 255, 0.1)" stroke="none" />
              <path d="M0 30 L10 25 L20 35 L30 15 L40 20 L50 5 L60 25 L70 10 L80 30 L90 15 L100 20" fill="none" stroke="#00e5ff" strokeLinejoin="round" strokeWidth="1.5" />
            </svg>
          </div>
        </div>

        {/* RAM Progress */}
        <div className="glass-panel rounded-lg md:col-span-4 p-4 flex flex-col justify-between">
          <div className="flex justify-between items-start mb-4">
            <div className="flex items-center gap-2">
              <span className="material-symbols-outlined text-secondary text-[20px]">dataset</span>
              <span className="font-micro-label text-micro-label text-on-surface-variant uppercase">Memory Allocation</span>
            </div>
            <span className="font-code-block text-code-block text-secondary text-sm font-bold">
              {metrics ? `${(metrics.system.memory_used_mb / 1024).toFixed(1)} GB / ${(metrics.system.memory_total_mb / 1024).toFixed(1)} GB` : "--"}
            </span>
          </div>
          <div className="w-full bg-surface-container-highest rounded-full h-2 mb-1 overflow-hidden relative">
            <div
              className="bg-secondary h-2 rounded-full shadow-[0_0_8px_rgba(209,188,255,0.4)] transition-all duration-500"
              style={{ width: `${metrics ? metrics.system.memory_usage_percent : 0}%` }}
            />
          </div>
          <div className="flex justify-between font-micro-label text-micro-label text-outline-variant mt-2">
            <span>Usage: {metrics ? `${metrics.system.memory_usage_percent.toFixed(1)}%` : "--"}</span>
            <span>Active Threads: {metrics ? metrics.system.active_threads : 0}</span>
          </div>
        </div>

        {/* LLM Tokens */}
        <div className="glass-panel rounded-lg md:col-span-4 p-4 flex flex-col justify-between">
          <div className="flex justify-between items-start mb-2">
            <div className="flex items-center gap-2">
              <span className="material-symbols-outlined text-tertiary-fixed-dim text-[20px]">psychology</span>
              <span className="font-micro-label text-micro-label text-on-surface-variant uppercase">LLM Throughput</span>
            </div>
            <span className="font-micro-label text-micro-label text-tertiary-fixed-dim bg-tertiary-fixed-dim/10 px-2 py-0.5 rounded">Active Session</span>
          </div>
          <div className="flex items-baseline gap-2 mt-2">
            <span className="font-headline-md text-headline-md text-on-surface font-bold text-2xl">
              {metrics ? metrics.ai.total_tokens.toLocaleString() : "0"}
            </span>
            <span className="font-body-sm text-body-sm text-outline">total tokens</span>
          </div>
          <div className="flex gap-4 mt-4 pt-4 border-t border-white/5">
            <div className="flex flex-col">
              <span className="font-micro-label text-micro-label text-outline">LATENCY</span>
              <span className="font-code-block text-code-block text-on-surface-variant">{metrics ? `${metrics.ai.average_latency_sec}s` : "--"}</span>
            </div>
            <div className="flex flex-col">
              <span className="font-micro-label text-micro-label text-outline">EST. COST</span>
              <span className="font-code-block text-code-block text-primary">${metrics ? metrics.ai.estimated_cost_usd.toFixed(4) : "0.0000"}</span>
            </div>
          </div>
        </div>

        {/* MCP Status Section */}
        <div className="md:col-span-12 mt-4 mb-2 flex items-center gap-2 pl-2">
          <span className="material-symbols-outlined text-on-surface-variant text-[18px]">account_tree</span>
          <h2 className="font-body-lg text-body-lg text-on-surface font-semibold">Model Context Protocol (MCP)</h2>
        </div>

        {mcpServers.map((server) => (
          <div key={server.id} className="glass-panel rounded-lg md:col-span-6 p-4 flex items-center justify-between border-l-2 border-l-primary-container">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-full bg-surface-container-high flex items-center justify-center shrink-0 border border-white/5">
                <span className="material-symbols-outlined text-primary-container">folder_shared</span>
              </div>
              <div>
                <h3 className="font-body-sm text-body-sm text-on-surface font-semibold">{server.name}</h3>
                <span className="font-micro-label text-micro-label text-on-surface-variant block mt-0.5 font-mono">{server.command}</span>
              </div>
            </div>
            <div className="flex items-center gap-3">
              <span className={`w-2 h-2 rounded-full ${server.running ? "bg-primary-container shadow-[0_0_8px_rgba(0,229,255,0.8)]" : "bg-outline"}`} />
              <button
                onClick={() => void handleToggleMcp(server.id, !server.enabled)}
                className={`w-10 h-5 rounded-full transition-colors relative p-0.5 ${server.enabled ? "bg-primary-container" : "bg-surface-container-highest"}`}
              >
                <div className={`w-4 h-4 rounded-full bg-surface transition-transform ${server.enabled ? "translate-x-5" : "translate-x-0"}`} />
              </button>
            </div>
          </div>
        ))}

        {/* Plugins Section */}
        <div className="md:col-span-12 mt-4 mb-2 flex items-center justify-between pl-2">
          <div className="flex items-center gap-2">
            <span className="material-symbols-outlined text-on-surface-variant text-[18px]">extension</span>
            <h2 className="font-body-lg text-body-lg text-on-surface font-semibold">Plugins & Extensions</h2>
          </div>
          <div className="flex items-center gap-2">
            <input
              type="text"
              placeholder="e.g. linter_ruff"
              value={newPluginId}
              onChange={(e) => setNewPluginId(e.target.value)}
              className="h-8 rounded bg-surface-container-lowest border border-white/10 px-3 text-xs text-on-surface focus:outline-none focus:border-primary"
            />
            <button
              onClick={() => void handleInstallPlugin()}
              disabled={loading || !newPluginId.trim()}
              className="bg-primary/10 text-primary border border-primary/30 hover:bg-primary/20 px-4 py-1.5 rounded-full font-micro-label text-micro-label uppercase font-bold"
            >
              + Install
            </button>
          </div>
        </div>

        {plugins.map((plugin) => (
          <div key={plugin.id} className="glass-panel rounded-lg md:col-span-6 p-4 flex items-center justify-between">
            <div>
              <div className="flex items-center gap-2">
                <span className="font-body-sm text-body-sm text-on-surface font-semibold">{plugin.name}</span>
                <span className="font-micro-label text-micro-label text-outline-variant bg-white/5 px-1.5 py-0.5 rounded">v{plugin.version}</span>
              </div>
              <p className="font-micro-label text-micro-label text-on-surface-variant mt-1">{plugin.description}</p>
            </div>
            <button
              onClick={() => void handleTogglePlugin(plugin.id, !plugin.enabled)}
              className={`w-10 h-5 rounded-full transition-colors relative p-0.5 ${plugin.enabled ? "bg-primary-container" : "bg-surface-container-highest"}`}
            >
              <div className={`w-4 h-4 rounded-full bg-surface transition-transform ${plugin.enabled ? "translate-x-5" : "translate-x-0"}`} />
            </button>
          </div>
        ))}
      </div>
    </main>
  );
}
