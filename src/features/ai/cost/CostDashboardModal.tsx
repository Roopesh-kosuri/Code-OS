import React, { useEffect } from "react";
import {
  X,
  Download,
  DollarSign,
  TrendingUp,
  Cpu,
  Layers,
  AlertTriangle,
  CheckCircle2,
  Sparkles,
  ShieldCheck,
  ShieldAlert,
} from "lucide-react";
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  PieChart,
  Pie,
  Cell,
  CartesianGrid,
  Legend,
} from "recharts";
import { useCostStore } from "../../../stores/costStore";
import { useWorkspaceStore } from "../../../stores/workspaceStore";

const PROVIDER_COLORS: Record<string, string> = {
  openai: "#10a37f",
  anthropic: "#d97706",
  groq: "#f97316",
  google: "#3b82f6",
  gemini: "#3b82f6",
  nvidia: "#22c55e",
  "nvidia-nim": "#22c55e",
  glm: "#8b5cf6",
  deepseek: "#06b6d4",
  moonshot: "#ec4899",
  qwen: "#a855f7",
  ollama: "#64748b",
  local: "#64748b",
  "team-agent": "#38bdf8",
  agent: "#818cf8",
};

const DEFAULT_CHART_COLOR = "#00daf3";

export function CostDashboardModal({
  isOpen,
  onClose,
}: {
  isOpen?: boolean;
  onClose?: () => void;
}) {
  const storeIsOpen = useCostStore((s) => s.isModalOpen);
  const storeCloseModal = useCostStore((s) => s.closeModal);
  const activePeriod = useCostStore((s) => s.activePeriod);
  const setActivePeriod = useCostStore((s) => s.setActivePeriod);
  const budget = useCostStore((s) => s.budget);
  const summary = useCostStore((s) => s.summary);
  const dailyBreakdown = useCostStore((s) => s.dailyBreakdown);
  const fetchBudget = useCostStore((s) => s.fetchBudget);
  const fetchSummary = useCostStore((s) => s.fetchSummary);
  const fetchBreakdown = useCostStore((s) => s.fetchBreakdown);

  const currentWorkspace = useWorkspaceStore((s) => s.currentWorkspace);

  const show = isOpen !== undefined ? isOpen : storeIsOpen;
  const handleClose = onClose || storeCloseModal;

  useEffect(() => {
    if (show) {
      const ws = currentWorkspace?.path || "";
      void fetchBudget(ws);
      void fetchSummary(activePeriod, ws);
      void fetchBreakdown(30, ws);
    }
  }, [show, activePeriod, currentWorkspace?.path]);

  if (!show) return null;

  // Provider pie chart data
  const providerPieData = Object.entries(summary.per_provider || {})
    .filter(([_, val]) => val > 0)
    .map(([prov, val]) => ({
      name: prov,
      value: Number(val.toFixed(4)),
      color: PROVIDER_COLORS[prov.toLowerCase()] || DEFAULT_CHART_COLOR,
    }))
    .sort((a, b) => b.value - a.value);

  // Top models data
  const topModels = Object.entries(summary.per_model || {})
    .map(([model, cost]) => ({ model, cost }))
    .sort((a, b) => b.cost - a.cost)
    .slice(0, 10);

  // Top provider
  const topProviderEntry = providerPieData[0];

  // Budget progress percentage
  const usagePct = budget.usage_percent || 0.0;
  const isOverBudget = usagePct >= 100;
  const isNearLimit = usagePct >= 90 && usagePct < 100;

  // Export CSV
  const handleExportCsv = () => {
    const headers = ["Job ID", "Workspace", "Provider", "Model", "Cost (USD)", "Tokens", "Timestamp"];
    const rows = (summary.per_job || []).map((j) => [
      `"${j.job_id}"`,
      `"${j.workspace || ""}"`,
      `"${j.provider}"`,
      `"${j.model}"`,
      j.cost_usd.toFixed(4),
      j.token_count,
      `"${new Date(j.timestamp * 1000).toISOString()}"`,
    ]);

    const csvContent = "data:text/csv;charset=utf-8," + [headers.join(","), ...rows.map((r) => r.join(","))].join("\n");
    const encodedUri = encodeURI(csvContent);
    const link = document.createElement("a");
    link.setAttribute("href", encodedUri);
    link.setAttribute("download", `code_os_cost_report_${new Date().toISOString().slice(0, 10)}.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Cost Dashboard & Budget Intelligence"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/85 backdrop-blur-xl p-4 sm:p-6 select-none animate-in fade-in duration-200"
    >
      <div className="relative w-full max-w-7xl h-[92vh] bg-[#0c0d12] border border-white/10 rounded-2xl shadow-2xl flex flex-col overflow-hidden text-on-surface">
        {/* ── Top Header ──────────────────────────────────────────────────────── */}
        <header className="flex items-center justify-between px-6 py-4 border-b border-white/10 bg-[#12131a]/80 shrink-0">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-primary/15 border border-primary/30 flex items-center justify-center text-primary shadow-[0_0_15px_rgba(0,218,243,0.2)]">
              <DollarSign size={22} />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h1 className="text-base font-bold text-white tracking-wide">
                  Cost Dashboard &amp; Spend Intelligence
                </h1>
                <span className="text-[10px] uppercase font-bold tracking-wider px-2 py-0.5 rounded-full bg-primary/20 text-primary border border-primary/30">
                  Real-Time
                </span>
              </div>
              <p className="text-xs text-on-surface-variant">
                Global token expenditure tracking, provider breakdowns, and hard limit enforcement.
              </p>
            </div>
          </div>

          <div className="flex items-center gap-3">
            {/* Period Tabs */}
            <div className="flex items-center bg-black/50 border border-white/10 p-1 rounded-xl">
              {(
                [
                  { id: "today", label: "Today" },
                  { id: "7d", label: "7d" },
                  { id: "30d", label: "30d" },
                  { id: "all", label: "All-time" },
                ] as const
              ).map(({ id, label }) => (
                <button
                  key={id}
                  type="button"
                  onClick={() => setActivePeriod(id)}
                  className={`px-3 py-1 rounded-lg text-xs font-medium transition-all cursor-pointer ${
                    activePeriod === id
                      ? "bg-primary text-[#001f24] font-bold shadow-sm"
                      : "text-on-surface-variant hover:text-white"
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>

            {/* Export CSV Button */}
            <button
              type="button"
              onClick={handleExportCsv}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-white/5 hover:bg-white/10 text-xs text-white border border-white/10 transition-all cursor-pointer font-medium"
              title="Export spend report as CSV"
            >
              <Download size={14} />
              <span>Export CSV</span>
            </button>

            {/* Close Button */}
            <button
              type="button"
              onClick={handleClose}
              className="p-1.5 rounded-xl text-on-surface-variant hover:text-white hover:bg-white/10 transition-colors cursor-pointer"
              title="Close (Esc)"
            >
              <X size={20} />
            </button>
          </div>
        </header>

        {/* ── Main Scrollable Body ────────────────────────────────────────────── */}
        <div className="flex-1 overflow-y-auto p-6 space-y-6 custom-scrollbar">
          {/* ── KPI Stat Cards ────────────────────────────────────────────────── */}
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
            {/* Card 1: Today's Spend & Budget Cap */}
            <div className="bg-[#14151e] border border-white/10 rounded-xl p-4 flex flex-col justify-between shadow-lg relative overflow-hidden">
              <div className="flex items-center justify-between">
                <span className="text-xs font-semibold text-on-surface-variant uppercase tracking-wider">
                  Today's Spend
                </span>
                {isOverBudget ? (
                  <span className="flex items-center gap-1 text-[10px] font-bold px-2 py-0.5 rounded-full bg-rose-500/20 text-rose-400 border border-rose-500/30 animate-pulse">
                    <ShieldAlert size={11} /> Over Budget
                  </span>
                ) : isNearLimit ? (
                  <span className="flex items-center gap-1 text-[10px] font-bold px-2 py-0.5 rounded-full bg-amber-500/20 text-amber-400 border border-amber-500/30">
                    <AlertTriangle size={11} /> Auto-Downgrade
                  </span>
                ) : (
                  <span className="flex items-center gap-1 text-[10px] font-bold px-2 py-0.5 rounded-full bg-emerald-500/20 text-emerald-400 border border-emerald-500/30">
                    <CheckCircle2 size={11} /> Within Limit
                  </span>
                )}
              </div>

              <div className="my-2">
                <div className="text-3xl font-extrabold text-white tracking-tight">
                  ${(budget.today_spend_usd || 0).toFixed(2)}
                  <span className="text-sm font-normal text-on-surface-variant ml-2">
                    {budget.daily_limit_usd ? `/ $${budget.daily_limit_usd.toFixed(2)}` : "unlimited"}
                  </span>
                </div>
              </div>

              {budget.daily_limit_usd && (
                <div className="space-y-1">
                  <div className="w-full h-1.5 bg-white/10 rounded-full overflow-hidden">
                    <div
                      className={`h-full rounded-full transition-all duration-500 ${
                        isOverBudget ? "bg-rose-500" : isNearLimit ? "bg-amber-400" : "bg-emerald-400"
                      }`}
                      style={{ width: `${Math.min(100, usagePct)}%` }}
                    />
                  </div>
                  <div className="flex justify-between text-[10px] text-on-surface-variant font-mono">
                    <span>{usagePct.toFixed(1)}% of daily cap</span>
                    <span>Action: {budget.status || "none"}</span>
                  </div>
                </div>
              )}
            </div>

            {/* Card 2: Selected Period Spend */}
            <div className="bg-[#14151e] border border-white/10 rounded-xl p-4 flex flex-col justify-between shadow-lg">
              <div className="flex items-center justify-between">
                <span className="text-xs font-semibold text-on-surface-variant uppercase tracking-wider">
                  {activePeriod === "today" ? "Today" : activePeriod === "7d" ? "Past 7 Days" : activePeriod === "30d" ? "Past 30 Days" : "All Time"} Spend
                </span>
                <TrendingUp size={16} className="text-primary" />
              </div>
              <div className="my-2">
                <div className="text-3xl font-extrabold text-white tracking-tight">
                  ${(summary.total_usd || 0).toFixed(2)}
                </div>
              </div>
              <div className="text-[11px] text-on-surface-variant flex items-center justify-between">
                <span>{(summary.per_job || []).length} job completions</span>
                <span className="text-primary font-mono font-medium">
                  {Object.keys(summary.per_model || {}).length} models used
                </span>
              </div>
            </div>

            {/* Card 3: Top Provider */}
            <div className="bg-[#14151e] border border-white/10 rounded-xl p-4 flex flex-col justify-between shadow-lg">
              <div className="flex items-center justify-between">
                <span className="text-xs font-semibold text-on-surface-variant uppercase tracking-wider">
                  Top Provider
                </span>
                <Layers size={16} className="text-cyan-400" />
              </div>
              <div className="my-2">
                <div className="text-2xl font-bold text-white tracking-tight capitalize truncate">
                  {topProviderEntry ? topProviderEntry.name : "None"}
                </div>
              </div>
              <div className="text-[11px] text-on-surface-variant flex justify-between">
                <span>Spend share:</span>
                <span className="font-mono text-cyan-300 font-bold">
                  {topProviderEntry && summary.total_usd > 0
                    ? `${((topProviderEntry.value / summary.total_usd) * 100).toFixed(1)}% ($${topProviderEntry.value.toFixed(2)})`
                    : "0%"}
                </span>
              </div>
            </div>

            {/* Card 4: Top Model */}
            <div className="bg-[#14151e] border border-white/10 rounded-xl p-4 flex flex-col justify-between shadow-lg">
              <div className="flex items-center justify-between">
                <span className="text-xs font-semibold text-on-surface-variant uppercase tracking-wider">
                  Top Model
                </span>
                <Cpu size={16} className="text-amber-400" />
              </div>
              <div className="my-2">
                <div className="text-2xl font-bold text-white tracking-tight truncate">
                  {topModels[0] ? topModels[0].model : "None"}
                </div>
              </div>
              <div className="text-[11px] text-on-surface-variant flex justify-between">
                <span>Model spend:</span>
                <span className="font-mono text-amber-300 font-bold">
                  {topModels[0] ? `$${topModels[0].cost.toFixed(4)}` : "$0.00"}
                </span>
              </div>
            </div>
          </div>

          {/* ── Charts Grid ───────────────────────────────────────────────────── */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            {/* Daily Spend Bar Chart (2 cols) */}
            <div className="lg:col-span-2 bg-[#14151e] border border-white/10 rounded-xl p-5 shadow-lg flex flex-col">
              <div className="flex items-center justify-between mb-4">
                <div>
                  <h2 className="text-sm font-bold text-white">Daily Spend Over Time</h2>
                  <p className="text-[11px] text-on-surface-variant">
                    Aggregated daily cost history (last {dailyBreakdown.length} days)
                  </p>
                </div>
                <div className="text-xs font-mono text-primary font-semibold">
                  Total: ${(dailyBreakdown.reduce((sum, d) => sum + (d.usd || 0), 0)).toFixed(2)}
                </div>
              </div>

              <div className="w-full h-64">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={dailyBreakdown} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#ffffff10" vertical={false} />
                    <XAxis
                      dataKey="date"
                      tickLine={false}
                      axisLine={{ stroke: "#ffffff20" }}
                      tick={{ fill: "#9ca3af", fontSize: 10 }}
                      tickFormatter={(val: string) => (val ? val.slice(5) : "")}
                    />
                    <YAxis
                      tickLine={false}
                      axisLine={{ stroke: "#ffffff20" }}
                      tick={{ fill: "#9ca3af", fontSize: 10 }}
                      tickFormatter={(val: number) => `$${val.toFixed(2)}`}
                    />
                    <Tooltip
                      contentStyle={{
                        backgroundColor: "#0d0e15",
                        borderColor: "#ffffff20",
                        borderRadius: "8px",
                        fontSize: "12px",
                      }}
                      formatter={(val: any) => [`$${Number(val).toFixed(4)}`, "Spend"]}
                      labelFormatter={(label: any) => `Date: ${label}`}
                    />
                    <Bar dataKey="usd" fill="#00daf3" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>

            {/* Provider Spend Pie Chart (1 col) */}
            <div className="bg-[#14151e] border border-white/10 rounded-xl p-5 shadow-lg flex flex-col">
              <div className="flex items-center justify-between mb-2">
                <div>
                  <h2 className="text-sm font-bold text-white">Spend by Provider</h2>
                  <p className="text-[11px] text-on-surface-variant">Distribution across AI providers</p>
                </div>
              </div>

              <div className="w-full h-64 flex items-center justify-center">
                {providerPieData.length === 0 ? (
                  <div className="text-xs text-on-surface-variant/60">No provider spend data</div>
                ) : (
                  <ResponsiveContainer width="100%" height="100%">
                    <PieChart>
                      <Pie
                        data={providerPieData}
                        dataKey="value"
                        nameKey="name"
                        cx="50%"
                        cy="50%"
                        innerRadius={45}
                        outerRadius={75}
                        paddingAngle={3}
                      >
                        {providerPieData.map((entry, index) => (
                          <Cell key={`cell-${index}`} fill={entry.color} stroke="#0c0d12" strokeWidth={2} />
                        ))}
                      </Pie>
                      <Tooltip
                        contentStyle={{
                          backgroundColor: "#0d0e15",
                          borderColor: "#ffffff20",
                          borderRadius: "8px",
                          fontSize: "12px",
                        }}
                        formatter={(val: any) => [`$${Number(val).toFixed(4)}`, "Cost"]}
                      />
                      <Legend wrapperStyle={{ fontSize: "11px", paddingTop: "8px" }} />
                    </PieChart>
                  </ResponsiveContainer>
                )}
              </div>
            </div>
          </div>

          {/* ── Tables Grid ───────────────────────────────────────────────────── */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* Table 1: Spend by Model */}
            <div className="bg-[#14151e] border border-white/10 rounded-xl p-5 shadow-lg flex flex-col">
              <h2 className="text-sm font-bold text-white mb-1">Top Models by Spend</h2>
              <p className="text-[11px] text-on-surface-variant mb-3">Top 10 highest expenditure models</p>

              <div className="flex-1 overflow-x-auto">
                <table className="w-full text-left text-xs">
                  <thead>
                    <tr className="border-b border-white/10 text-[10px] text-on-surface-variant uppercase font-mono">
                      <th className="pb-2">Model</th>
                      <th className="pb-2 text-right">Spend (USD)</th>
                      <th className="pb-2 text-right">Share</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-white/5">
                    {topModels.length === 0 ? (
                      <tr>
                        <td colSpan={3} className="py-4 text-center text-on-surface-variant/60 text-xs">
                          No model expenditure recorded.
                        </td>
                      </tr>
                    ) : (
                      topModels.map(({ model, cost }, idx) => {
                        const share = summary.total_usd > 0 ? (cost / summary.total_usd) * 100 : 0;
                        return (
                          <tr key={idx} className="hover:bg-white/5 transition-colors">
                            <td className="py-2.5 font-medium text-white truncate max-w-xs">{model}</td>
                            <td className="py-2.5 text-right font-mono text-cyan-300 font-semibold">
                              ${cost.toFixed(4)}
                            </td>
                            <td className="py-2.5 text-right font-mono text-on-surface-variant">
                              {share.toFixed(1)}%
                            </td>
                          </tr>
                        );
                      })
                    )}
                  </tbody>
                </table>
              </div>
            </div>

            {/* Table 2: Spend by Job */}
            <div className="bg-[#14151e] border border-white/10 rounded-xl p-5 shadow-lg flex flex-col">
              <h2 className="text-sm font-bold text-white mb-1">Recent Jobs Expenditure</h2>
              <p className="text-[11px] text-on-surface-variant mb-3">Per-job token usage and cost tracking</p>

              <div className="flex-1 overflow-x-auto max-h-60 custom-scrollbar">
                <table className="w-full text-left text-xs">
                  <thead>
                    <tr className="border-b border-white/10 text-[10px] text-on-surface-variant uppercase font-mono">
                      <th className="pb-2">Job ID</th>
                      <th className="pb-2">Provider / Model</th>
                      <th className="pb-2 text-right">Tokens</th>
                      <th className="pb-2 text-right">Cost (USD)</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-white/5">
                    {(summary.per_job || []).length === 0 ? (
                      <tr>
                        <td colSpan={4} className="py-4 text-center text-on-surface-variant/60 text-xs">
                          No job expenditure recorded yet.
                        </td>
                      </tr>
                    ) : (
                      (summary.per_job || []).slice(0, 15).map((job, idx) => (
                        <tr key={idx} className="hover:bg-white/5 transition-colors cursor-pointer">
                          <td className="py-2 font-mono text-primary truncate max-w-[120px]" title={job.job_id}>
                            {job.job_id.slice(0, 10)}…
                          </td>
                          <td className="py-2 text-on-surface truncate max-w-[160px]">
                            <span className="text-white font-medium">{job.model}</span>
                            <span className="text-[10px] text-on-surface-variant ml-1">({job.provider})</span>
                          </td>
                          <td className="py-2 text-right font-mono text-on-surface-variant">
                            {job.token_count.toLocaleString()}
                          </td>
                          <td className="py-2 text-right font-mono text-cyan-300 font-semibold">
                            ${job.cost_usd.toFixed(4)}
                          </td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
