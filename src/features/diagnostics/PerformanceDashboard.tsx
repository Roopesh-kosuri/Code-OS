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
    <section className="flex h-full min-h-0 w-full min-w-0 flex-col border-b border-surface-700 bg-surface-900 text-slate-100">
      {/* Title Bar */}
      <div className="flex h-[38px] shrink-0 items-center justify-between border-b border-surface-700 px-3">
        <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-slate-400">
          <Gauge size={15} />
          Diagnostics & Extensions
        </div>
        <button
          onClick={handleRefresh}
          className={`text-slate-400 hover:text-white transition-colors ${refreshing ? "animate-spin" : ""}`}
          title="Refresh Metrics"
        >
          <RefreshCw size={14} />
        </button>
      </div>

      {/* Main Content Area - Scrollable */}
      <div className="flex-1 min-h-0 overflow-y-auto p-3 space-y-5 text-sm">
        {/* System Telemetry */}
        <div>
          <div className="mb-2.5 flex items-center gap-2 text-xs font-bold uppercase tracking-wider text-slate-400">
            <Cpu size={14} />
            System Metrics
          </div>
          {metrics?.system ? (
            <div className="grid grid-cols-2 gap-2 bg-surface-850 p-2.5 rounded-lg border border-surface-750">
              <div className="flex flex-col">
                <span className="text-[11px] text-slate-400">CPU Usage</span>
                <span className="text-base font-semibold text-accent-400">
                  {metrics.system.cpu_usage_percent}%
                </span>
              </div>
              <div className="flex flex-col">
                <span className="text-[11px] text-slate-400">Memory Usage</span>
                <span className="text-base font-semibold text-accent-400">
                  {metrics.system.memory_usage_percent}%
                </span>
              </div>
              <div className="flex flex-col col-span-2 pt-1.5 border-t border-surface-700 mt-1">
                <span className="text-[10px] text-slate-400">Memory Detail</span>
                <span className="text-xs font-medium text-slate-300">
                  {metrics.system.memory_used_mb.toFixed(0)} MB / {metrics.system.memory_total_mb.toFixed(0)} MB
                </span>
              </div>
              <div className="flex flex-col pt-1.5 border-t border-surface-700 mt-1">
                <span className="text-[10px] text-slate-400">Active Threads</span>
                <span className="text-xs font-medium text-slate-300">
                  {metrics.system.active_threads}
                </span>
              </div>
              <div className="flex flex-col pt-1.5 border-t border-surface-700 mt-1">
                <span className="text-[10px] text-slate-400">Agent Workers</span>
                <span className="text-xs font-medium text-slate-300">
                  {metrics.system.active_agent_jobs} active
                </span>
              </div>
            </div>
          ) : (
            <div className="text-xs text-slate-500 py-2">Loading system telemetry...</div>
          )}
        </div>

        {/* AI Analytics & Costs */}
        <div>
          <div className="mb-2.5 flex items-center gap-2 text-xs font-bold uppercase tracking-wider text-slate-400">
            <Coins size={14} />
            AI Execution Cost
          </div>
          {metrics?.ai ? (
            <div className="space-y-2 bg-surface-850 p-2.5 rounded-lg border border-surface-750">
              <div className="flex justify-between">
                <span className="text-xs text-slate-400">Total Tokens:</span>
                <span className="text-xs font-semibold text-slate-200">{metrics.ai.total_tokens.toLocaleString()}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-xs text-slate-400">Average Latency:</span>
                <span className="text-xs font-semibold text-slate-200">{metrics.ai.average_latency_sec}s</span>
              </div>
              <div className="flex justify-between">
                <span className="text-xs text-slate-400">API Calls:</span>
                <span className="text-xs font-semibold text-slate-200">{metrics.ai.total_requests} calls</span>
              </div>
              <div className="flex justify-between pt-1.5 border-t border-surface-700 font-bold">
                <span className="text-xs text-accent-400">Estimated Cost:</span>
                <span className="text-xs text-accent-400">${metrics.ai.estimated_cost_usd.toFixed(4)} USD</span>
              </div>
            </div>
          ) : (
            <div className="text-xs text-slate-500 py-2">Loading cost analytics...</div>
          )}
        </div>

        {/* Plugins / Marketplace */}
        <div>
          <div className="mb-2 flex items-center gap-2 text-xs font-bold uppercase tracking-wider text-slate-400">
            <Puzzle size={14} />
            Plugins & Extensions
          </div>

          {/* Mini Mock Install Form */}
          <div className="flex gap-1.5 mb-3">
            <input
              type="text"
              placeholder="e.g. linter_ruff"
              value={newPluginId}
              onChange={(e) => setNewPluginId(e.target.value)}
              className="h-8 flex-1 rounded bg-surface-850 border border-surface-700 px-2.5 text-xs text-slate-100 placeholder-slate-500 focus:outline-none focus:border-accent-500"
              disabled={loading}
            />
            <Button variant="primary" onClick={handleInstallPlugin} disabled={loading || !newPluginId.trim()}>
              <Plus size={14} />
              Install
            </Button>
          </div>

          {/* Plugin list */}
          <div className="space-y-2">
            {plugins.length === 0 ? (
              <div className="text-xs text-slate-500 italic py-1 bg-surface-850 p-2 rounded border border-surface-750">
                No extensions installed. Try installing 'linter_ruff'!
              </div>
            ) : (
              plugins.map((p) => {
                const loadTime = metrics?.plugins?.load_times_ms?.[p.id];
                return (
                  <div key={p.id} className="bg-surface-850 p-2 rounded border border-surface-750 space-y-1.5">
                    <div className="flex items-start justify-between">
                      <div>
                        <div className="text-xs font-bold text-slate-200 flex items-center gap-1.5">
                          {p.name}
                          <span className="text-[9px] bg-surface-700 px-1 rounded text-slate-400">v{p.version}</span>
                        </div>
                        <div className="text-[10px] text-slate-500">by {p.author}</div>
                      </div>
                      <button
                        onClick={() => handleTogglePlugin(p.id, p.enabled)}
                        className={`p-1 rounded transition-colors ${p.enabled ? "text-emerald-400 bg-emerald-950/30 hover:bg-emerald-900/30" : "text-slate-400 bg-surface-700 hover:bg-surface-650"}`}
                        title={p.enabled ? "Disable Plugin" : "Enable Plugin"}
                      >
                        <Power size={13} />
                      </button>
                    </div>
                    <p className="text-[11px] text-slate-400 leading-normal">{p.description}</p>
                    {loadTime !== undefined && (
                      <div className="text-[9px] text-slate-500 flex items-center gap-1">
                        <Activity size={10} />
                        Init: {loadTime}ms
                      </div>
                    )}
                  </div>
                );
              })
            )}
          </div>
        </div>

        {/* MCP Servers */}
        <div>
          <div className="mb-2.5 flex items-center gap-2 text-xs font-bold uppercase tracking-wider text-slate-400">
            <Terminal size={14} />
            Model Context Protocol
          </div>
          <div className="space-y-2">
            {mcpServers.map((s) => (
              <div key={s.id} className="flex items-center justify-between bg-surface-850 p-2 rounded border border-surface-750">
                <div className="flex flex-col">
                  <span className="text-xs font-bold text-slate-200 flex items-center gap-2">
                    {s.name}
                    <span className={`h-1.5 w-1.5 rounded-full ${s.running ? "bg-emerald-400 animate-pulse" : "bg-red-400"}`} />
                  </span>
                  <span className="text-[10px] text-slate-500 font-mono">
                    {s.command} {s.args[0]}...
                  </span>
                </div>
                <label className="relative inline-flex items-center cursor-pointer">
                  <input
                    type="checkbox"
                    checked={s.enabled}
                    onChange={() => handleToggleMcp(s.id, s.enabled)}
                    className="sr-only peer"
                  />
                  <div className="w-8 h-4 bg-surface-750 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-slate-300 after:border-slate-350 after:border after:rounded-full after:h-3 after:w-3 after:transition-all peer-checked:bg-accent-600 peer-checked:after:bg-white"></div>
                </label>
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
