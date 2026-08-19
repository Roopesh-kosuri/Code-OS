import { useEffect, useState } from "react";
import {
  Gauge,
  Cpu,
  Activity,
  Coins,
  Puzzle,
  Terminal,
  RefreshCw,
  Plus,
  ShieldCheck,
  Check,
  Power,
  Server,
  Layers,
  Search,
  Download,
  Loader2,
  AlertCircle,
} from "lucide-react";
import { api } from "../../lib/api";
import { useBackendStore } from "../../stores/backendStore";

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
  author?: string;
  entry?: string;
  permissions?: string[];
  enabled: boolean;
};

type MCPServerItem = {
  id: string;
  name: string;
  command: string;
  args?: string[];
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
  const [error, setError] = useState<string | null>(null);

  const fetchAll = async () => {
    if (useBackendStore.getState().status !== "connected") return;
    try {
      const [metricsData, pluginsData, mcpData] = await Promise.allSettled([
        api.get<DiagnosticsData>("/api/diagnostics/metrics"),
        api.get<PluginItem[]>("/api/plugins"),
        api.get<MCPServerItem[]>("/api/mcp/servers"),
      ]);

      if (metricsData.status === "fulfilled" && metricsData.value) {
        setMetrics(metricsData.value);
      }
      if (pluginsData.status === "fulfilled" && Array.isArray(pluginsData.value)) {
        setPlugins(pluginsData.value);
      }
      if (mcpData.status === "fulfilled" && Array.isArray(mcpData.value)) {
        setMcpServers(mcpData.value);
      }
    } catch (err: any) {
      setError(err?.message || "Failed to poll system metrics.");
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
    setError(null);
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
    } catch {
      setPlugins((prev) =>
        prev.map((p) => (p.id === pluginId ? { ...p, enabled: !currentlyEnabled } : p))
      );
    }
  };

  const handleInstallPlugin = async () => {
    if (!newPluginId.trim()) return;
    setLoading(true);
    try {
      await api.post("/api/plugins/install", { plugin_id: newPluginId.trim().toLowerCase() });
      setNewPluginId("");
      await fetchAll();
    } catch (err: any) {
      setError(err?.message || "Failed to install plugin");
    } finally {
      setLoading(false);
    }
  };

  const handleToggleMcp = async (serverId: string, currentlyEnabled: boolean) => {
    try {
      await api.post(`/api/mcp/servers/${serverId}/toggle`, { enabled: !currentlyEnabled });
      await fetchAll();
    } catch {
      setMcpServers((prev) =>
        prev.map((s) => (s.id === serverId ? { ...s, enabled: !currentlyEnabled, running: !currentlyEnabled } : s))
      );
    }
  };

  return (
    <main className="flex-1 overflow-y-auto bg-background p-6 font-ui-label-reg text-ui-label-reg text-on-surface antialiased select-none">
      <div className="max-w-6xl mx-auto flex flex-col gap-6 pb-12">
        {/* ── Section Header ──────────────────────────────────────────────── */}
        <div className="flex items-center justify-between mt-2">
          <div>
            <h1 className="font-headline-md text-headline-md text-on-surface font-bold tracking-tight">
              System Metrics
            </h1>
            <p className="font-caption text-caption text-on-surface-variant mt-0.5">
              Live hardware diagnostics, AI inference telemetry, and MCP integration status.
            </p>
          </div>
          <button
            onClick={() => void handleRefresh()}
            className="flex items-center gap-2 px-4 py-2 rounded-full bg-surface-container-high hover:bg-surface-variant border border-outline-variant/30 text-on-surface-variant hover:text-on-surface transition-all cursor-pointer shadow-sm"
          >
            <RefreshCw size={14} className={refreshing ? "animate-spin text-primary-container" : ""} />
            <span className="font-ui-label-bold text-ui-label-bold text-xs">Live Update</span>
          </button>
        </div>

        {error && (
          <div className="rounded-xl border border-error/40 bg-error/10 p-3 text-xs text-error flex items-center gap-2">
            <AlertCircle size={16} />
            <span>{error}</span>
          </div>
        )}

        {/* ── 3-Card Metrics Row (Real Data / Clean Empty State) ───────────── */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          {/* CPU Usage Card */}
          <div className="bg-surface-container-low rounded-xl p-6 flex flex-col relative overflow-hidden group border border-surface-container-high shadow-lg">
            <div className="flex justify-between items-start z-10">
              <span className="font-ui-label-bold text-ui-label-bold text-on-surface-variant uppercase tracking-wider text-xs">
                CPU Usage
              </span>
              <span className="material-symbols-outlined text-primary-container/60 text-[22px]">
                memory
              </span>
            </div>
            <div className="mt-4 z-10">
              <div className="flex items-baseline gap-2">
                <span className="font-display-lg text-display-lg text-primary-container font-black">
                  {metrics ? `${metrics.system.cpu_usage_percent.toFixed(1)}%` : "--"}
                </span>
                <span className="font-code-sm text-code-sm text-on-surface-variant">
                  {metrics ? `${metrics.system.active_threads} threads` : "connecting…"}
                </span>
              </div>
            </div>
            {/* Sparkline Chart SVG */}
            <div className="absolute bottom-0 left-0 w-full h-16 opacity-40 group-hover:opacity-80 transition-opacity duration-500 pointer-events-none">
              <svg className="w-full h-full stroke-primary-container fill-primary-container/10" preserveAspectRatio="none" viewBox="0 0 100 30">
                <path d="M0,30 L0,20 C10,15 20,25 30,18 C40,11 50,22 60,15 C70,8 80,18 90,10 L100,5 L100,30 Z" strokeLinejoin="round" strokeWidth="1.5" />
              </svg>
            </div>
          </div>

          {/* Memory Allocation Card */}
          <div className="bg-surface-container-low rounded-xl p-6 flex flex-col justify-between border border-surface-container-high shadow-lg">
            <div className="flex justify-between items-start">
              <span className="font-ui-label-bold text-ui-label-bold text-on-surface-variant uppercase tracking-wider text-xs">
                Memory Allocation
              </span>
              <span className="font-ui-label-bold text-ui-label-bold text-secondary">
                {metrics ? `${metrics.system.memory_usage_percent.toFixed(1)}%` : "--"}
              </span>
            </div>
            <div className="mt-4">
              <div className="font-code-main text-code-main text-on-surface mb-3 flex items-end gap-1 font-bold">
                <span className="text-2xl font-bold">
                  {metrics ? (metrics.system.memory_used_mb / 1024).toFixed(1) : "--"}
                </span>{" "}
                GB{" "}
                <span className="text-on-surface-variant text-sm font-normal">
                  / {metrics ? (metrics.system.memory_total_mb / 1024).toFixed(1) : "--"} GB
                </span>
              </div>
              {/* Progress Bar */}
              <div className="w-full h-2 bg-surface-container-highest rounded-full overflow-hidden">
                <div
                  className="h-full bg-secondary-container rounded-full relative transition-all duration-500 shadow-[0_0_8px_rgba(0,218,243,0.3)]"
                  style={{ width: `${metrics ? metrics.system.memory_usage_percent : 0}%` }}
                >
                  <div className="absolute inset-0 bg-white/20 w-full animate-pulse rounded-full" />
                </div>
              </div>
            </div>
          </div>

          {/* LLM Throughput Card */}
          <div className="bg-surface-container-low rounded-xl p-6 flex flex-col justify-between border border-primary-container/20 shadow-[0_0_20px_rgba(0,218,243,0.08)]">
            <div className="flex justify-between items-start">
              <span className="font-ui-label-bold text-ui-label-bold text-on-surface-variant uppercase tracking-wider text-xs">
                LLM Telemetry
              </span>
              <div className="px-2.5 py-0.5 rounded-full bg-primary-container/10 border border-primary-container/30 flex items-center gap-1.5">
                <div className={`w-1.5 h-1.5 rounded-full ${metrics ? "bg-primary-container animate-pulse" : "bg-outline"}`} />
                <span className="text-[10px] font-bold text-primary-container tracking-wider">
                  {metrics ? `${metrics.ai.total_requests} REQUESTS` : "STANDBY"}
                </span>
              </div>
            </div>
            <div className="mt-4">
              <div className="flex items-baseline gap-2 mb-2">
                <span className="font-display-lg text-display-lg text-on-surface font-black">
                  {metrics ? metrics.ai.total_tokens.toLocaleString() : "--"}
                </span>
                <span className="font-code-sm text-code-sm text-on-surface-variant">total tokens</span>
              </div>
              <div className="flex items-center gap-6 border-t border-outline-variant/30 pt-3 mt-2">
                <div className="flex flex-col">
                  <span className="text-[10px] text-on-surface-variant uppercase tracking-wider mb-0.5">Latency</span>
                  <span className="font-code-sm text-code-sm text-on-surface font-semibold">
                    {metrics ? `${(metrics.ai.average_latency_sec * 1000).toFixed(0)}ms` : "--"}
                  </span>
                </div>
                <div className="flex flex-col">
                  <span className="text-[10px] text-on-surface-variant uppercase tracking-wider mb-0.5">Est. Cost</span>
                  <span className="font-code-sm text-code-sm text-primary font-semibold">
                    {metrics ? `$${metrics.ai.estimated_cost_usd.toFixed(4)}` : "$0.0000"}
                  </span>
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* ── Model Context Protocol (MCP) Section ──────────────────────────── */}
        <div className="mt-4">
          <h2 className="font-headline-md text-headline-md text-on-surface mb-4 tracking-tight flex items-center gap-2 font-bold">
            <span className="material-symbols-outlined text-[22px] text-primary-container">hub</span>
            <span>Model Context Protocol (MCP)</span>
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {mcpServers.map((server) => (
              <div
                key={server.id}
                onClick={() => void handleToggleMcp(server.id, server.enabled)}
                className="bg-surface-container-low rounded-xl p-4 border border-outline-variant/20 flex items-center justify-between hover:bg-surface-variant/40 transition-colors cursor-pointer group shadow-md"
              >
                <div className="flex items-center gap-4">
                  <div className="w-10 h-10 rounded-lg bg-surface-container-highest flex items-center justify-center border border-outline-variant/30">
                    <span className="material-symbols-outlined text-on-surface-variant text-[20px]">
                      {server.id === "filesystem" ? "folder" : "merge_type"}
                    </span>
                  </div>
                  <div className="flex flex-col">
                    <div className="flex items-center gap-2">
                      <span className="font-ui-label-bold text-ui-label-bold text-on-surface">{server.name}</span>
                      <div
                        className={`w-2 h-2 rounded-full ${server.running ? "bg-primary-container shadow-[0_0_8px_rgba(0,218,243,0.8)]" : "bg-outline-variant"}`}
                        title={server.running ? "Connected" : "Disconnected"}
                      />
                    </div>
                    <span className="font-code-sm text-code-sm text-on-surface-variant font-mono text-[11px]">{server.command}</span>
                  </div>
                </div>

                {/* Custom Toggle Switch */}
                <div className={`w-11 h-6 rounded-full transition-colors relative p-0.5 border ${server.enabled ? "bg-primary-container border-primary-container" : "bg-surface-container-highest border-outline-variant/40"}`}>
                  <div className={`w-4 h-4 rounded-full bg-surface-dim transition-transform duration-200 ${server.enabled ? "translate-x-5" : "translate-x-0.5"} mt-0.5`} />
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* ── Plugins & Extensions Section ─────────────────────────────────── */}
        <div className="mt-4 border-t border-outline-variant/20 pt-6">
          <div className="flex items-center justify-between mb-4">
            <h2 className="font-headline-md text-headline-md text-on-surface tracking-tight flex items-center gap-2 font-bold">
              <span className="material-symbols-outlined text-[22px] text-primary-container">extension</span>
              <span>Plugins &amp; Extensions</span>
            </h2>
          </div>

          <div className="bg-surface-container-low rounded-xl p-6 border border-outline-variant/20 shadow-lg">
            <div className="flex gap-4 items-center">
              <div className="relative flex-1 group">
                <span className="material-symbols-outlined absolute left-3.5 top-1/2 -translate-y-1/2 text-on-surface-variant text-[20px] z-10 group-focus-within:text-primary-container transition-colors">
                  search
                </span>
                <input
                  type="text"
                  value={newPluginId}
                  onChange={(e) => setNewPluginId(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && void handleInstallPlugin()}
                  className="w-full bg-[#1e1f24] text-on-surface font-ui-label-reg text-ui-label-reg rounded-lg pl-11 pr-4 py-3 outline-none border border-transparent focus:border-primary-container/50 focus:ring-1 focus:ring-primary-container focus:shadow-[0_0_12px_rgba(0,218,243,0.2)] transition-all placeholder:text-on-surface-variant/50"
                  placeholder="Search marketplace or enter plugin ID (e.g. linter_ruff)..."
                />
              </div>
              <button
                onClick={() => void handleInstallPlugin()}
                disabled={loading || !newPluginId.trim()}
                className="bg-primary-container hover:bg-primary-fixed text-[#001f24] font-ui-label-bold text-ui-label-bold px-6 py-3 rounded-full flex items-center gap-2 transition-all disabled:opacity-40 cursor-pointer shadow-md"
              >
                <Download size={15} />
                <span>{loading ? "Installing..." : "Install"}</span>
              </button>
            </div>

            {/* Suggested tag chips */}
            <div className="mt-4 flex flex-wrap gap-2 items-center">
              <span className="font-code-sm text-code-sm text-on-surface-variant mr-1">Suggested:</span>
              {["docker_provider", "vercel_deploy", "aws_toolkit", "pyright_sast", "tailwind_intellisense"].map((tag) => (
                <button
                  key={tag}
                  onClick={() => setNewPluginId(tag)}
                  className="px-3 py-1 rounded-lg bg-surface-container-high border border-outline-variant/30 text-on-surface font-code-sm text-code-sm hover:border-primary-container/50 hover:text-primary transition-colors cursor-pointer"
                >
                  {tag}
                </button>
              ))}
            </div>

            {/* Installed Plugin List */}
            {plugins.length > 0 ? (
              <div className="mt-6 border-t border-surface-variant pt-4 space-y-3">
                <h3 className="font-caption text-caption text-on-surface-variant uppercase tracking-wider">
                  Installed Extensions ({plugins.length})
                </h3>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                  {plugins.map((p) => (
                    <div key={p.id} className="bg-[#1e1f24] rounded-lg p-3 border border-white/5 flex items-center justify-between">
                      <div>
                        <div className="flex items-center gap-2">
                          <span className="font-ui-label-bold text-ui-label-bold text-on-surface">{p.name}</span>
                          <span className="font-mono text-[10px] bg-white/5 px-1.5 py-0.5 rounded text-outline-variant">v{p.version}</span>
                        </div>
                        <p className="font-caption text-caption text-on-surface-variant mt-0.5 line-clamp-1">{p.description}</p>
                      </div>
                      <button
                        onClick={() => void handleTogglePlugin(p.id, p.enabled)}
                        className={`w-10 h-5 rounded-full transition-colors relative p-0.5 ${p.enabled ? "bg-primary-container" : "bg-surface-container-highest"}`}
                      >
                        <div className={`w-4 h-4 rounded-full bg-surface-dim transition-transform ${p.enabled ? "translate-x-5" : "translate-x-0"}`} />
                      </button>
                    </div>
                  ))}
                </div>
              </div>
            ) : null}
          </div>
        </div>
      </div>
    </main>
  );
}
