// Marathon Autopilot — Start Marathon modal with goal input and budget sliders
import { useState } from "react";
import { Rocket, X, Coins, Clock, DollarSign, Zap } from "lucide-react";
import { useMarathonStore } from "./marathonStore";
import { useWorkspaceStore } from "../../stores/workspaceStore";
import type { BudgetConfig } from "./types";

const DEFAULT_BUDGET: BudgetConfig = {
  token_budget: 500_000,
  time_budget_seconds: 4 * 3600,
  cost_budget_usd: 5.0,
};

function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  return `${(n / 1_000).toFixed(0)}K`;
}

function formatTime(s: number): string {
  const h = s / 3600;
  return h < 1 ? `${(h * 60).toFixed(0)}m` : `${h.toFixed(1)}h`;
}

export function MarathonModal() {
  const { startMarathon, isLoading, error, setShowModal, clearError } = useMarathonStore();
  const workspace = useWorkspaceStore((s) => s.currentWorkspace?.path ?? ".");

  const [goal, setGoal] = useState("");
  const [budget, setBudget] = useState<BudgetConfig>(DEFAULT_BUDGET);
  const [clarifyingAnswer, setClarifyingAnswer] = useState("");

  const handleStart = async () => {
    if (!goal.trim()) return;
    await startMarathon({
      goal: goal.trim(),
      workspace,
      budget,
      provider_config: { provider: "openai", model: "gpt-4o" },
      clarifying_answer: clarifyingAnswer || undefined,
    });
  };

  return (
    <div className="fixed inset-0 z-[10000] flex items-center justify-center bg-black/70 backdrop-blur-md">
      <div
        id="marathon-modal"
        className="relative w-full max-w-2xl bg-[#0e1117] border border-violet-500/30 rounded-2xl shadow-[0_0_80px_rgba(139,92,246,0.25)] overflow-hidden"
      >
        {/* Header */}
        <div className="flex items-center gap-3 px-6 py-4 border-b border-violet-500/20 bg-gradient-to-r from-violet-950/60 to-indigo-950/60">
          <div className="w-9 h-9 rounded-xl bg-violet-500/20 border border-violet-500/30 flex items-center justify-center">
            <Rocket size={18} className="text-violet-400" />
          </div>
          <div>
            <h2 className="text-base font-bold text-slate-100 tracking-tight">Start Marathon</h2>
            <p className="text-xs text-slate-400">Autonomous multi-day project executor</p>
          </div>
          <button
            id="marathon-modal-close"
            onClick={() => { clearError(); setShowModal(false); }}
            className="ml-auto p-1.5 rounded-lg text-slate-400 hover:text-slate-200 hover:bg-white/10 transition-colors"
          >
            <X size={16} />
          </button>
        </div>

        {/* Body */}
        <div className="p-6 space-y-5">
          {/* Goal textarea */}
          <div>
            <label className="block text-xs font-semibold text-slate-300 mb-1.5 uppercase tracking-wider">
              Grand Goal
            </label>
            <textarea
              id="marathon-goal-input"
              value={goal}
              onChange={(e) => setGoal(e.target.value)}
              placeholder='e.g. "Migrate the entire database from SQLite to Postgres, update all ORMs and write migration tests"'
              rows={4}
              className="w-full bg-[#1a1f2e] border border-slate-600/50 rounded-xl px-4 py-3 text-sm text-slate-200 placeholder-slate-500 resize-none focus:outline-none focus:border-violet-500/60 focus:ring-1 focus:ring-violet-500/30 transition-all font-mono"
            />
          </div>

          {/* Clarifying answer (optional) */}
          <div>
            <label className="block text-xs font-semibold text-slate-400 mb-1 uppercase tracking-wider">
              Additional Context <span className="text-slate-500 font-normal">(optional)</span>
            </label>
            <input
              id="marathon-clarify-input"
              type="text"
              value={clarifyingAnswer}
              onChange={(e) => setClarifyingAnswer(e.target.value)}
              placeholder="Stack constraints, must-keep tests, naming conventions…"
              className="w-full bg-[#1a1f2e] border border-slate-600/50 rounded-xl px-4 py-2.5 text-sm text-slate-300 placeholder-slate-500 focus:outline-none focus:border-violet-500/60 transition-all"
            />
          </div>

          {/* Budget sliders */}
          <div className="grid grid-cols-3 gap-4">
            {/* Token Budget */}
            <div className="space-y-2">
              <div className="flex items-center gap-1.5 text-xs font-semibold text-slate-300 uppercase tracking-wider">
                <Zap size={12} className="text-cyan-400" />
                Tokens
              </div>
              <input
                id="marathon-token-slider"
                type="range"
                min={100_000}
                max={5_000_000}
                step={100_000}
                value={budget.token_budget}
                onChange={(e) => setBudget((b) => ({ ...b, token_budget: Number(e.target.value) }))}
                className="w-full accent-violet-500 cursor-pointer"
              />
              <div className="text-center text-sm font-bold text-violet-300">
                {formatTokens(budget.token_budget)}
              </div>
            </div>

            {/* Time Budget */}
            <div className="space-y-2">
              <div className="flex items-center gap-1.5 text-xs font-semibold text-slate-300 uppercase tracking-wider">
                <Clock size={12} className="text-amber-400" />
                Time
              </div>
              <input
                id="marathon-time-slider"
                type="range"
                min={1800}
                max={86400}
                step={1800}
                value={budget.time_budget_seconds}
                onChange={(e) => setBudget((b) => ({ ...b, time_budget_seconds: Number(e.target.value) }))}
                className="w-full accent-amber-500 cursor-pointer"
              />
              <div className="text-center text-sm font-bold text-amber-300">
                {formatTime(budget.time_budget_seconds)}
              </div>
            </div>

            {/* Cost Budget */}
            <div className="space-y-2">
              <div className="flex items-center gap-1.5 text-xs font-semibold text-slate-300 uppercase tracking-wider">
                <DollarSign size={12} className="text-emerald-400" />
                Cost
              </div>
              <input
                id="marathon-cost-slider"
                type="range"
                min={0.5}
                max={50}
                step={0.5}
                value={budget.cost_budget_usd}
                onChange={(e) => setBudget((b) => ({ ...b, cost_budget_usd: Number(e.target.value) }))}
                className="w-full accent-emerald-500 cursor-pointer"
              />
              <div className="text-center text-sm font-bold text-emerald-300">
                ${budget.cost_budget_usd.toFixed(2)}
              </div>
            </div>
          </div>

          {/* Error */}
          {error && (
            <div className="px-4 py-2.5 rounded-lg bg-red-900/30 border border-red-500/40 text-red-300 text-sm">
              {error}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center gap-3 px-6 py-4 border-t border-violet-500/20 bg-[#0a0d14]">
          <button
            onClick={() => { clearError(); setShowModal(false); }}
            className="px-4 py-2 rounded-lg text-slate-400 hover:text-slate-200 hover:bg-white/5 text-sm transition-colors"
          >
            Cancel
          </button>
          <button
            id="marathon-start-btn"
            onClick={() => void handleStart()}
            disabled={isLoading || !goal.trim()}
            className="ml-auto flex items-center gap-2 px-5 py-2 rounded-xl bg-gradient-to-r from-violet-600 to-indigo-600 hover:from-violet-500 hover:to-indigo-500 disabled:opacity-40 disabled:cursor-not-allowed text-white font-semibold text-sm shadow-lg shadow-violet-500/25 transition-all active:scale-95"
          >
            {isLoading ? (
              <>
                <span className="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                Planning…
              </>
            ) : (
              <>
                <Rocket size={15} />
                Start Marathon
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
