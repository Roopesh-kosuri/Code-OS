import { useEffect, useState, useRef, useMemo } from "react";
import {
  Play,
  Square,
  RefreshCw,
  Clock,
  CheckCircle2,
  AlertCircle,
  ShieldAlert,
  ChevronRight,
  Terminal,
  Activity,
  Layers,
  FileCode,
  Check,
  X,
  Sliders,
  Maximize2,
  HelpCircle,
  RotateCcw,
  Zap,
  Loader2,
  Sparkles,
  Bot,
  Flame,
  Globe,
  Server,
  Cpu,
  Users,
  FolderOpen,
  MessageSquare,
  Send,
  CornerDownLeft,
} from "lucide-react";

import { useWorkspaceStore } from "../../stores/workspaceStore";
import { useSettingsStore } from "../../stores/settingsStore";
import { useAIStore } from "../../stores/aiStore";
import { useBackendStore } from "../../stores/backendStore";
import { api } from "../../lib/api";
import { PROVIDER_PRESETS } from "../../lib/providerPresets";
import { CustomSelect, type CustomSelectOption } from "../../components/ui/CustomSelect";
import { LiquidGlassModelSelector } from "../../components/ui/LiquidGlassModelSelector";
import { TeamConsole } from "./console/TeamConsole";
import { FileUploadZone } from "../files/FileUploadZone";
import { FilePreviewModal } from "../files/FilePreviewModal";
import { useFileUploadStore } from "../files/fileUploadStore";

const PROVIDER_OPTIONS: CustomSelectOption[] = [
  {
    value: "auto",
    label: "Auto Routing (default)",
    icon: Sparkles,
    iconColor: "text-purple-400",
    badge: "Auto",
    badgeColor: "bg-purple-500/15 text-purple-300 border border-purple-500/30",
    description: "Intelligently routes requests",
  },
  {
    value: "ollama",
    label: "Ollama (local)",
    icon: Terminal,
    iconColor: "text-emerald-400",
    badge: "Local",
    badgeColor: "bg-emerald-500/15 text-emerald-300 border border-emerald-500/30",
    description: "Offline local models",
  },
  {
    value: "openai",
    label: "OpenAI",
    icon: Zap,
    iconColor: "text-emerald-400",
    badge: "Cloud",
    description: "GPT-4o & reasoning",
  },
  {
    value: "anthropic",
    label: "Anthropic (Claude)",
    icon: Bot,
    iconColor: "text-amber-400",
    badge: "Cloud",
    description: "Claude 3.5 & 3.7",
  },
  {
    value: "gemini",
    label: "Google Gemini",
    icon: Sparkles,
    iconColor: "text-blue-400",
    badge: "Free Tier",
    description: "1M token context",
  },
  {
    value: "groq",
    label: "Groq",
    icon: Flame,
    iconColor: "text-orange-400",
    badge: "Fast LPU",
    badgeColor: "bg-orange-500/15 text-orange-300 border border-orange-500/30",
    description: "Ultra-fast open weights",
  },
  {
    value: "deepseek",
    label: "DeepSeek",
    icon: Globe,
    iconColor: "text-cyan-400",
    badge: "Reasoning",
    description: "V3 & R1 Chain-of-Thought",
  },
  {
    value: "mistral",
    label: "Mistral AI",
    icon: Layers,
    iconColor: "text-rose-400",
    badge: "Cloud",
    description: "Codestral & Mistral Large",
  },
  {
    value: "openrouter",
    label: "OpenRouter",
    icon: Globe,
    iconColor: "text-indigo-400",
    badge: "Aggregator",
    description: "100+ multi-provider models",
  },
  {
    value: "nvidia-nim",
    label: "NVIDIA NIM",
    icon: Cpu,
    iconColor: "text-green-400",
    badge: "GPU Cloud",
    badgeColor: "bg-green-500/15 text-green-300 border border-green-500/30",
    description: "Llama 3.1, MiniMax, DeepSeek",
  },
  {
    value: "custom",
    label: "Custom endpoint",
    icon: Server,
    iconColor: "text-slate-400",
    badge: "Custom",
    description: "OpenAI-compatible HTTP API",
  },
];

const AGENT_CONSOLE_MODEL_SUGGESTIONS: Record<string, { id: string; label: string; tag?: string }[]> = {
  groq: [
    { id: "openai/gpt-oss-120b", label: "gpt-oss-120b", tag: "Recommended" },
    { id: "openai/gpt-oss-20b", label: "gpt-oss-20b", tag: "Fast" },
    { id: "qwen/qwen3.6-27b", label: "qwen-3.6-27b", tag: "Reasoning" },
    { id: "groq/compound-mini", label: "compound-mini", tag: "Fast Agent" },
    { id: "groq/compound", label: "compound" },
  ],
  "nvidia-nim": [
    { id: "minimaxai/minimax-m3", label: "minimax-m3", tag: "Recommended" },
    { id: "minimaxai/minimax-01", label: "minimax-01", tag: "Flagship" },
    { id: "meta/llama-3.1-70b-instruct", label: "llama-3.1-70b" },
    { id: "meta/llama-3.1-8b-instruct", label: "llama-3.1-8b", tag: "Fast" },
    { id: "meta/llama-3.3-70b-instruct", label: "llama-3.3-70b" },
    { id: "deepseek-ai/deepseek-r1", label: "deepseek-r1", tag: "Reasoning" },
    { id: "mistralai/mistral-large-2-instruct", label: "mistral-large-2" },
  ],
  openrouter: [
    { id: "openai/gpt-5.5", label: "gpt-5.5", tag: "Flagship" },
    { id: "openai/gpt-5.6-sol", label: "sol", tag: "Reasoning" },
    { id: "anthropic/claude-opus-4-6", label: "opus-4.6" },
    { id: "anthropic/claude-opus-5", label: "opus-5", tag: "Flagship" },
    { id: "anthropic/claude-sonnet-4-7", label: "sonnet-4.7" },
    { id: "anthropic/claude-sonnet-4-8", label: "sonnet-4.8", tag: "Recommended" },
    { id: "anthropic/claude-sonnet-5", label: "sonnet-5" },
    { id: "anthropic/claude-fable-5", label: "fable-5", tag: "Agent" },
    { id: "google/gemini-2.5-flash", label: "gemini-2.5-flash", tag: "Recommended" },
    { id: "openai/gpt-4o", label: "gpt-4o" },
    { id: "meta-llama/llama-3.3-70b-instruct", label: "llama-3.3-70b" },
    { id: "deepseek/deepseek-chat-v3-0324", label: "deepseek-v3" },
  ],
  openai: [
    { id: "gpt-5.5", label: "gpt-5.5", tag: "Flagship" },
    { id: "gpt-5.6", label: "gpt-5.6", tag: "Flagship" },
    { id: "gpt-5.6-sol", label: "sol", tag: "Reasoning" },
    { id: "gpt-5.6-terra", label: "terra", tag: "Flagship" },
    { id: "gpt-5.6-luna", label: "luna", tag: "Coding" },
    { id: "gpt-4o", label: "gpt-4o", tag: "Recommended" },
    { id: "gpt-4o-mini", label: "gpt-4o-mini", tag: "Fast" },
    { id: "o3-mini", label: "o3-mini", tag: "Reasoning" },
  ],
  anthropic: [
    { id: "claude-sonnet-4-8", label: "sonnet-4.8", tag: "Recommended" },
    { id: "claude-sonnet-4-7", label: "sonnet-4.7" },
    { id: "claude-sonnet-5", label: "sonnet-5", tag: "Flagship" },
    { id: "claude-opus-4-6", label: "opus-4.6" },
    { id: "claude-opus-4-7", label: "opus-4.7" },
    { id: "claude-opus-4-8", label: "opus-4.8" },
    { id: "claude-opus-5", label: "opus-5", tag: "Flagship" },
    { id: "claude-fable-5", label: "fable-5", tag: "Agent" },
    { id: "claude-sonnet-4-5", label: "claude-sonnet-4-5" },
    { id: "claude-3-5-sonnet-latest", label: "claude-3.5-sonnet" },
    { id: "claude-3-5-haiku-latest", label: "claude-3.5-haiku", tag: "Fast" },
  ],
  auto: [
    { id: "claude-sonnet-4-8", label: "sonnet-4.8 (Recommended)", tag: "Recommended" },
    { id: "gpt-5.6-sol", label: "sol (Reasoning)", tag: "Reasoning" },
    { id: "claude-opus-5", label: "opus-5 (Flagship)", tag: "Flagship" },
    { id: "gpt-5.5", label: "gpt-5.5" },
    { id: "claude-fable-5", label: "fable-5", tag: "Agent" },
    { id: "claude-sonnet-4-7", label: "sonnet-4.7" },
  ],
  gemini: [
    { id: "gemini-2.5-flash", label: "gemini-2.5-flash", tag: "Recommended" },
    { id: "gemini-2.5-pro", label: "gemini-2.5-pro" },
    { id: "gemini-2.0-flash", label: "gemini-2.0-flash" },
  ],
  deepseek: [
    { id: "deepseek-chat", label: "deepseek-chat", tag: "Recommended" },
    { id: "deepseek-reasoner", label: "deepseek-reasoner", tag: "Reasoning" },
  ],
  mistral: [
    { id: "mistral-large-latest", label: "mistral-large", tag: "Recommended" },
    { id: "codestral-latest", label: "codestral" },
    { id: "mistral-small-latest", label: "mistral-small", tag: "Fast" },
  ],
  ollama: [
    { id: "llama3", label: "llama3" },
    { id: "codellama", label: "codellama" },
    { id: "mistral", label: "mistral" },
  ],
};

interface AgentTask {
  id: string;
  job_id?: string;
  title: string;
  agent_role: "planner" | "architect" | "coder" | "tester" | "reviewer" | "documenter" | string;
  status: "pending" | "running" | "completed" | "failed" | "skipped";
  dependencies?: string[];
  output?: string;
  structured_output?: {
    files_modified?: string[];
    tests_passed?: boolean;
    issues_found?: string[];
    [key: string]: any;
  };
  pending_action?: {
    type: "clarification" | "task_failure" | "llm_failure" | "command" | "destructive_edit" | "file-write" | string;
    details?: string;
    command?: string;
    target?: string;
    questions?: string[];
  };
}

interface AgentJob {
  id: string;
  workspace: string;
  workflow: string;
  status: "planning" | "running" | "paused" | "completed" | "failed" | "cancelled";
  created_at?: string;
  completed_at?: string;
  tasks: AgentTask[];
  logs: string[];
  progress?: number;
  final_proposal_id?: string;
}

export function AgentConsole({ compact = false }: { compact?: boolean }) {
  const workspace = useWorkspaceStore((state) => state.currentWorkspace);
  const openWorkspace = useWorkspaceStore((state) => state.openWorkspace);
  const globalModel = useAIStore((state) => state.model);
  const globalPreset = useAIStore((state) => state.preset);

  const [instruction, setInstruction] = useState("");
  const [quickEdit, setQuickEdit] = useState(true);
  const [selectedProvider, setSelectedProvider] = useState(globalPreset || "ollama");
  const [selectedModel, setSelectedModel] = useState(globalModel || "llama3");
  const [activeJob, setActiveJob] = useState<AgentJob | null>(null);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [clarificationAnswer, setClarificationAnswer] = useState("");
  const [actionInProgress, setActionInProgress] = useState(false);
  const [recoveryProvider, setRecoveryProvider] = useState<string>("groq");
  const [recoveryModel, setRecoveryModel] = useState<string>("openai/gpt-oss-120b");
  const [teamMode, setTeamMode] = useState(false);
  const [rightPanelTab, setRightPanelTab] = useState<"logs" | "steering">("logs");
  const [steeringInput, setSteeringInput] = useState("");
  const [isSteeringSubmitting, setIsSteeringSubmitting] = useState(false);
  const [steeringHistory, setSteeringHistory] = useState<
    Array<{ id: string; action: string; directive?: string; timestamp: number }>
  >([]);

  const handleSendSteering = async (action: string, directive?: string) => {
    if (!activeJob?.id) return;
    setIsSteeringSubmitting(true);
    const effectiveDirective = directive || (action === "steer" ? steeringInput.trim() : undefined);
    try {
      await api.post(`/api/agents/jobs/${activeJob.id}/steer`, {
        action,
        directive: effectiveDirective,
      });
      setSteeringHistory((prev) => [
        ...prev,
        {
          id: Math.random().toString(36).substring(2, 9),
          action,
          directive: effectiveDirective,
          timestamp: Date.now(),
        },
      ]);
      if (action === "steer") {
        setSteeringInput("");
      }
      if (action === "continue" || action === "retry") {
        const updated = await api.get<AgentJob>(`/api/agents/jobs/${activeJob.id}`);
        if (updated) setActiveJob(updated);
      }
    } catch (err: any) {
      console.error("Failed to steer job:", err);
    } finally {
      setIsSteeringSubmitting(false);
    }
  };

  const logsEndRef = useRef<HTMLDivElement>(null);

  // Timer
  useEffect(() => {
    let interval: any;
    if (activeJob && (activeJob.status === "running" || activeJob.status === "planning")) {
      interval = setInterval(() => {
        setElapsedSeconds((prev) => prev + 1);
      }, 1000);
    }
    return () => clearInterval(interval);
  }, [activeJob?.status]);

  const formattedTimer = useMemo(() => {
    const hours = Math.floor(elapsedSeconds / 3600);
    const minutes = Math.floor((elapsedSeconds % 3600) / 60);
    const seconds = elapsedSeconds % 60;
    return [
      hours.toString().padStart(2, "0"),
      minutes.toString().padStart(2, "0"),
      seconds.toString().padStart(2, "0"),
    ].join(":");
  }, [elapsedSeconds]);

  // Fetch active job status & tasks
  // Fetch active job status & tasks
  const fetchActiveJob = async () => {
    if (!workspace || useBackendStore.getState().status !== "connected") return;
    try {
      if (activeJob?.id) {
        const data = await api.get<AgentJob>(`/api/agents/jobs/${activeJob.id}`);
        if (data) {
          if (data.status === "completed" && activeJob?.status !== "completed") {
            void useWorkspaceStore.getState().refreshTree();
          }
          setActiveJob(data);
          return;
        }
      }
      // Check active / latest jobs for workspace
      const jobs = await api.get<AgentJob[]>("/api/agents/jobs", { workspace: workspace.path });
      if (Array.isArray(jobs) && jobs.length > 0) {
        const running = jobs.find((j) => j.status === "running" || j.status === "planning" || j.status === "paused");
        if (running) {
          const detailed = await api.get<AgentJob>(`/api/agents/jobs/${running.id}`);
          setActiveJob(detailed);
        }
      }
    } catch {
      // ignore
    }
  };

  // Clear stale errors on workspace change
  useEffect(() => {
    setError(null);
  }, [workspace?.path]);

  useEffect(() => {
    void fetchActiveJob();
    const interval = setInterval(() => {
      void fetchActiveJob();
    }, 2000);
    return () => clearInterval(interval);
  }, [workspace?.path, activeJob?.id]);

  useEffect(() => {
    logsEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [activeJob?.logs]);

  // Start Autonomous DAG Run
  const handleStartPlan = async () => {
    if (!instruction.trim() || !workspace) return;
    setLoading(true);
    setError(null);
    setElapsedSeconds(0);

    const userReq = quickEdit && !instruction.includes("--quick")
      ? `${instruction.trim()} --quick`
      : instruction.trim();

    const presetObj = PROVIDER_PRESETS.find((p) => p.id === selectedProvider);
    const providerConfig = {
      preset: selectedProvider,
      provider: presetObj?.provider || "openai-compatible",
      model: selectedModel,
      base_url: presetObj?.base_url || undefined,
      api_key_provider: presetObj?.api_key_provider || selectedProvider,
    };

    try {
      const fileIds = useFileUploadStore.getState().uploadedFiles.map((f) => f.file_id);

      // 1. Generate plan tasks from PlannerAgent
      const planRes = await api.post<{ tasks: any[] }>("/api/agents/plan", {
        workspace: workspace.path,
        user_request: userReq,
        provider_config: providerConfig,
        file_ids: fileIds,
      });

      const tasks = planRes.tasks || [];
      if (tasks.length === 0) {
        setError("Planner agent could not generate execution steps. Please refine the task prompt.");
        setLoading(false);
        return;
      }

      // 2. Start DAG execution job
      const startRes = await api.post<{ job_id: string; status: string }>("/api/agents/jobs", {
        workspace: workspace.path,
        workflow: instruction.trim(),
        tasks: tasks,
        provider_config: providerConfig,
        file_ids: fileIds,
      });

      if (startRes.job_id) {
        const initialJob: AgentJob = {
          id: startRes.job_id,
          workspace: workspace.path,
          workflow: instruction.trim(),
          status: "running",
          tasks: tasks.map((t, i) => ({
            id: t.id || `task_${i}`,
            title: t.title || t.name || `Step ${i + 1}`,
            agent_role: t.agent_role || "coder",
            status: i === 0 ? "running" : "pending",
          })),
          logs: [
            `[${new Date().toLocaleTimeString()}] INFO: Initializing workflow job ${startRes.job_id.slice(0, 8)}`,
            `[${new Date().toLocaleTimeString()}] INFO: Provider: ${selectedProvider} (${selectedModel})`,
            `[${new Date().toLocaleTimeString()}] EXEC: Planned ${tasks.length} execution tasks`,
          ],
        };
        setActiveJob(initialJob);
        // Promptly fetch real status
        setTimeout(() => void fetchActiveJob(), 1000);
      }
    } catch (err: any) {
      setError(err?.message || "Failed to launch autonomous agent plan");
    } finally {
      setLoading(false);
    }
  };

  const handleCancel = async () => {
    if (!activeJob) return;
    try {
      await api.post(`/api/agents/jobs/${activeJob.id}/cancel`);
      void fetchActiveJob();
    } catch (err: any) {
      setError(err?.message || "Failed to cancel job");
    }
  };

  // ── Recovery & Interactive Action Handlers ─────────────────────────────
  const handleApproveAction = async (jobId: string, taskId: string) => {
    setActionInProgress(true);
    try {
      await api.post(`/api/agents/jobs/${jobId}/tasks/${taskId}/approve`);
      await fetchActiveJob();
    } catch (err: any) {
      setError(err?.message || "Failed to approve action");
    } finally {
      setActionInProgress(false);
    }
  };

  const handleRejectAction = async (jobId: string, taskId: string, feedback?: string) => {
    setActionInProgress(true);
    try {
      await api.post(`/api/agents/jobs/${jobId}/tasks/${taskId}/reject`, { feedback });
      await fetchActiveJob();
    } catch (err: any) {
      setError(err?.message || "Failed to deny action");
    } finally {
      setActionInProgress(false);
    }
  };

  const handleRecoverAction = async (
    jobId: string,
    taskId: string,
    action: "retry" | "reduced_pipeline" | "switch_to_api" | "change_model" | "cancel",
    modelPayload?: { provider?: string; model?: string; api_key_provider?: string; base_url?: string }
  ) => {
    setActionInProgress(true);
    try {
      await api.post(`/api/agents/jobs/${jobId}/tasks/${taskId}/recover`, {
        action,
        provider: modelPayload?.provider,
        model: modelPayload?.model,
        api_key_provider: modelPayload?.api_key_provider,
        base_url: modelPayload?.base_url,
      });
      await fetchActiveJob();
    } catch (err: any) {
      setError(err?.message || "Failed to submit recovery action");
    } finally {
      setActionInProgress(false);
    }
  };

  const handleAnswerClarification = async (jobId: string, taskId: string) => {
    if (!clarificationAnswer.trim()) return;
    setActionInProgress(true);
    try {
      await api.post(`/api/agents/jobs/${jobId}/tasks/${taskId}/answer`, { answer: clarificationAnswer.trim() });
      setClarificationAnswer("");
      await fetchActiveJob();
    } catch (err: any) {
      setError(err?.message || "Failed to submit clarification answer");
    } finally {
      setActionInProgress(false);
    }
  };

  const isRunning = Boolean(activeJob && (activeJob.status === "running" || activeJob.status === "planning" || activeJob.status === "paused"));
  const pendingTask = activeJob?.tasks?.find((t) => t.pending_action);

  return (
    <div className="flex-1 flex flex-col h-full overflow-y-auto bg-background text-on-surface p-6 font-ui-label-reg text-ui-label-reg select-none antialiased">
      {/* ── Header ──────────────────────────────────────────────────────── */}
      <div className="flex justify-between items-center mb-6 shrink-0">
        <div className="flex items-center gap-3">
          <h1 className="font-headline-md text-headline-md text-on-surface font-bold tracking-tight">
            Agent Console
          </h1>

          {/* Mode Toggle */}
          <div
            data-testid="mode-toggle"
            className="flex items-center bg-surface-container-low p-1 rounded-xl border border-white/5 ml-2"
          >
            <button
              data-testid="mode-toggle-standard"
              onClick={() => setTeamMode(false)}
              className={`px-3 py-1 rounded-lg text-xs font-medium transition-colors cursor-pointer ${
                !teamMode
                  ? "bg-surface-container-high text-on-surface font-bold shadow"
                  : "text-on-surface-variant hover:text-on-surface"
              }`}
            >
              Standard Workflow
            </button>
            <button
              data-testid="mode-toggle-team"
              onClick={() => setTeamMode(true)}
              className={`flex items-center gap-1.5 px-3 py-1 rounded-lg text-xs font-medium transition-colors cursor-pointer ${
                teamMode
                  ? "bg-primary-container text-on-primary-container font-bold shadow"
                  : "text-on-surface-variant hover:text-on-surface"
              }`}
            >
              <Users size={13} />
              <span>Team Mode</span>
            </button>
          </div>

          {/* Workspace Switcher in Agent Mode */}
          <div className="flex items-center gap-1.5 ml-2 pl-3 border-l border-white/10 text-xs font-mono text-on-surface-variant">
            <FolderOpen size={13} className="text-primary-container shrink-0" />
            <span className="truncate max-w-[140px] text-on-surface font-medium" title={workspace?.path || "No workspace opened"}>
              {workspace?.name || "No Workspace"}
            </span>
            <button
              onClick={() => void openWorkspace()}
              data-testid="agent-mode-change-workspace-btn"
              className="text-[11px] text-primary-container hover:underline cursor-pointer ml-1 font-mono"
              title="Open folder picker to change workspace"
            >
              Change Workspace
            </button>
          </div>

          {!teamMode && (
            <span className={`px-3 py-1 rounded-full font-caption text-caption font-bold tracking-wider flex items-center gap-1.5 ${
              isRunning
                ? activeJob?.status === "paused"
                  ? "bg-amber-500/10 text-amber-300 border border-amber-500/30"
                  : "bg-primary-container/10 text-primary-container border border-primary-container/30"
                : "bg-surface-variant text-on-surface-variant"
            }`}>
              <span className={`w-2 h-2 rounded-full ${
                isRunning
                  ? activeJob?.status === "paused"
                    ? "bg-amber-400 animate-pulse"
                    : "bg-primary-container animate-pulse"
                  : "bg-outline"
              }`} />
              {isRunning ? (activeJob?.status === "paused" ? "PAUSED / ATTENTION" : "RUNNING") : "READY"}
            </span>
          )}
        </div>

        {/* Timer & Refresh */}
        {!teamMode && (
          <div className="flex items-center gap-2">
            <button
              onClick={() => void fetchActiveJob()}
              className="p-1.5 rounded-full bg-surface-container-low hover:bg-surface-container-high text-on-surface-variant hover:text-on-surface transition-colors cursor-pointer border border-white/5"
              title="Refresh Status"
            >
              <RefreshCw size={13} />
            </button>
            <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-surface-container-low border border-white/5 text-on-surface-variant font-mono text-xs">
              <Clock size={14} className="text-primary-container" />
              <span>{formattedTimer}</span>
            </div>
          </div>
        )}
      </div>

      {teamMode ? (
        <TeamConsole />
      ) : (
        <>
          {error && (
            <div className="mb-4 rounded-xl border border-error/40 bg-error/10 p-3 text-xs text-error flex items-center justify-between">
              <div className="flex items-center gap-2">
                <AlertCircle size={16} />
                <span>{error}</span>
              </div>
              <button onClick={() => setError(null)} className="text-error hover:opacity-80">
                <X size={14} />
              </button>
            </div>
          )}

      {/* ΓöÇΓöÇ Main Two-Column Layout ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ */}
      <div className={`grid grid-cols-1 ${compact ? "gap-4" : "lg:grid-cols-2 gap-6"} flex-1 min-h-0`}>
        {/* ΓöÇΓöÇ Left Column: Agent Instruction & Interactive Actions ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ */}
        <div className="flex flex-col gap-6">
          {/* Card 1: Agent Instruction */}
          <div className="bg-surface-container-low rounded-xl border border-surface-container-high p-6 flex flex-col gap-4 shadow-lg">
            <div className="flex justify-between items-center">
              <div className="flex items-center gap-2 text-on-surface font-ui-label-bold text-ui-label-bold">
                <span className="material-symbols-outlined text-primary-container text-lg">description</span>
                <span>Agent Instruction</span>
              </div>
              <div className="flex items-center gap-2">
                <span className="font-caption text-caption text-on-surface-variant">Quick Edit</span>
                <label className="relative inline-block w-10 h-6 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={quickEdit}
                    onChange={(e) => setQuickEdit(e.target.checked)}
                    className="toggle-checkbox absolute block w-5 h-5 rounded-full bg-white border-4 appearance-none cursor-pointer z-10 opacity-0"
                  />
                  <div className="toggle-label block overflow-hidden h-6 rounded-full bg-surface-variant cursor-pointer" />
                </label>
              </div>
            </div>

            {/* File Upload Zone */}
            <FileUploadZone compact workspace={workspace?.path} />

            {/* Instruction Textarea */}
            <textarea
              value={instruction}
              onChange={(e) => setInstruction(e.target.value)}
              placeholder="Describe the autonomous multi-agent task (e.g. Implement user authentication with JWT, refactor database layer, add unit tests)..."
              rows={5}
              disabled={isRunning}
              className="w-full bg-[#131315] border border-surface-variant rounded-lg p-4 font-code-main text-code-main text-on-surface placeholder:text-outline-variant focus:border-primary-container focus:outline-none focus:ring-1 focus:ring-primary-container/20 transition-all resize-none disabled:opacity-50"
            />

            {/* Provider & Model Selects */}
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="font-caption text-caption text-on-surface-variant mb-1.5 block">Provider</label>
                <CustomSelect
                  value={selectedProvider}
                  options={PROVIDER_OPTIONS}
                  disabled={isRunning}
                  variant="liquid-glass"
                  onChange={(nextProvider) => {
                    setSelectedProvider(nextProvider);
                    const preset = PROVIDER_PRESETS.find((p) => p.id === nextProvider);
                    if (preset && preset.model_example) {
                      setSelectedModel(preset.model_example);
                      useAIStore.getState().setPreset(nextProvider, preset.base_url, preset.model_example);
                    } else {
                      useAIStore.getState().setPreset(nextProvider);
                    }
                  }}
                />
              </div>
              <div>
                <label className="font-caption text-caption text-on-surface-variant mb-1.5 block">Model</label>
                <LiquidGlassModelSelector
                  value={selectedModel}
                  provider={selectedProvider}
                  disabled={isRunning}
                  onChange={(val) => {
                    setSelectedModel(val);
                    useAIStore.getState().setModel(val);
                  }}
                  testId="model-selector-trigger"
                  inputTestId="model-selector-input"
                  placeholder="Select model..."
                />
              </div>
            </div>

            {/* Quick Model Suggestions for initial setup */}
            {(() => {
              const suggestions = AGENT_CONSOLE_MODEL_SUGGESTIONS[selectedProvider] || [];
              if (!suggestions.length) return null;
              return (
                <div className="flex flex-wrap items-center gap-1.5 pt-1">
                  <span className="text-[10px] text-on-surface-variant font-medium">Quick Models:</span>
                  {suggestions.map((s) => (
                    <button
                      key={s.id}
                      type="button"
                      disabled={isRunning}
                      onClick={() => setSelectedModel(s.id)}
                      className={`text-[10px] px-2 py-0.5 rounded-full border transition-all cursor-pointer ${selectedModel === s.id ? "bg-primary text-[#001f24] border-primary font-bold shadow" : "bg-surface-variant/30 border-outline/40 hover:border-primary text-on-surface"} disabled:opacity-40`}
                    >
                      {s.label}{s.tag ? ` (${s.tag})` : ""}
                    </button>
                  ))}
                </div>
              );
            })()}

            {/* Action CTA Button */}
            <div className="flex justify-between items-center pt-2">
              {activeJob ? (
                <button
                  type="button"
                  onClick={() => {
                    setActiveJob(null);
                    setInstruction("");
                  }}
                  className="text-xs text-on-surface-variant hover:text-on-surface underline font-mono cursor-pointer"
                >
                  + New Task
                </button>
              ) : <div />}

              {isRunning ? (
                <button
                  onClick={handleCancel}
                  className="px-6 py-2.5 rounded-full font-ui-label-bold text-ui-label-bold bg-error text-on-error hover:bg-error-container hover:text-on-error-container transition-all flex items-center gap-2 shadow-lg cursor-pointer"
                >
                  <Square size={14} /> Stop Agent
                </button>
              ) : (
                <button
                  onClick={handleStartPlan}
                  disabled={loading || !instruction.trim()}
                  className="bg-primary-container hover:bg-primary-fixed text-[#001f24] font-ui-label-bold text-ui-label-bold px-8 py-3 rounded-full flex items-center gap-2 transition-all shadow-[0_0_20px_rgba(0,218,243,0.25)] hover:shadow-[0_0_30px_rgba(0,218,243,0.45)] hover:scale-[1.02] disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer"
                >
                  <span className="material-symbols-outlined text-[18px]">play_arrow</span>
                  <span>{loading ? "Planning Workflow..." : "GENERATE PLAN"}</span>
                </button>
              )}
            </div>
          </div>

          {/* ΓöÇΓöÇ Card 2: Interactive Actions & Recovery (Priority 1) ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ */}
          {pendingTask && pendingTask.pending_action ? (
            <div className="danger-glow rounded-xl p-6 relative overflow-hidden flex flex-col gap-4 shadow-xl">
              {/* Type: Clarification Request */}
              {pendingTask.pending_action.type === "clarification" ? (
                <div className="space-y-4">
                  <div className="flex items-start gap-3">
                    <div className="p-2 rounded-full bg-amber-500/10 text-amber-400 shrink-0">
                      <HelpCircle size={22} />
                    </div>
                    <div>
                      <h3 className="font-ui-label-bold text-ui-label-bold text-amber-400 text-base mb-1">
                        Agent Requests Clarification
                      </h3>
                      <p className="font-ui-label-reg text-ui-label-reg text-on-surface text-xs leading-relaxed">
                        {pendingTask.pending_action.details || "The agent needs additional guidance before proceeding with implementation."}
                      </p>
                    </div>
                  </div>

                  {pendingTask.pending_action.questions && pendingTask.pending_action.questions.length > 0 && (
                    <div className="bg-[#131315] rounded-lg p-3 border border-amber-500/20 space-y-1">
                      {pendingTask.pending_action.questions.map((q, qi) => (
                        <div key={qi} className="text-xs text-amber-200/90 font-medium">
                          ΓÇó {q}
                        </div>
                      ))}
                    </div>
                  )}

                  <textarea
                    value={clarificationAnswer}
                    onChange={(e) => setClarificationAnswer(e.target.value)}
                    placeholder="Provide guidance or answer the questions..."
                    rows={3}
                    className="w-full bg-[#131315] border border-amber-500/30 rounded-lg p-3 text-xs text-on-surface focus:outline-none focus:border-amber-400"
                  />

                  <div className="flex justify-end gap-3 pt-2">
                    <button
                      onClick={() => handleRejectAction(activeJob!.id, pendingTask.id, "Clarification dismissed")}
                      disabled={Boolean(actionInProgress)}
                      className="px-5 py-2 rounded-full border border-outline text-on-surface font-ui-label-bold text-xs hover:bg-surface-variant transition-colors cursor-pointer"
                    >
                      Dismiss
                    </button>
                    <button
                      onClick={() => handleAnswerClarification(activeJob!.id, pendingTask.id)}
                      disabled={Boolean(actionInProgress || !clarificationAnswer.trim())}
                      className="px-6 py-2 rounded-full bg-amber-400 text-[#001f24] font-ui-label-bold text-xs hover:bg-amber-300 transition-colors shadow-lg cursor-pointer flex items-center gap-1.5 disabled:opacity-40"
                    >
                      {actionInProgress ? <Loader2 size={12} className="animate-spin" /> : <Check size={14} />}
                      <span>Submit Answer</span>
                    </button>
                  </div>
                </div>
              ) : pendingTask.pending_action.type === "task_failure" ? (
                /* Type: Task Failure Recovery */
                <div className="space-y-4">
                  <div className="flex items-start gap-3">
                    <div className="p-2 rounded-full bg-error/10 text-error shrink-0">
                      <AlertCircle size={22} />
                    </div>
                    <div>
                      <h3 className="font-ui-label-bold text-ui-label-bold text-error text-base mb-1">
                        Task Execution Stalled
                      </h3>
                      <p className="font-ui-label-reg text-ui-label-reg text-on-surface text-xs leading-relaxed">
                        {pendingTask.pending_action.details || "A step encountered an execution error. Choose a recovery path to proceed:"}
                      </p>
                    </div>
                  </div>

                  <div className="flex flex-wrap gap-2.5 pt-2">
                    <button
                      onClick={() => handleRecoverAction(activeJob!.id, pendingTask.id, "retry")}
                      disabled={Boolean(actionInProgress)}
                      className="px-4 py-2 rounded-full bg-primary-container text-[#001f24] font-ui-label-bold text-xs hover:bg-primary-fixed transition-colors flex items-center gap-1.5 shadow-md cursor-pointer"
                    >
                      <RotateCcw size={13} />
                      <span>Try Again (Re-ground &amp; Retry)</span>
                    </button>
                    <button
                      onClick={() => handleRecoverAction(activeJob!.id, pendingTask.id, "reduced_pipeline")}
                      disabled={Boolean(actionInProgress)}
                      className="px-4 py-2 rounded-full bg-amber-400 text-[#001f24] font-ui-label-bold text-xs hover:bg-amber-300 transition-colors flex items-center gap-1.5 shadow-md cursor-pointer"
                    >
                      <Zap size={13} />
                      <span>Reduced Pipeline</span>
                    </button>
                    <button
                      onClick={() => handleRecoverAction(activeJob!.id, pendingTask.id, "cancel")}
                      disabled={Boolean(actionInProgress)}
                      className="px-4 py-2 rounded-full border border-outline text-on-surface font-ui-label-bold text-xs hover:bg-surface-variant transition-colors cursor-pointer"
                    >
                      Cancel Workflow
                    </button>
                  </div>
                </div>
              ) : pendingTask.pending_action.type === "llm_failure" ? (
                /* Type: LLM / Rate Limit Failure Recovery */
                <div className="space-y-4">
                  <div className="flex items-start gap-3">
                    <div className="p-2 rounded-full bg-error/10 text-error shrink-0">
                      <AlertCircle size={22} />
                    </div>
                    <div className="flex-1">
                      <h3 className="font-ui-label-bold text-ui-label-bold text-error text-base mb-1">
                        Inference Provider Failure
                      </h3>
                      <p className="font-ui-label-reg text-ui-label-reg text-on-surface text-xs leading-relaxed">
                        {pendingTask.pending_action.details || "Inference provider timed out or exceeded rate limit."}
                      </p>
                    </div>
                  </div>

                  {/* ── Dynamic Model Switcher Panel ── */}
                  <div className="bg-surface/50 rounded-xl p-3.5 border border-outline/30 space-y-3">
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-semibold text-on-surface flex items-center gap-1.5">
                        <Sparkles size={14} className="text-primary" />
                        Select Replacement Model & Provider
                      </span>
                      <span className="text-[11px] text-on-surface-variant">Switch model to resume execution</span>
                    </div>

                    <div className="grid grid-cols-1 md:grid-cols-2 gap-2.5">
                      <div>
                        <label className="text-[11px] text-on-surface-variant font-medium block mb-1">Provider</label>
                        <CustomSelect
                          value={recoveryProvider}
                          options={PROVIDER_OPTIONS}
                          variant="liquid-glass"
                          onChange={(nextP) => {
                            setRecoveryProvider(nextP);
                            const preset = PROVIDER_PRESETS.find((p) => p.id === nextP);
                            if (preset?.model_example) {
                              setRecoveryModel(preset.model_example);
                            }
                          }}
                        />
                      </div>

                      <div>
                        <label className="text-[11px] text-on-surface-variant font-medium block mb-1">Model Name / ID</label>
                        <LiquidGlassModelSelector
                          value={recoveryModel}
                          provider={recoveryProvider}
                          onChange={(m) => setRecoveryModel(m)}
                          placeholder="Select recovery model..."
                        />
                      </div>
                    </div>

                    {/* Quick Model Suggestions */}
                    {(() => {
                      const suggestions = AGENT_CONSOLE_MODEL_SUGGESTIONS[recoveryProvider] || [];
                      if (!suggestions.length) return null;
                      return (
                        <div className="flex flex-wrap items-center gap-1.5 pt-0.5">
                          <span className="text-[10px] text-on-surface-variant font-medium">Quick Suggestions:</span>
                          {suggestions.map((s) => (
                            <button
                              key={s.id}
                              type="button"
                              onClick={() => setRecoveryModel(s.id)}
                              className={`text-[10px] px-2 py-0.5 rounded-full border transition-all cursor-pointer ${recoveryModel === s.id ? "bg-primary text-[#001f24] border-primary font-bold shadow" : "bg-surface-variant/30 border-outline/40 hover:border-primary text-on-surface"}`}
                            >
                              {s.label}{s.tag ? ` (${s.tag})` : ""}
                            </button>
                          ))}
                        </div>
                      );
                    })()}
                  </div>

                  <div className="flex flex-wrap gap-2.5 pt-1">
                    <button
                      onClick={() => {
                        const preset = PROVIDER_PRESETS.find((p) => p.id === recoveryProvider);
                        handleRecoverAction(activeJob!.id, pendingTask.id, "change_model", {
                          provider: preset?.provider || recoveryProvider,
                          model: recoveryModel,
                          base_url: preset?.base_url || "",
                          api_key_provider: preset?.api_key_provider || recoveryProvider,
                        });
                      }}
                      disabled={Boolean(actionInProgress)}
                      className="px-4 py-2 rounded-full bg-primary text-[#001f24] font-ui-label-bold text-xs hover:bg-primary/90 transition-colors flex items-center gap-1.5 shadow-md cursor-pointer disabled:opacity-40"
                    >
                      <Sparkles size={13} />
                      <span>Switch Model & Resume</span>
                    </button>
                    <button
                      onClick={() => handleRecoverAction(activeJob!.id, pendingTask.id, "retry")}
                      disabled={Boolean(actionInProgress)}
                      className="px-4 py-2 rounded-full bg-surface-variant text-on-surface font-ui-label-bold text-xs hover:bg-surface-variant/80 transition-colors flex items-center gap-1.5 border border-outline/30 cursor-pointer disabled:opacity-40"
                    >
                      <RotateCcw size={13} />
                      <span>Retry Current Model</span>
                    </button>
                    <button
                      onClick={() => handleRecoverAction(activeJob!.id, pendingTask.id, "cancel")}
                      disabled={Boolean(actionInProgress)}
                      className="px-4 py-2 rounded-full border border-outline text-on-surface font-ui-label-bold text-xs hover:bg-surface-variant transition-colors cursor-pointer disabled:opacity-40"
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              ) : (
                /* Type: Command / File Write / Permission Approval */
                <div className="space-y-4">
                  <div className="flex items-start gap-3">
                    <div className="p-2 rounded-full bg-error/10 text-error shrink-0">
                      <span className="material-symbols-outlined text-2xl" style={{ fontVariationSettings: "'FILL' 1" }}>
                        warning
                      </span>
                    </div>
                    <div className="flex-1">
                      <h3 className="font-ui-label-bold text-ui-label-bold text-error text-base mb-1">
                        Approval Required
                      </h3>
                      <p className="font-ui-label-reg text-ui-label-reg text-on-surface text-xs leading-relaxed">
                        Agent intends to execute{" "}
                        <span className="font-mono text-error font-semibold bg-error/10 px-1.5 py-0.5 rounded">
                          {pendingTask.pending_action.command || pendingTask.pending_action.target || pendingTask.pending_action.details || "destructive action"}
                        </span>
                        . Review and authorize to continue execution.
                      </p>
                    </div>
                  </div>

                  <div className="flex justify-end gap-3 pt-2">
                    <button
                      onClick={() => handleRejectAction(activeJob!.id, pendingTask.id)}
                      disabled={Boolean(actionInProgress)}
                      className="px-6 py-2 rounded-full border border-outline text-on-surface font-ui-label-bold text-ui-label-bold hover:bg-surface-variant transition-colors cursor-pointer text-xs"
                    >
                      DENY ACTION
                    </button>
                    <button
                      onClick={() => handleApproveAction(activeJob!.id, pendingTask.id)}
                      disabled={Boolean(actionInProgress)}
                      className="px-6 py-2 rounded-full bg-primary-container text-[#001f24] font-ui-label-bold text-ui-label-bold hover:bg-primary-fixed transition-colors shadow-lg cursor-pointer flex items-center gap-1.5 text-xs"
                    >
                      {actionInProgress ? <Loader2 size={12} className="animate-spin" /> : <Check size={14} />}
                      <span>APPROVE</span>
                    </button>
                  </div>
                </div>
              )}
            </div>
          ) : (
            /* Idle Policy Card */
            <div className="rounded-xl border border-surface-container-high/60 bg-surface-container-low/40 p-5 flex items-center justify-between">
              <div className="flex items-center gap-3">
                <div className="w-9 h-9 rounded-full bg-secondary-container/20 border border-secondary-container/40 flex items-center justify-center text-secondary">
                  <span className="material-symbols-outlined text-[18px]">verified_user</span>
                </div>
                <div>
                  <div className="text-xs font-semibold text-on-surface">Deterministic Policy Engine Active</div>
                  <div className="text-[11px] text-on-surface-variant mt-0.5">Destructive filesystem, command executions, and clarifications will pause here for authorization.</div>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* ΓöÇΓöÇ Right Column: Execution Flow & Live Terminal Logs ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ */}
        <div className="flex flex-col gap-6">
          {/* Card 1: Real Execution Flow Steps */}
          <div className="bg-surface-container-low rounded-xl border border-surface-container-high p-6 flex flex-col gap-4 shadow-lg flex-1">
            <div className="flex justify-between items-center border-b border-surface-variant pb-3">
              <div className="flex items-center gap-2 text-on-surface font-ui-label-bold text-ui-label-bold">
                <span className="material-symbols-outlined text-primary-container text-lg">account_tree</span>
                <span>Execution Flow</span>
              </div>
              <span className="text-[11px] font-mono text-on-surface-variant">
                {activeJob?.tasks ? `${activeJob.tasks.filter((t) => t.status === "completed").length}/${activeJob.tasks.length} completed` : "Idle"}
              </span>
            </div>

            {/* Steps Timeline */}
            <div className="space-y-4 py-2 flex-1 overflow-y-auto max-h-[340px]">
              {activeJob?.tasks && activeJob.tasks.length > 0 ? (
                activeJob.tasks.map((task, index) => {
                  const isNodeActive = task.status === "running";
                  const isCompleted = task.status === "completed";
                  const isFailed = task.status === "failed";

                  return (
                    <div key={task.id} className="flex items-start gap-4 relative group">
                      {index < activeJob.tasks.length - 1 && (
                        <div className="absolute left-4 top-8 bottom-[-16px] w-[2px] bg-surface-variant" />
                      )}

                      {/* Step Indicator */}
                      <div className={`w-8 h-8 rounded-full flex items-center justify-center shrink-0 border z-10 transition-all ${
                        isNodeActive
                          ? "bg-primary-container/20 border-primary-container text-primary-container shadow-[0_0_12px_rgba(0,218,243,0.4)] animate-pulse"
                          : isCompleted
                            ? "bg-emerald-500/20 border-emerald-500 text-emerald-400"
                            : isFailed
                              ? "bg-error/20 border-error text-error"
                              : "bg-surface-container-high border-surface-variant text-outline-variant"
                      }`}>
                        {isCompleted ? (
                          <Check size={14} />
                        ) : isFailed ? (
                          <X size={14} />
                        ) : (
                          <span className="text-xs font-mono font-bold">{index + 1}</span>
                        )}
                      </div>

                      {/* Step Content */}
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center justify-between">
                          <h4 className={`font-ui-label-bold text-ui-label-bold truncate ${
                            isNodeActive ? "text-primary-container font-bold" : "text-on-surface"
                          }`}>
                            Step {index + 1}: {task.agent_role?.toUpperCase()}
                          </h4>
                          <span className={`px-2.5 py-0.5 rounded-full font-caption text-[10px] uppercase font-bold tracking-wider ${
                            isNodeActive
                              ? "bg-primary-container/15 text-primary-container border border-primary-container/30"
                              : isCompleted
                                ? "bg-emerald-500/15 text-emerald-400"
                                : isFailed
                                  ? "bg-error/20 text-error"
                                  : "text-outline-variant bg-surface-variant/40"
                          }`}>
                            {task.status}
                          </span>
                        </div>
                        <p className="font-caption text-caption text-on-surface-variant mt-0.5 font-mono">
                          {task.title}
                        </p>

                        {/* Structured Output (if any) */}
                        {task.structured_output?.files_modified && task.structured_output.files_modified.length > 0 && (
                          <div className="flex flex-wrap gap-1.5 mt-2">
                            {task.structured_output.files_modified.map((file, fi) => (
                              <span key={fi} className="px-2 py-0.5 bg-[#131315] border border-surface-variant rounded text-[10px] font-mono text-on-surface-variant flex items-center gap-1">
                                <FileCode size={11} className="text-primary-container" />
                                <span>{file.split(/[\\/]/).pop()}</span>
                              </span>
                            ))}
                          </div>
                        )}
                      </div>
                    </div>
                  );
                })
              ) : (
                <div className="h-full flex flex-col items-center justify-center p-8 text-center text-xs text-on-surface-variant/50 space-y-2">
                  <span className="material-symbols-outlined text-3xl text-outline-variant">account_tree</span>
                  <p>No active workflow running. Generate a plan above to begin execution.</p>
                </div>
              )}
            </div>
          </div>

          {/* Card 2: Live Terminal Logs & Task Steering Chat */}
          <div className="bg-[#131315] rounded-xl border border-surface-container-high p-4 flex flex-col h-[320px] shadow-lg">
            <div className="flex justify-between items-center border-b border-surface-variant pb-2.5 mb-2.5">
              {/* Tab Selector */}
              <div className="flex items-center gap-1 bg-[#0d0f18] p-0.5 rounded-lg border border-white/5">
                <button
                  type="button"
                  onClick={() => setRightPanelTab("logs")}
                  className={`flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-semibold transition-all cursor-pointer ${
                    rightPanelTab === "logs"
                      ? "bg-primary/20 text-primary border border-primary/30 shadow-[0_0_10px_rgba(0,218,243,0.15)]"
                      : "text-on-surface-variant hover:text-white"
                  }`}
                >
                  <Terminal size={12} className={rightPanelTab === "logs" ? "text-primary" : "text-on-surface-variant"} />
                  <span>Live Logs</span>
                </button>
                <button
                  type="button"
                  onClick={() => setRightPanelTab("steering")}
                  data-testid="tab-task-steering"
                  className={`flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-semibold transition-all cursor-pointer relative ${
                    rightPanelTab === "steering"
                      ? "bg-primary/20 text-primary border border-primary/30 shadow-[0_0_10px_rgba(0,218,243,0.15)]"
                      : "text-on-surface-variant hover:text-white"
                  }`}
                >
                  <MessageSquare size={12} className={rightPanelTab === "steering" ? "text-primary" : "text-on-surface-variant"} />
                  <span>Steering Chat</span>
                  {activeJob?.status === "paused" && (
                    <span className="w-2 h-2 rounded-full bg-amber-400 animate-pulse" />
                  )}
                </button>
              </div>

              {/* Right status & metrics */}
              <div className="flex items-center gap-2.5">
                {(() => {
                  let tokenCount = 0;
                  let costEst = 0;
                  if (activeJob?.logs) {
                    for (let i = activeJob.logs.length - 1; i >= 0; i--) {
                      const l = activeJob.logs[i];
                      const match = l.match(/Task Total:\s*~?([\d,]+)\s*tokens?(?:\s*\(\s*~?\$([\d.]+)\s*\))?/i);
                      if (match) {
                        tokenCount = parseInt(match[1].replace(/,/g, ""), 10) || 0;
                        costEst = parseFloat(match[2]) || 0;
                        break;
                      }
                    }
                  }
                  if (tokenCount > 0) {
                    return (
                      <div className="flex items-center gap-1 px-2 py-0.5 rounded-full bg-primary/10 border border-primary/20 text-[10px] font-mono text-primary font-medium">
                        <Sparkles size={11} />
                        <span>{tokenCount.toLocaleString()} tokens</span>
                        {costEst > 0 && <span className="text-on-surface-variant text-[9px] font-normal">(${costEst.toFixed(4)})</span>}
                      </div>
                    );
                  }
                  return null;
                })()}
                <span className={`w-2 h-2 rounded-full ${isRunning ? "bg-primary-container animate-pulse shadow-[0_0_8px_rgba(0,218,243,0.6)]" : "bg-surface-variant"}`} />
              </div>
            </div>

            {/* Content: Logs View */}
            {rightPanelTab === "logs" ? (
              <div className="flex-1 overflow-y-auto font-mono text-[11px] space-y-1.5 pr-2 leading-relaxed">
                {activeJob?.logs && activeJob.logs.length > 0 ? (
                  activeJob.logs.map((log, i) => {
                    const isInfo = log.includes("INFO:") || log.includes("[INFO]");
                    const isSuccess = log.includes("SUCCESS:") || log.includes("completed");
                    const isWarn = log.includes("WARN:") || log.includes("[WARNING]");
                    const isHalt = log.includes("HALT:") || log.includes("ERROR:") || log.includes("[ERROR]");

                    return (
                      <div key={i} className="flex gap-2">
                        <span className={`${
                          isSuccess
                            ? "text-primary-container font-semibold"
                            : isInfo
                              ? "text-emerald-400"
                              : isWarn
                                ? "text-tertiary-container"
                                : isHalt
                                  ? "text-error font-semibold"
                                  : "text-on-surface-variant"
                        }`}>
                          {log}
                        </span>
                      </div>
                    );
                  })
                ) : (
                  <div className="text-outline-variant italic py-8 text-center text-xs">
                    {isRunning ? "Waiting for initial agent log output..." : "Agent logs will stream here during task execution."}
                  </div>
                )}
                {isRunning && activeJob?.status === "paused" && (
                  <div className="text-amber-400 font-bold flex items-center gap-2 pt-1 animate-pulse">
                    <span>●</span>
                    <span>PAUSED: AWAITING OPERATOR INPUT...</span>
                  </div>
                )}
                <div ref={logsEndRef} />
              </div>
            ) : (
              /* Content: Task Steering Chat View */
              <div className="flex-1 flex flex-col min-h-0">
                {/* Steering History & Suggestions */}
                <div className="flex-1 overflow-y-auto space-y-2.5 pr-1 text-xs mb-2">
                  {/* Paused/Interrupted Alert Banner */}
                  {activeJob?.status === "paused" && (
                    <div className="p-2.5 rounded-lg bg-amber-500/15 border border-amber-500/30 flex items-center justify-between gap-2">
                      <div className="flex items-center gap-2 text-amber-300 text-xs font-semibold">
                        <AlertCircle size={14} className="shrink-0 text-amber-400 animate-pulse" />
                        <span>Workflow paused. Ready for operator steering.</span>
                      </div>
                      <button
                        type="button"
                        onClick={() => handleSendSteering("continue")}
                        disabled={isSteeringSubmitting}
                        className="px-2.5 py-1 rounded bg-amber-400 text-black font-bold text-[11px] hover:bg-amber-300 transition-colors cursor-pointer shrink-0"
                      >
                        Resume
                      </button>
                    </div>
                  )}

                  {/* Steering Quick Action Chips */}
                  <div className="space-y-1">
                    <span className="text-[10px] uppercase font-bold text-on-surface-variant/70 tracking-wider">
                      Quick Steering Actions
                    </span>
                    <div className="flex flex-wrap gap-1.5">
                      <button
                        type="button"
                        onClick={() => handleSendSteering("continue")}
                        disabled={!activeJob || isSteeringSubmitting}
                        className="px-2 py-1 rounded-md text-[11px] font-mono bg-white/5 hover:bg-white/10 text-on-surface border border-white/10 transition-colors cursor-pointer disabled:opacity-40"
                      >
                        ⚡ Continue what you stopped
                      </button>
                      <button
                        type="button"
                        onClick={() => handleSendSteering("retry")}
                        disabled={!activeJob || isSteeringSubmitting}
                        className="px-2 py-1 rounded-md text-[11px] font-mono bg-white/5 hover:bg-white/10 text-on-surface border border-white/10 transition-colors cursor-pointer disabled:opacity-40"
                      >
                        ↺ Retry current step
                      </button>
                      <button
                        type="button"
                        onClick={() => handleSendSteering("skip_tests", "Skip unit test phase and proceed to finalization")}
                        disabled={!activeJob || isSteeringSubmitting}
                        className="px-2 py-1 rounded-md text-[11px] font-mono bg-white/5 hover:bg-white/10 text-on-surface border border-white/10 transition-colors cursor-pointer disabled:opacity-40"
                      >
                        ⏩ Skip tests & finalize
                      </button>
                    </div>
                  </div>

                  {/* Recorded Steering Directives */}
                  <div className="space-y-1.5 pt-1">
                    <span className="text-[10px] uppercase font-bold text-on-surface-variant/70 tracking-wider">
                      Steering Directive History
                    </span>
                    {steeringHistory.length > 0 ? (
                      steeringHistory.map((item) => (
                        <div
                          key={item.id}
                          className="p-2 rounded-lg bg-surface-container-low border border-surface-container-high/60 flex items-start gap-2"
                        >
                          <div className="p-1 rounded bg-primary/10 text-primary mt-0.5 shrink-0">
                            <CornerDownLeft size={11} />
                          </div>
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center justify-between text-[10px] text-on-surface-variant">
                              <span className="font-mono font-bold text-primary">{item.action.toUpperCase()}</span>
                              <span>{new Date(item.timestamp).toLocaleTimeString()}</span>
                            </div>
                            {item.directive && (
                              <p className="text-xs text-on-surface mt-0.5 leading-tight font-sans">
                                {item.directive}
                              </p>
                            )}
                          </div>
                        </div>
                      ))
                    ) : (
                      <div className="p-3 text-center text-xs text-on-surface-variant/60 italic bg-surface-container-lowest/50 rounded-lg border border-white/5">
                        No steering directives sent yet. Send instructions above or below to steer the active agents.
                      </div>
                    )}
                  </div>
                </div>

                {/* Operator Prompt Input */}
                <form
                  onSubmit={(e) => {
                    e.preventDefault();
                    if (steeringInput.trim()) {
                      handleSendSteering("steer");
                    }
                  }}
                  className="flex items-center gap-1.5 pt-2 border-t border-surface-variant shrink-0"
                >
                  <input
                    type="text"
                    value={steeringInput}
                    onChange={(e) => setSteeringInput(e.target.value)}
                    disabled={!activeJob || isSteeringSubmitting}
                    placeholder={
                      activeJob
                        ? "Type steering instruction for agent..."
                        : "Start a workflow to steer tasks..."
                    }
                    className="flex-1 bg-[#0d0f18] border border-white/10 rounded-lg px-2.5 py-1.5 text-xs text-white placeholder:text-on-surface-variant/50 focus:outline-none focus:border-primary/60 font-sans disabled:opacity-40"
                  />
                  <button
                    type="submit"
                    disabled={!activeJob || !steeringInput.trim() || isSteeringSubmitting}
                    className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-semibold bg-primary text-black hover:bg-primary/90 transition-all cursor-pointer disabled:opacity-40 shadow-sm shrink-0"
                  >
                    {isSteeringSubmitting ? (
                      <Loader2 size={12} className="animate-spin" />
                    ) : (
                      <Send size={12} />
                    )}
                    <span>Steer</span>
                  </button>
                </form>
              </div>
            )}
          </div>
        </div>
      </div>
        </>
      )}
      <FilePreviewModal />
    </div>
  );
}
