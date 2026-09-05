import React, { useState } from "react";
import {
  Layers,
  Terminal,
  ShieldCheck,
  FlaskConical,
  Server,
  Plus,
  Zap,
  Activity,
  Coins,
  ChevronDown,
  type LucideIcon,
} from "lucide-react";
import { useTeamStore, TeamRole } from "./teamStore";

interface RoleMetadata {
  role: TeamRole;
  displayName: string;
  description: string;
  icon: LucideIcon;
  color: string;
  borderColor: string;
  bgGlow: string;
  modelKey: keyof typeof MODEL_KEYS;
  providerKey: keyof typeof PROVIDER_KEYS;
}

const MODEL_KEYS = {
  architect: "architect_model",
  coder: "coder_model",
  reviewer: "reviewer_model",
  tester: "tester_model",
  devops: "devops_model",
} as const;

const PROVIDER_KEYS = {
  architect: "architect_provider",
  coder: "coder_provider",
  reviewer: "reviewer_provider",
  tester: "tester_provider",
  devops: "devops_provider",
} as const;

const ROLES: RoleMetadata[] = [
  {
    role: "architect",
    displayName: "Architect",
    description: "System design, specifications & module decomposition",
    icon: Layers,
    color: "text-purple-400",
    borderColor: "border-purple-500/30",
    bgGlow: "bg-purple-500/10",
    modelKey: "architect",
    providerKey: "architect",
  },
  {
    role: "coder",
    displayName: "Coder",
    description: "Production code generation, refactoring & implementation",
    icon: Terminal,
    color: "text-emerald-400",
    borderColor: "border-emerald-500/30",
    bgGlow: "bg-emerald-500/10",
    modelKey: "coder",
    providerKey: "coder",
  },
  {
    role: "reviewer",
    displayName: "Reviewer",
    description: "Code audit, security analysis, invariants & PR review",
    icon: ShieldCheck,
    color: "text-amber-400",
    borderColor: "border-amber-500/30",
    bgGlow: "bg-amber-500/10",
    modelKey: "reviewer",
    providerKey: "reviewer",
  },
  {
    role: "tester",
    displayName: "Tester",
    description: "Unit tests, edge cases, chaos checks & verification",
    icon: FlaskConical,
    color: "text-cyan-400",
    borderColor: "border-cyan-500/30",
    bgGlow: "bg-cyan-500/10",
    modelKey: "tester",
    providerKey: "tester",
  },
  {
    role: "devops",
    displayName: "DevOps",
    description: "Build tooling, dependencies, migrations & deployments",
    icon: Server,
    color: "text-rose-400",
    borderColor: "border-rose-500/30",
    bgGlow: "bg-rose-500/10",
    modelKey: "devops",
    providerKey: "devops",
  },
];

const MODEL_PRESETS = [
  { label: "Claude 3.5 Sonnet", model: "claude-3-5-sonnet-latest", provider: "anthropic" },
  { label: "GPT-4o", model: "gpt-4o", provider: "openai" },
  { label: "GPT-4o Mini", model: "gpt-4o-mini", provider: "openai" },
  { label: "Llama 3.3 70B (Groq)", model: "llama-3.3-70b-versatile", provider: "groq" },
  { label: "Llama 3.1 8B (Groq)", model: "llama-3.1-8b-instant", provider: "groq" },
  { label: "DeepSeek V3", model: "deepseek/deepseek-chat", provider: "openrouter" },
  { label: "Gemini 2.5 Flash", model: "gemini-2.5-flash", provider: "gemini" },
];

interface ModelPricing {
  inputPerMillion: number;
  outputPerMillion: number;
}

const MODEL_PRICING: Record<string, ModelPricing> = {
  "gpt-4o": { inputPerMillion: 2.50, outputPerMillion: 10.00 },
  "gpt-4o-mini": { inputPerMillion: 0.15, outputPerMillion: 0.60 },
  "claude-3-5-sonnet-latest": { inputPerMillion: 3.00, outputPerMillion: 15.00 },
  "claude-3-5-sonnet": { inputPerMillion: 3.00, outputPerMillion: 15.00 },
  "llama-3.3-70b-versatile": { inputPerMillion: 0.59, outputPerMillion: 0.79 },
  "llama-3.1-8b-instant": { inputPerMillion: 0.05, outputPerMillion: 0.08 },
};

function getPricingForModel(model: string): ModelPricing {
  const m = model.toLowerCase();
  for (const [key, p] of Object.entries(MODEL_PRICING)) {
    if (m.includes(key) || key.includes(m)) return p;
  }
  return { inputPerMillion: 2.50, outputPerMillion: 10.00 };
}

export const AgentRoster: React.FC = () => {
  const { teamConfig, updateTeamConfig, agentMetrics, tasks, jobStatus, isVerifying } = useTeamStore();
  const [showAddModal, setShowAddModal] = useState(false);

  const getRoleStatus = (role: TeamRole) => {
    const roleTasks = tasks.filter((t) => t.assigned_agent === role);
    if (roleTasks.some((t) => t.status === "running")) return "running";
    if (roleTasks.some((t) => t.status === "failed")) return "failed";
    if (roleTasks.length > 0 && roleTasks.every((t) => t.status === "completed")) return "completed";
    if (roleTasks.some((t) => t.status === "waiting" || t.status === "pending" || t.status === "queued")) {
      return "waiting";
    }
    return "idle";
  };

  const getStatusBadge = (status: string) => {
    switch (status) {
      case "running":
        return (
          <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-primary-container/20 text-primary-container border border-primary-container/40 flex items-center gap-1">
            <span className="w-1.5 h-1.5 rounded-full bg-primary-container animate-pulse" />
            RUNNING
          </span>
        );
      case "completed":
        return (
          <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-emerald-500/20 text-emerald-300 border border-emerald-500/30">
            DONE
          </span>
        );
      case "failed":
        return (
          <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-error/20 text-error border border-error/30">
            FAILED
          </span>
        );
      case "waiting":
        return (
          <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-amber-500/20 text-amber-300 border border-amber-500/30">
            WAITING
          </span>
        );
      default:
        return (
          <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-white/5 text-on-surface-variant/70 border border-white/10">
            IDLE
          </span>
        );
    }
  };

  return (
    <div className="flex flex-col gap-4 h-full">
      {/* Roster Header */}
      <div className="flex justify-between items-center px-1">
        <div className="flex items-center gap-2">
          <Zap size={16} className="text-primary-container" />
          <h2 className="text-xs font-bold uppercase tracking-wider text-on-surface">Agent Roster</h2>
          <span className="px-1.5 py-0.2 rounded text-[10px] bg-white/5 text-on-surface-variant font-mono">
            {ROLES.length} Active
          </span>
          {(isVerifying || jobStatus === "verifying") && (
            <span
              data-testid="verification-badge"
              className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-purple-500/20 text-purple-300 border border-purple-500/40 animate-pulse flex items-center gap-1"
            >
              <span className="w-1.5 h-1.5 rounded-full bg-purple-400 animate-ping" />
              Verification in progress...
            </span>
          )}
        </div>
        <button
          onClick={() => setShowAddModal(true)}
          className="flex items-center gap-1 px-2.5 py-1 rounded-lg text-xs bg-surface-container-high hover:bg-surface-variant text-on-surface border border-white/10 transition-colors cursor-pointer"
          title="Add Custom Agent Role"
        >
          <Plus size={13} />
          <span>Add Agent</span>
        </button>
      </div>

      {/* Roster Cards Grid */}
      <div className="flex flex-col gap-3 overflow-y-auto pr-1">
        {ROLES.map((r) => {
          const Icon = r.icon;
          const status = getRoleStatus(r.role);
          const currentRunningTask = tasks.find(
            (t) => t.assigned_agent === r.role && t.status === "running"
          );
          const metrics = agentMetrics[r.role] || {
            total_tokens: 0,
            input_tokens: 0,
            output_tokens: 0,
            total_cost: 0,
            message_count: 0,
          };

          const activeModel = teamConfig[MODEL_KEYS[r.modelKey]] || "gpt-4o";
          const activeProvider = teamConfig[PROVIDER_KEYS[r.providerKey]] || "openai";
          const pricing = getPricingForModel(activeModel);
          const inTokens = metrics.input_tokens || 0;
          const outTokens = metrics.output_tokens || 0;
          const inCost = (inTokens / 1_000_000) * pricing.inputPerMillion;
          const outCost = (outTokens / 1_000_000) * pricing.outputPerMillion;
          const calculatedCost = inCost + outCost;
          const totalCost = metrics.total_cost > 0 ? metrics.total_cost : calculatedCost;

          return (
            <div
              key={r.role}
              data-testid={`agent-card-${r.role}`}
              className={`rounded-xl p-3.5 border ${r.borderColor} bg-surface-container-low hover:bg-surface-container transition-all flex flex-col gap-2.5 shadow-sm relative overflow-hidden`}
            >
              {/* Card Header: Icon + Name + Status Badge */}
              <div className="flex justify-between items-start">
                <div className="flex items-center gap-2.5">
                  <div className={`p-2 rounded-lg ${r.bgGlow} ${r.color}`}>
                    <Icon size={16} />
                  </div>
                  <div>
                    <div className="flex items-center gap-1.5">
                      <h3 className="text-xs font-bold text-on-surface">{r.displayName}</h3>
                      <span className="text-[10px] text-on-surface-variant font-mono lowercase">
                        @{r.role}
                      </span>
                    </div>
                    <p className="text-[10px] text-on-surface-variant/80 line-clamp-1">
                      {r.description}
                    </p>
                  </div>
                </div>
                <div>{getStatusBadge(status)}</div>
              </div>

              {/* Current Active Task (if running) */}
              {currentRunningTask && (
                <div className="bg-primary-container/10 border border-primary-container/20 rounded-lg px-2.5 py-1.5 flex items-center gap-2">
                  <Activity size={12} className="text-primary-container animate-spin" />
                  <span className="text-[11px] font-medium text-primary-container truncate">
                    {currentRunningTask.title}
                  </span>
                </div>
              )}

              {/* Model Selector Dropdown */}
              <div className="flex items-center gap-2">
                <label className="text-[10px] font-medium text-on-surface-variant shrink-0">Model:</label>
                <div className="relative flex-1">
                  <select
                    disabled={jobStatus === "running" || jobStatus === "verifying"}
                    value={`${activeProvider}:${activeModel}`}
                    onChange={(e) => {
                      const [provider, model] = e.target.value.split(":");
                      updateTeamConfig({
                        [MODEL_KEYS[r.modelKey]]: model,
                        [PROVIDER_KEYS[r.providerKey]]: provider,
                      });
                    }}
                    className="w-full bg-[#131315] border border-white/10 rounded-md px-2 py-1 text-[11px] text-on-surface appearance-none focus:outline-none focus:border-primary-container cursor-pointer font-mono disabled:opacity-50"
                  >
                    {MODEL_PRESETS.map((p) => (
                      <option key={`${p.provider}:${p.model}`} value={`${p.provider}:${p.model}`}>
                        {p.label} ({p.provider})
                      </option>
                    ))}
                    {!MODEL_PRESETS.some((p) => p.model === activeModel) && (
                      <option value={`${activeProvider}:${activeModel}`}>
                        {activeModel} ({activeProvider})
                      </option>
                    )}
                  </select>
                  <ChevronDown
                    size={12}
                    className="absolute right-2 top-1/2 -translate-y-1/2 text-on-surface-variant pointer-events-none"
                  />
                </div>
              </div>

              {/* Live Cost Breakdown per Role */}
              <div
                data-testid={`cost-breakdown-${r.role}`}
                className="pt-2 border-t border-white/5 flex flex-col gap-1 text-[10px] font-mono text-on-surface-variant"
              >
                <div className="flex items-center justify-between">
                  <span className="flex items-center gap-1">
                    <Coins size={10} className="text-amber-400" />
                    Input tokens: {inTokens.toLocaleString()} (${inCost.toFixed(2)})
                  </span>
                </div>
                <div className="flex items-center justify-between">
                  <span>Output tokens: {outTokens.toLocaleString()} (${outCost.toFixed(2)})</span>
                </div>
                <div className="flex items-center justify-between pt-0.5 border-t border-white/5 text-emerald-400 font-bold">
                  <span>Total: ${totalCost.toFixed(2)}</span>
                  {metrics.total_tokens > 0 && (
                    <div className="flex items-center gap-1 text-[9px] text-on-surface-variant font-normal">
                      <span>{metrics.total_tokens.toLocaleString()}</span>
                      <span>tok</span>
                      <span className="text-emerald-400/80">${metrics.total_cost.toFixed(4)}</span>
                    </div>
                  )}
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {/* Add Agent Modal / Notification */}
      {showAddModal && (
        <div className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4">
          <div className="bg-surface-container-low border border-white/10 rounded-xl p-5 max-w-sm w-full flex flex-col gap-4 shadow-2xl">
            <h3 className="text-sm font-bold text-on-surface flex items-center gap-2">
              <Plus size={16} className="text-primary-container" />
              Custom Agent Roles
            </h3>
            <p className="text-xs text-on-surface-variant leading-relaxed">
              Autonomous custom agent role provisioning (e.g. Data Scientist, Security Auditor, Tech Writer) will be unlocked in Phase B5.
            </p>
            <div className="flex justify-end">
              <button
                onClick={() => setShowAddModal(false)}
                className="px-3 py-1.5 rounded-lg text-xs bg-primary-container text-on-primary-container font-medium hover:opacity-90 cursor-pointer"
              >
                Understood
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
