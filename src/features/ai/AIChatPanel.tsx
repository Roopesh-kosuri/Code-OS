import { useEffect, useState, useCallback, useRef } from "react";
import {
  Bot,
  Copy,
  Paperclip,
  RotateCcw,
  Square,
  ChevronDown,
  ChevronUp,
  History,
  Plus,
  Trash2,
  Edit2,
  Check,
  X,
  FileDiff,
  Mic,
  MicOff,
  Send,
  Loader2,
  Eye,
  Image as ImageIcon,
  MessageSquare,
  Cpu,
  ArrowRight,
  Code2,
  GitBranch,
} from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { ProviderSelector, type ProviderConfig } from "../../components/ui/ProviderSelector";
import { getPreset } from "../../lib/providerPresets";
import { useAIStore, type ExtendedChatMessage, type ChatThread, type AttachedImage, type CheckpointInfo } from "../../stores/aiStore";
import { useEditorStore } from "../../stores/editorStore";
import { useWorkspaceStore } from "../../stores/workspaceStore";
import { api } from "../../lib/api";
import { AgentStatusIndicator } from "./AgentStatusIndicator";
import { DockedApprovalCard } from "./DockedApprovalCard";
import { Sparkles, Zap, CheckCircle2, XCircle, ExternalLink, AlertTriangle } from "lucide-react";

function parseProposals(text: string) {
  const proposals: { path: string; original: string; updated: string }[] = [];
  const regex = /\[PROPOSAL:\s*([^\]]+)\]\s*<<<<(?: ORIGINAL)?\r?\n([\s\S]*?)\r?\n====\r?\n([\s\S]*?)\r?\n>{3,}/g;
  let match;
  while ((match = regex.exec(text)) !== null) {
    proposals.push({
      path: match[1].trim(),
      original: match[2],
      updated: match[3],
    });
  }
  let cleanText = text.replace(
    regex,
    (m, path) => `\n*(Pending code changes proposed for \`${path}\` — inspect changes below)*\n`
  );

  // Clean raw agent control blocks (these are rendered in the AgentStatusIndicator)
  cleanText = cleanText.replace(/\[PLAN\][\s\S]*?\[\/PLAN\]/gi, "");
  cleanText = cleanText.replace(/\[TOOL_CALL:[^\]]+\][\s\S]*?\[\/TOOL_CALL\]/gi, "");
  cleanText = cleanText.replace(/\[TOOL_RESULT:[^\]]+\][\s\S]*?\[\/TOOL_RESULT\]/gi, "");
  cleanText = cleanText.replace(/\[DONE\]/gi, "");
  cleanText = cleanText.replace(/\[ESCALATE\]/gi, "");
  cleanText = cleanText.trim();

  return { cleanText, proposals };
}

function ChatCodeBlock({ language, code }: { language: string; code: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = () => {
    void navigator.clipboard.writeText(code);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="bg-[#0a0a0c] border border-surface-variant rounded-lg overflow-hidden my-2.5 select-text font-mono text-xs shadow-inner w-full min-w-0 max-w-full">
      <div className="bg-surface-container-high px-3 py-1.5 flex justify-between items-center border-b border-surface-variant select-none">
        <span className="font-caption text-caption text-on-surface-variant uppercase text-[10px] font-bold">{language || "code"}</span>
        <button
          type="button"
          onClick={handleCopy}
          className="text-on-surface-variant hover:text-primary transition-colors flex items-center gap-1 text-[11px] cursor-pointer"
        >
          {copied ? <><Check size={12} /> Copied</> : <><Copy size={12} /> Copy</>}
        </button>
      </div>
      <pre className="p-3 overflow-x-auto w-full min-w-0 max-w-full leading-relaxed text-on-surface font-code-sm text-code-sm">
        <code className="break-normal whitespace-pre block">{code}</code>
      </pre>
    </div>
  );
}

function ProposalCard({ path, original, updated }: { path: string; original: string; updated: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = () => {
    void navigator.clipboard.writeText(updated);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleOpenDiff = () => {
    window.dispatchEvent(new CustomEvent("code-os:switch-top-view", { detail: "proposals" }));
  };

  return (
    <div className="mt-3 rounded-xl border border-primary-container/30 bg-primary-container/5 p-4 space-y-3 text-xs shadow-md">
      <div className="flex items-center justify-between border-b border-surface-variant pb-2">
        <div className="flex items-center gap-2 font-ui-label-bold text-ui-label-bold text-on-surface truncate">
          <FileDiff size={14} className="text-primary-container shrink-0" />
          <span className="truncate">{path.split(/[\\/]/).pop() ?? path}</span>
        </div>
        <span className="rounded-full bg-primary-container/10 border border-primary-container/20 px-2 py-0.5 text-[9px] text-primary font-bold uppercase shrink-0">
          PROPOSAL
        </span>
      </div>

      <div className="flex justify-between items-center gap-2 pt-1">
        <button
          onClick={handleOpenDiff}
          className="flex items-center gap-1.5 px-3 py-1 rounded-full bg-primary-container text-[#001f24] font-bold text-[11px] hover:bg-primary-fixed transition-colors shadow-sm cursor-pointer"
        >
          <Eye size={12} /> Open Diff Inspector
        </button>
        <button
          onClick={handleCopy}
          className="text-on-surface-variant hover:text-on-surface text-[11px] transition-colors cursor-pointer"
        >
          {copied ? "Copied!" : "Copy code"}
        </button>
      </div>
    </div>
  );
}

export function AIChatPanel() {
  const [prompt, setPrompt] = useState("");
  const [attachedPaths, setAttachedPaths] = useState<string[]>([]);
  const [attachedImages, setAttachedImages] = useState<AttachedImage[]>([]);
  const [showProviderConfig, setShowProviderConfig] = useState(false);
  const [configuredKeys, setConfiguredKeys] = useState<string[]>([]);
  const [showDrawer, setShowDrawer] = useState(false);
  const [historySearch, setHistorySearch] = useState("");
  const [isListening, setIsListening] = useState(false);
  const [clarificationInput, setClarificationInput] = useState("");

  const fileInputRef = useRef<HTMLInputElement>(null);
  const imageInputRef = useRef<HTMLInputElement>(null);


  const messages = useAIStore((s) => s.messages);
  const models = useAIStore((s) => s.models);
  const model = useAIStore((s) => s.model);
  const preset = useAIStore((s) => s.preset);
  const baseUrl = useAIStore((s) => s.baseUrl);
  const streaming = useAIStore((s) => s.streaming);
  const error = useAIStore((s) => s.error);
  const threads = useAIStore((s) => s.threads);
  const currentThreadId = useAIStore((s) => s.currentThreadId);

  // Agent mode state
  const agentMode = useAIStore((s) => s.agentMode);
  const currentTier = useAIStore((s) => s.currentTier);
  const currentTierLabel = useAIStore((s) => s.currentTierLabel);
  const currentTokensUsed = useAIStore((s) => s.currentTokensUsed);
  const interruptedState = useAIStore((s) => s.interruptedState);
  const checkInterruptedState = useAIStore((s) => s.checkInterruptedState);
  const resumeInterruptedRun = useAIStore((s) => s.resumeInterruptedRun);
  const dismissInterruptedState = useAIStore((s) => s.dismissInterruptedState);
  const agentStatus = useAIStore((s) => s.agentStatus);
  const agentPlan = useAIStore((s) => s.agentPlan);
  const agentToolHistory = useAIStore((s) => s.agentToolHistory);
  const pendingApproval = useAIStore((s) => s.pendingApproval);
  const pendingApprovals = useAIStore((s) => s.pendingApprovals);
  const pendingUserResponse = useAIStore((s) => s.pendingUserResponse);
  const respondToUserQuestion = useAIStore((s) => s.respondToUserQuestion);
  const clearPendingUserResponse = useAIStore((s) => s.clearPendingUserResponse);
  const toggleAgentMode = useAIStore((s) => s.toggleAgentMode);
  const setAgentMode = useAIStore((s) => s.setAgentMode);
  const approveAction = useAIStore((s) => s.approveAction);
  const rejectAction = useAIStore((s) => s.rejectAction);
  const undoTurn = useAIStore((s) => s.undoTurn);

  const [undoingHash, setUndoingHash] = useState<string | null>(null);
  const [undoFeedback, setUndoFeedback] = useState<Record<string, string>>({});

  const handleUndoTurn = async (checkpoint: CheckpointInfo) => {
    setUndoingHash(checkpoint.commit_hash);
    try {
      const res = await undoTurn(checkpoint.commit_hash, checkpoint.touched_files);
      setUndoFeedback((prev) => ({
        ...prev,
        [checkpoint.commit_hash]: `✓ Restored ${res.restored_files.length} file(s) to pre-turn checkpoint`,
      }));
    } catch (err: any) {
      setUndoFeedback((prev) => ({
        ...prev,
        [checkpoint.commit_hash]: `Failed to undo: ${err?.message || err}`,
      }));
    } finally {
      setUndoingHash(null);
    }
  };

  const loadThreads = useAIStore((s) => s.loadThreads);
  const sendMessage = useAIStore((s) => s.sendMessage);
  const stopGeneration = useAIStore((s) => s.stopGeneration);
  const regenerate = useAIStore((s) => s.regenerate);
  const newThread = useAIStore((s) => s.newThread);
  const switchThread = useAIStore((s) => s.switchThread);
  const deleteThread = useAIStore((s) => s.deleteThread);
  const setPreset = useAIStore((s) => s.setPreset);
  const setModel = useAIStore((s) => s.setModel);
  const apiKeyProvider = useAIStore((s) => s.apiKeyProvider);
  const tokenUsage = useAIStore((s) => s.tokenUsage);
  const providerHealth = useAIStore((s) => s.providerHealth);
  const fetchTokenUsage = useAIStore((s) => s.fetchTokenUsage);
  const fetchProviderHealth = useAIStore((s) => s.fetchProviderHealth);

  const workspace = useWorkspaceStore((s) => s.currentWorkspace);

  useEffect(() => {
    void loadThreads(workspace?.path);
    void checkInterruptedState(workspace?.path);
    void fetchTokenUsage();
    void fetchProviderHealth();
    const interval = setInterval(() => {
      void fetchTokenUsage();
      void fetchProviderHealth();
    }, 10000);
    return () => clearInterval(interval);
  }, [workspace?.path, loadThreads, checkInterruptedState, fetchTokenUsage, fetchProviderHealth]);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape" && showDrawer) {
        setShowDrawer(false);
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [showDrawer]);
  const messagesEndRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  useEffect(() => {
    void api.get<{ provider_id: string; configured: boolean }[]>("/api/settings/api-keys")
      .then((k) => setConfiguredKeys(k.filter((x) => x.configured).map((x) => x.provider_id)))
      .catch(() => undefined);
  }, []);

  const providerValue: ProviderConfig = {
    preset,
    model,
    base_url: baseUrl,
  };

  const handleProviderChange = (cfg: ProviderConfig) => {
    if (cfg.preset !== preset || cfg.base_url !== baseUrl) {
      setPreset(cfg.preset, cfg.base_url, cfg.model);
    } else if (cfg.model !== model) {
      setModel(cfg.model);
    }
  };

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>, imageOnly = false) => {
    const files = e.target.files;
    if (!files || files.length === 0) return;

    Array.from(files).forEach((file) => {
      if (file.type.startsWith("image/") || /\.(png|jpe?g|webp|svg|gif|bmp)$/i.test(file.name)) {
        const reader = new FileReader();
        reader.onload = (ev) => {
          const dataUrl = ev.target?.result as string;
          if (dataUrl) {
            setAttachedImages((prev) => [
              ...prev,
              { name: file.name, dataUrl, size: file.size, type: file.type },
            ]);
          }
        };
        reader.readAsDataURL(file);
      } else if (!imageOnly) {
        setAttachedPaths((prev) => Array.from(new Set([...prev, file.name])));
      }
    });

    e.target.value = "";
  };

  const handlePaste = (e: React.ClipboardEvent) => {
    const items = e.clipboardData?.items;
    if (!items) return;
    for (let i = 0; i < items.length; i++) {
      if (items[i].type.startsWith("image/")) {
        const file = items[i].getAsFile();
        if (file) {
          e.preventDefault();
          const reader = new FileReader();
          reader.onload = (ev) => {
            const dataUrl = ev.target?.result as string;
            if (dataUrl) {
              setAttachedImages((prev) => [
                ...prev,
                { name: file.name || `Pasted Image ${prev.length + 1}.png`, dataUrl, size: file.size, type: file.type },
              ]);
            }
          };
          reader.readAsDataURL(file);
        }
      }
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    const files = e.dataTransfer.files;
    if (!files || files.length === 0) return;

    Array.from(files).forEach((file) => {
      if (file.type.startsWith("image/") || /\.(png|jpe?g|webp|svg|gif|bmp)$/i.test(file.name)) {
        const reader = new FileReader();
        reader.onload = (ev) => {
          const dataUrl = ev.target?.result as string;
          if (dataUrl) {
            setAttachedImages((prev) => [
              ...prev,
              { name: file.name, dataUrl, size: file.size, type: file.type },
            ]);
          }
        };
        reader.readAsDataURL(file);
      } else {
        setAttachedPaths((prev) => Array.from(new Set([...prev, file.name])));
      }
    });
  };

  return (
    <section data-testid="ai-chat-panel" className="flex flex-col h-full min-h-0 w-full min-w-0 overflow-hidden bg-surface-container-low text-on-surface font-ui-label-reg text-ui-label-reg relative select-none antialiased">
      {/* ── Header / Controls (Fluid, Non-cramped Layout) ───────── */}
      <div className="px-3 py-2.5 border-b border-surface-variant flex flex-col gap-2 bg-surface-container/60 shrink-0 relative z-40">
        {/* Row 1: Brand Title on Left + Utility Action Buttons on Right */}
        <div className="flex justify-between items-center min-w-0">
          <div className="flex items-center gap-2 font-bold text-xs text-on-surface whitespace-nowrap shrink-0">
            <span className="material-symbols-outlined text-primary text-lg">smart_toy</span>
            <span className="tracking-tight">Rony Agent</span>
            {currentTierLabel && (
              <span className="ml-1 inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold bg-white/5 border border-white/10 text-on-surface">
                <span>{currentTier === 0 ? "⚡" : (currentTier === 1 ? "🛠️" : "🧠")}</span>
                <span>{currentTierLabel}</span>
                {currentTokensUsed != null && (
                  <span className="text-on-surface-variant font-mono">({currentTokensUsed} tok)</span>
                )}
              </span>
            )}
          </div>

          <div className="flex items-center gap-1 text-on-surface-variant shrink-0">
            <button
              onClick={() => void newThread(workspace?.path)}
              className="p-1 hover:text-on-surface hover:bg-white/10 rounded-md transition-colors cursor-pointer"
              title="New Chat"
            >
              <Plus size={15} />
            </button>
            <button
              onClick={() => {
                setShowDrawer((v) => !v);
                setShowProviderConfig(false);
              }}
              className={`p-1 rounded-md transition-colors cursor-pointer ${
                showDrawer
                  ? "text-primary bg-primary/15 border border-primary/30"
                  : "hover:text-on-surface hover:bg-white/10"
              }`}
              title="Chat History"
            >
              <History size={15} />
            </button>
            <button
              onClick={() => {
                setShowProviderConfig((v) => !v);
                setShowDrawer(false);
              }}
              className={`p-1 rounded-md transition-colors cursor-pointer ${
                showProviderConfig
                  ? "text-primary bg-primary/15 border border-primary/30"
                  : "hover:text-on-surface hover:bg-white/10"
              }`}
              title="Configure AI Model"
            >
              {showProviderConfig ? <ChevronUp size={15} /> : <ChevronDown size={15} />}
            </button>
          </div>
        </div>

        {/* Row 2: Full-Width Responsive Mode Switcher (Chat | Agent) */}
        <div className="relative grid grid-cols-2 p-0.5 rounded-lg bg-[#0e1014] border border-white/[0.08] shadow-[inset_0_1px_3px_rgba(0,0,0,0.6)] select-none w-full h-[28px] items-center">
          {/* Sliding Pill Thumb */}
          <div
            className={`absolute top-0.5 bottom-0.5 w-[calc(50%-2px)] rounded-[6px] transition-all duration-200 ease-out pointer-events-none ${
              agentMode
                ? "left-[calc(50%+1px)] bg-gradient-to-b from-primary/25 to-primary/10 border border-primary/40 shadow-[0_0_10px_rgba(0,218,243,0.2)]"
                : "left-0.5 bg-gradient-to-b from-white/[0.14] to-white/[0.06] border border-white/15 shadow-[0_2px_4px_rgba(0,0,0,0.4)]"
            }`}
            style={{
              transitionTimingFunction: "cubic-bezier(0.16, 1, 0.3, 1)",
            }}
          />
          <button
            type="button"
            onClick={() => setAgentMode(false)}
            className={`relative z-10 h-full rounded-[6px] text-[11px] font-medium transition-all duration-150 cursor-pointer flex items-center justify-center gap-1.5 active:scale-95 ${
              !agentMode
                ? "text-white font-semibold"
                : "text-on-surface-variant/70 hover:text-white"
            }`}
            title="Chat Mode: Ask questions, get explanations, and debug code"
          >
            <MessageSquare size={11} className={!agentMode ? "text-white" : "text-on-surface-variant/60"} />
            <span className="truncate">Chat</span>
          </button>
          <button
            type="button"
            onClick={() => setAgentMode(true)}
            className={`relative z-10 h-full rounded-[6px] text-[11px] font-medium transition-all duration-150 cursor-pointer flex items-center justify-center gap-1.5 active:scale-95 ${
              agentMode
                ? "text-primary font-bold tracking-wide"
                : "text-on-surface-variant/70 hover:text-primary/80"
            }`}
            title="Agent Mode: Rony Agent autonomously reads/edits files, executes tools, and verifies tests"
          >
            <Sparkles
              size={11}
              className={`transition-transform duration-200 ${
                agentMode
                  ? "text-primary scale-110 drop-shadow-[0_0_6px_var(--primary)]"
                  : "text-on-surface-variant/60"
              }`}
            />
            <span className="truncate">Agent</span>
          </button>
        </div>

        {/* Row 3: Model Selector Button / Popover */}
        {!showProviderConfig ? (
          <button
            onClick={() => {
              setShowProviderConfig(true);
              setShowDrawer(false);
            }}
            className="w-full bg-[#16181f]/80 hover:bg-[#1c1e28] border border-white/10 hover:border-primary/40 rounded-lg px-2.5 py-1.5 flex items-center justify-between transition-all duration-200 cursor-pointer shadow-xs group min-w-0"
          >
            <div className="flex items-center gap-2 min-w-0 flex-1 overflow-hidden">
              <div className="w-4 h-4 rounded-md bg-primary/20 border border-primary/30 flex items-center justify-center overflow-hidden shrink-0 text-primary group-hover:scale-105 transition-transform">
                <Sparkles size={10} />
              </div>
              <div className="flex items-center gap-1.5 truncate min-w-0">
                <span className="font-bold text-[11px] text-on-surface shrink-0">
                  {preset ? getPreset(preset)?.label : "Auto"}
                </span>
                <span className="text-[10px] text-on-surface-variant font-mono truncate">
                  {model ? model : "auto-select"}
                </span>
              </div>
            </div>
            <div className="w-4 h-4 rounded flex items-center justify-center text-on-surface-variant group-hover:text-primary transition-colors shrink-0 ml-1">
              <ChevronDown size={12} />
            </div>
          </button>
        ) : (
          <div className="relative z-50 animate-popover-in">
            <ProviderSelector
              value={providerValue}
              onChange={handleProviderChange}
              configuredKeys={configuredKeys}
              models={models}
              onClose={() => setShowProviderConfig(false)}
              compact
            />
          </div>
        )}
      </div>

      {/* ── Thread History Drawer (Full Z-[60] Overlay, No Overlap) ────────── */}
      {showDrawer && (
        <div className="absolute inset-0 bg-[#0d0e14]/98 backdrop-blur-xl z-[60] flex flex-col p-4 space-y-3 animate-fade-in shadow-2xl">
          {/* Drawer Header */}
          <div className="flex justify-between items-center border-b border-white/10 pb-3">
            <div className="flex items-center gap-2">
              <div className="w-6 h-6 rounded-lg bg-primary/20 border border-primary/30 flex items-center justify-center text-primary">
                <History size={13} />
              </div>
              <span className="font-bold text-xs text-on-surface uppercase tracking-wider">
                Conversation History
              </span>
            </div>
            <div className="flex items-center gap-1.5">
              <button
                onClick={() => {
                  void newThread(workspace?.path);
                  setShowDrawer(false);
                }}
                className="px-2.5 py-1 bg-primary/10 hover:bg-primary/20 border border-primary/30 rounded-lg text-primary text-[11px] font-medium flex items-center gap-1 transition-all cursor-pointer hover:shadow-sm"
                title="Start a new chat"
              >
                <Plus size={13} />
                <span>New Chat</span>
              </button>
              <button
                onClick={() => setShowDrawer(false)}
                className="p-1 rounded-lg text-on-surface-variant hover:text-on-surface hover:bg-white/10 transition-colors cursor-pointer"
                title="Close (Esc)"
              >
                <X size={16} />
              </button>
            </div>
          </div>

          {/* Search bar if multiple conversations */}
          {threads.length > 3 && (
            <div className="relative">
              <input
                type="text"
                value={historySearch}
                onChange={(e) => setHistorySearch(e.target.value)}
                placeholder="Search conversations..."
                className="w-full bg-[#161822] border border-white/10 rounded-xl px-3 py-1.5 text-xs text-on-surface placeholder:text-on-surface-variant/50 focus:outline-none focus:border-primary/50"
              />
              {historySearch && (
                <button
                  onClick={() => setHistorySearch("")}
                  className="absolute right-2.5 top-1/2 -translate-y-1/2 text-on-surface-variant hover:text-on-surface"
                >
                  <X size={12} />
                </button>
              )}
            </div>
          )}

          {/* Conversations List */}
          <div className="flex-1 overflow-y-auto space-y-1.5 pr-0.5 custom-scrollbar">
            {threads.length === 0 ? (
              <div className="flex flex-col items-center justify-center h-48 text-center text-xs text-on-surface-variant/50 space-y-2 select-none">
                <History size={28} className="text-white/20" />
                <p>No past conversations yet</p>
                <button
                  onClick={() => {
                    void newThread(workspace?.path);
                    setShowDrawer(false);
                  }}
                  className="text-primary hover:underline text-[11px] font-medium"
                >
                  Start a new conversation
                </button>
              </div>
            ) : (
              threads
                .filter((t) => !historySearch || t.title.toLowerCase().includes(historySearch.toLowerCase()))
                .map((t) => {
                  const isActive = currentThreadId === t.id;
                  return (
                    <div
                      key={t.id}
                      className={`group w-full flex items-center justify-between p-2.5 rounded-xl border text-xs transition-all cursor-pointer ${
                        isActive
                          ? "bg-primary/10 border-primary/40 text-primary font-semibold shadow-sm"
                          : "bg-[#161822]/80 border-white/5 text-on-surface-variant hover:text-on-surface hover:bg-[#1e202e] hover:border-white/15"
                      }`}
                      onClick={async () => {
                        await switchThread(t.id);
                        setShowDrawer(false);
                      }}
                    >
                      <div className="flex items-center gap-2.5 min-w-0 flex-1">
                        <div
                          className={`w-2 h-2 rounded-full shrink-0 ${
                            isActive ? "bg-primary shadow-[0_0_8px_var(--primary)]" : "bg-white/20"
                          }`}
                        />
                        <span className="truncate">{t.title || "Untitled Conversation"}</span>
                      </div>
                      <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            void deleteThread(t.id);
                          }}
                          className="p-1 rounded-md text-on-surface-variant hover:text-error hover:bg-error/10 transition-colors"
                          title="Delete thread"
                        >
                          <Trash2 size={12} />
                        </button>
                      </div>
                    </div>
                  );
                })
            )}
          </div>
        </div>
      )}

      {/* ── Chat Messages Stream ───────────────────────────────────────────── */}
      <div className="flex-1 overflow-y-auto overflow-x-hidden p-3.5 flex flex-col gap-4 select-text min-w-0 w-full max-w-full">
        {interruptedState && (
          <div className="p-3 rounded-xl bg-amber-500/10 border border-amber-500/30 flex items-center justify-between text-xs shadow-md">
            <div className="flex items-center gap-2.5 min-w-0">
              <div className="w-6 h-6 rounded-lg bg-amber-500/20 text-amber-400 flex items-center justify-center shrink-0">
                <RotateCcw size={13} />
              </div>
              <div className="min-w-0">
                <div className="font-bold text-amber-300 truncate">Interrupted Task Available</div>
                <div className="text-[11px] text-on-surface-variant truncate">
                  {interruptedState.user_query || `Step ${interruptedState.iteration + 1}`} ({interruptedState.tokens_used || 0} tokens used)
                </div>
              </div>
            </div>
            <div className="flex items-center gap-1.5 shrink-0 ml-2">
              <button
                type="button"
                onClick={() => void resumeInterruptedRun(workspace?.path)}
                className="px-2.5 py-1 bg-amber-500/20 hover:bg-amber-500/30 border border-amber-500/40 text-amber-200 rounded-lg font-semibold text-[11px] transition-all cursor-pointer"
              >
                Resume
              </button>
              <button
                type="button"
                onClick={() => void dismissInterruptedState(workspace?.path)}
                className="p-1 text-on-surface-variant hover:text-white rounded transition-colors cursor-pointer"
                title="Dismiss"
              >
                <X size={13} />
              </button>
            </div>
          </div>
        )}

        {messages.length === 0 ? (
          !agentMode ? (
            /* Chat Mode Empty State — Lightweight coding & questions + Mode switcher guidance */
            <div className="flex flex-col items-center justify-center my-auto p-4 max-w-sm mx-auto text-center space-y-4 select-none animate-fade-in">
              {/* Main Badge & Title */}
              <div className="flex flex-col items-center space-y-2">
                <div className="w-10 h-10 rounded-2xl bg-white/[0.06] border border-white/10 flex items-center justify-center text-on-surface shadow-inner">
                  <MessageSquare size={18} className="text-white/90" />
                </div>
                <div className="space-y-1">
                  <h3 className="font-bold text-xs text-white tracking-wide">
                    Lightweight Coding & Questions
                  </h3>
                  <p className="text-[11px] text-on-surface-variant/80 leading-relaxed max-w-[270px]">
                    Fast answers for syntax doubts, debugging snippets, logic reviews, and coding questions.
                  </p>
                </div>
              </div>

              {/* Mode Guidance & Switcher Recommendation Cards */}
              <div className="w-full space-y-2 pt-1 text-left">
                {/* 1. Medium - Large Coding -> Switch to Rony Agent */}
                <button
                  type="button"
                  onClick={() => setAgentMode(true)}
                  className="w-full text-left p-3 rounded-xl bg-gradient-to-r from-primary/10 via-primary/5 to-transparent border border-primary/25 hover:border-primary/50 hover:bg-primary/15 transition-all duration-200 group cursor-pointer shadow-xs"
                >
                  <div className="flex items-center justify-between mb-1">
                    <div className="flex items-center gap-1.5 text-primary text-xs font-bold">
                      <Sparkles size={13} className="group-hover:scale-110 transition-transform" />
                      <span>Medium – Large Coding</span>
                    </div>
                    <span className="text-[10px] font-semibold text-primary px-1.5 py-0.5 rounded bg-primary/20 flex items-center gap-0.5 group-hover:translate-x-0.5 transition-transform">
                      Switch to Agent <ArrowRight size={10} />
                    </span>
                  </div>
                  <p className="text-[10.5px] text-on-surface-variant/75 leading-normal">
                    For autonomous multi-file edits, terminal execution, and verified testing, switch to <span className="text-primary font-medium">Rony Agent</span>.
                  </p>
                </button>

                {/* 2. Huge Projects -> Switch to Agent Console */}
                <button
                  type="button"
                  onClick={() => {
                    window.dispatchEvent(new CustomEvent("code-os:menu-action", { detail: "view.switchTopView:agent" }));
                  }}
                  className="w-full text-left p-3 rounded-xl bg-[#14161f]/80 border border-white/10 hover:border-white/20 hover:bg-[#1a1d28] transition-all duration-200 group cursor-pointer shadow-xs"
                >
                  <div className="flex items-center justify-between mb-1">
                    <div className="flex items-center gap-1.5 text-on-surface text-xs font-bold">
                      <Cpu size={13} className="text-secondary group-hover:scale-110 transition-transform" />
                      <span>Huge Projects</span>
                    </div>
                    <span className="text-[10px] font-semibold text-on-surface-variant px-1.5 py-0.5 rounded bg-white/5 flex items-center gap-0.5 group-hover:text-white group-hover:translate-x-0.5 transition-transform">
                      Agent Console <ExternalLink size={10} />
                    </span>
                  </div>
                  <p className="text-[10.5px] text-on-surface-variant/75 leading-normal">
                    For full project generation, architecture DAGs, and multi-agent workflows, switch to <span className="text-white font-medium">Agent Console</span>.
                  </p>
                  <div className="mt-2 flex items-center gap-1.5 text-[10px] text-amber-300/90 bg-amber-500/10 rounded-md px-2 py-1 border border-amber-500/20">
                    <AlertTriangle size={11} className="text-amber-400 shrink-0" />
                    <span>Caution: Running small tasks in Agent workflows costs more tokens and time. Use Chat for quick edits.</span>
                  </div>
                </button>
              </div>
            </div>
          ) : (
            /* Agent Mode Empty State — Autonomous Execution */
            <div className="flex flex-col items-center justify-center my-auto p-4 max-w-sm mx-auto text-center space-y-4 select-none animate-fade-in">
              <div className="flex flex-col items-center space-y-2">
                <div className="w-10 h-10 rounded-2xl bg-primary/15 border border-primary/30 flex items-center justify-center text-primary shadow-[0_0_16px_rgba(0,218,243,0.2)]">
                  <Sparkles size={20} className="animate-pulse" />
                </div>
                <div className="space-y-1">
                  <h3 className="font-bold text-xs text-white tracking-wide">
                    Rony Autonomous Coding Agent
                  </h3>
                  <p className="text-[11px] text-on-surface-variant/80 leading-relaxed max-w-[270px]">
                    Describe your goal. Rony Agent will inspect files, apply edits, run terminal commands, and verify test passes.
                  </p>
                </div>
              </div>

              {/* Quick Prompt Starters */}
              <div className="w-full flex flex-col gap-1.5 pt-1">
                <button
                  type="button"
                  onClick={() => setPrompt("Create a new feature module and verify tests")}
                  className="w-full text-left px-3 py-2 rounded-lg bg-white/[0.04] hover:bg-white/[0.08] border border-white/5 text-[11px] text-on-surface-variant hover:text-white transition-colors cursor-pointer flex items-center gap-1.5"
                >
                  <Sparkles size={11} className="text-primary shrink-0" />
                  <span>"Create a new feature module and verify tests"</span>
                </button>
                <button
                  type="button"
                  onClick={() => setPrompt("Find and fix any bugs or edge cases in this file")}
                  className="w-full text-left px-3 py-2 rounded-lg bg-white/[0.04] hover:bg-white/[0.08] border border-white/5 text-[11px] text-on-surface-variant hover:text-white transition-colors cursor-pointer flex items-center gap-1.5"
                >
                  <Code2 size={11} className="text-secondary shrink-0" />
                  <span>"Find and fix any bugs or edge cases in this file"</span>
                </button>
              </div>
            </div>
          )
        ) : null}

        {error && (
          <div className="rounded-xl border border-error/40 bg-error/10 p-3 text-xs text-error">
            {error}
          </div>
        )}

        {messages.map((message, index) => {
          const isUser = message.role === "user";
          const { cleanText, proposals } = parseProposals(message.content);
          const isStreamingMessage = streaming && !isUser && index === messages.length - 1;

          return isUser ? (
            /* User Message Bubble */
            <div key={index} className="flex flex-col gap-1.5 items-end animate-message-in">
              {message.attached_images && message.attached_images.length > 0 && (
                <div className="flex flex-wrap gap-2 justify-end">
                  {message.attached_images.map((img, iIdx) => (
                    <div
                      key={iIdx}
                      className="rounded-xl overflow-hidden border border-white/15 bg-black/40 shadow-md max-w-[220px]"
                    >
                      <img src={img.dataUrl} alt={img.name} className="max-h-40 w-auto object-cover rounded-t-lg" />
                      <div className="px-2 py-1 bg-surface-container-high/90 text-[10px] font-mono truncate text-on-surface-variant">
                        {img.name}
                      </div>
                    </div>
                  ))}
                </div>
              )}
              {cleanText && (
                <div className="bg-surface-variant text-on-surface px-3.5 py-2 rounded-2xl rounded-tr-sm max-w-[88%] font-ui-label-reg text-ui-label-reg text-xs leading-relaxed shadow-sm break-words [overflow-wrap:anywhere] overflow-hidden">
                  {cleanText}
                </div>
              )}
            </div>
          ) : (
            /* AI Response Card (Stitch Elevation 2 Card) */
            <div key={index} className="flex flex-col gap-2 items-start w-full animate-message-in">
              <div className="flex items-center gap-2 px-1">
                <span className="material-symbols-outlined text-primary text-[18px]">smart_toy</span>
                <span className="font-caption text-caption text-on-surface-variant">
                  {message.agentStatus || agentMode ? "Rony Agent" : "Rony"}
                </span>
              </div>

              <div className="bg-[#1e1f24] text-on-surface p-3.5 rounded-xl shadow-[0_4px_20px_rgba(0,0,0,0.15)] ring-1 ring-white/5 w-full min-w-0 max-w-full space-y-2.5 overflow-hidden transition-all duration-200">
                {/* Agent Status & Thinking Indicator */}
                {(message.agentStatus || message.agentPlan || (index === messages.length - 1 && (agentStatus || agentPlan || agentToolHistory.length > 0))) && (
                  <AgentStatusIndicator
                    status={message.agentStatus || (index === messages.length - 1 ? agentStatus : null)}
                    plan={message.agentPlan || (index === messages.length - 1 ? agentPlan : null)}
                    toolHistory={
                      (message.agentToolHistory && message.agentToolHistory.length > 0)
                        ? message.agentToolHistory
                        : (message.commands && message.commands.length > 0)
                          ? message.commands.map(c => ({
                              tool: "run_command",
                              detail: c.command,
                              timestamp: message.created_at || new Date().toISOString(),
                              success: c.success,
                            }))
                          : (index === messages.length - 1 ? agentToolHistory : [])
                    }
                    streaming={streaming && index === messages.length - 1}
                  />
                )}

                {cleanText ? (
                  <div className="markdown-body font-ui-label-reg text-ui-label-reg text-xs leading-relaxed break-words [overflow-wrap:anywhere] min-w-0 max-w-full overflow-hidden">
                    <ReactMarkdown
                      remarkPlugins={[remarkGfm]}
                      components={{
                        code({ className, children }) {
                          const match = /language-(\w+)/.exec(className || "");
                          const code = String(children).replace(/\n$/, "");
                          if (match) {
                            return <ChatCodeBlock language={match[1]} code={code} />;
                          }
                          return (
                            <code className="bg-[#0a0a0c] text-primary px-1.5 py-0.5 rounded font-mono text-[11px] border border-white/5 break-words [overflow-wrap:anywhere]">
                              {children}
                            </code>
                          );
                        },
                      }}
                    >
                      {cleanText}
                    </ReactMarkdown>
                    {isStreamingMessage && <span className="streaming-caret" />}
                  </div>
                ) : isStreamingMessage ? (
                  <div className="text-xs text-primary/70 flex items-center gap-1.5 py-1">
                    <Loader2 size={13} className="animate-spin text-primary" />
                    <span className="shimmer-text">Generating response...</span>
                  </div>
                ) : message.agentStatus?.type === "error" ? (
                  <div className="text-xs text-rose-400/90 bg-rose-500/10 border border-rose-500/20 rounded-lg p-2.5 space-y-1">
                    <div className="font-semibold flex items-center gap-1.5 text-rose-300">
                      <AlertTriangle size={14} />
                      <span>{message.agentStatus.message || "Provider Error"}</span>
                    </div>
                  </div>
                ) : null}

                {/* Live Terminal / Command & Edit Receipts Feed */}
                {message.commands && message.commands.length > 0 && (
                  <div className="space-y-2 pt-1">
                    {message.commands.map((cmd, cIdx) => {
                      const isEdit = cmd.command.startsWith("edit ") || cmd.command.startsWith("edit_file ");
                      const filePath = isEdit ? cmd.command.replace(/^edit(?:_file)?\s+/, "").trim() : "";

                      if (isEdit) {
                        return (
                          <div
                            key={cIdx}
                            className={`flex items-center justify-between px-3 py-2 rounded-lg border text-xs font-mono shadow-sm transition-all animate-success-pop ${
                              cmd.success
                                ? "bg-emerald-500/10 border-emerald-500/30 text-emerald-300"
                                : "bg-rose-500/10 border-rose-500/30 text-rose-300"
                            }`}
                          >
                            <div className="flex items-center gap-2 min-w-0 flex-1">
                              {cmd.success ? (
                                <CheckCircle2 size={15} className="text-emerald-400 shrink-0" />
                              ) : (
                                <XCircle size={15} className="text-rose-400 shrink-0" />
                              )}
                              <span className="font-semibold text-[11.5px] truncate">
                                {cmd.success ? "✓ Approved edit to" : "✗ Denied edit to"}{" "}
                                <span className="underline decoration-dotted text-white font-mono">{filePath}</span>
                              </span>
                            </div>
                            {cmd.success && (
                              <button
                                type="button"
                                onClick={() =>
                                  window.dispatchEvent(
                                    new CustomEvent("code-os:switch-top-view", { detail: "proposals" })
                                  )
                                }
                                className="text-[10.5px] text-primary hover:underline flex items-center gap-1 cursor-pointer shrink-0 ml-2 font-sans font-medium interactive-scale"
                              >
                                <ExternalLink size={11} /> Diff
                              </button>
                            )}
                          </div>
                        );
                      }

                      // Check for denied / timed out terminal commands
                      const isRejected =
                        !cmd.success &&
                        (cmd.output?.includes("rejected by user") ||
                          cmd.output?.includes("timed out") ||
                          cmd.output?.includes("User rejected"));

                      if (isRejected) {
                        return (
                          <div
                            key={cIdx}
                            className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-rose-500/10 border border-rose-500/30 text-rose-300 font-mono text-xs shadow-sm"
                          >
                            <XCircle size={14} className="text-rose-400 shrink-0" />
                            <span className="font-semibold text-[11px] truncate">
                              ✗ Denied: <span className="text-rose-200">{cmd.command}</span>
                            </span>
                          </div>
                        );
                      }

                      // Regular terminal execution output card
                      return (
                        <div
                          key={cIdx}
                          className="rounded-lg bg-[#0d0e11] border border-white/10 overflow-hidden font-mono text-xs shadow-inner"
                        >
                          <div className="flex items-center justify-between px-3 py-1.5 bg-[#16171b] border-b border-white/5 text-[11px]">
                            <div className="flex items-center gap-2 min-w-0 flex-1 truncate">
                              <span className="text-amber-400 font-bold">$</span>
                              <span className="text-on-surface truncate font-semibold">{cmd.command}</span>
                            </div>
                            <span
                              className={`px-1.5 py-0.5 rounded text-[9.5px] font-bold shrink-0 ml-2 ${
                                cmd.success
                                  ? "bg-emerald-500/20 text-emerald-300 border border-emerald-500/30"
                                  : "bg-rose-500/20 text-rose-300 border border-rose-500/30"
                              }`}
                            >
                              exit: {cmd.exit_code}
                            </span>
                          </div>
                          <div className="p-2.5 text-[11px] text-[#c9d1d9] leading-relaxed max-h-48 overflow-y-auto whitespace-pre-wrap select-text bg-black/50">
                            {cmd.output || "(no output)"}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}

                {/* Proposals Card */}
                {proposals.map((p, pIdx) => (
                  <ProposalCard key={pIdx} path={p.path} original={p.original} updated={p.updated} />
                ))}

                {/* Turn Checkpoint & Undo Action */}
                {message.checkpoint && message.checkpoint.touched_files?.length > 0 && (
                  <div className="pt-2.5 mt-1 border-t border-white/10 flex items-center justify-between gap-2 flex-wrap">
                    <div className="flex items-center gap-1.5 text-[11px] text-on-surface-variant font-mono truncate">
                      <GitBranch size={12} className="text-primary/70 shrink-0" />
                      <span className="truncate">
                        Checkpoint: <code className="text-cyan-300 font-bold bg-black/40 px-1 py-0.5 rounded">{message.checkpoint.commit_hash.slice(0, 7)}</code> ({message.checkpoint.touched_files.length} modified file{message.checkpoint.touched_files.length > 1 ? "s" : ""})
                      </span>
                    </div>

                    {message.checkpoint.undone || undoFeedback[message.checkpoint.commit_hash]?.startsWith("✓") ? (
                      <span className="text-[10.5px] text-emerald-300 font-semibold flex items-center gap-1 bg-emerald-500/10 px-2 py-0.5 rounded-full border border-emerald-500/20">
                        <Check size={11} /> Turn Undone
                      </span>
                    ) : (
                      <button
                        type="button"
                        disabled={undoingHash === message.checkpoint.commit_hash}
                        onClick={() => handleUndoTurn(message.checkpoint!)}
                        className="px-2.5 py-1 rounded-md bg-white/5 hover:bg-white/10 border border-white/10 hover:border-amber-500/40 text-on-surface hover:text-amber-200 text-[11px] font-medium transition-all flex items-center gap-1.5 cursor-pointer disabled:opacity-50 interactive-scale"
                        title="Revert only the files modified during this turn back to pre-turn state"
                      >
                        <RotateCcw size={11} className={undoingHash === message.checkpoint.commit_hash ? "animate-spin text-amber-400" : "text-amber-400"} />
                        <span>{undoingHash === message.checkpoint.commit_hash ? "Reverting..." : "Undo turn"}</span>
                      </button>
                    )}
                  </div>
                )}
              </div>
            </div>
          );
        })}

        {streaming && !agentMode && (
          <div className="flex items-center gap-2 text-primary text-xs px-2 animate-pulse">
            <Loader2 size={14} className="animate-spin" />
            <span>Thinking…</span>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* ── Docked Approval Card (Pinned Directly Above Chat Input) ───────── */}
      {pendingApproval && (
        <DockedApprovalCard
          pendingApproval={pendingApproval}
          pendingApprovals={pendingApprovals}
          onApprove={approveAction}
          onReject={rejectAction}
        />
      )}

      {/* ── Interactive Clarification Card (ask_user) ──────────────────────── */}
      {pendingUserResponse && (
        <div className="border-t border-b px-4 py-3 shrink-0 bg-[#12141a]/95 border-primary/40 shadow-lg z-20 animate-docked-in backdrop-blur-xl">
          <div className="flex items-center justify-between gap-2 mb-2">
            <div className="flex items-center gap-2">
              <div className="p-1 rounded-md bg-primary/20 text-primary">
                <Bot size={14} />
              </div>
              <span className="font-bold text-xs text-primary">Clarification Requested</span>
            </div>
            <button
              type="button"
              onClick={() => clearPendingUserResponse()}
              className="text-on-surface-variant hover:text-on-surface p-1 rounded hover:bg-surface-variant/40 transition-colors cursor-pointer"
              title="Dismiss clarification"
            >
              <X size={14} />
            </button>
          </div>
          <p className="text-xs text-on-surface mb-2.5 leading-relaxed">{pendingUserResponse.question}</p>
          <div className="flex flex-wrap gap-1.5 mb-2.5">
            {pendingUserResponse.options.map((opt, oIdx) => (
              <button
                key={oIdx}
                type="button"
                onClick={() => {
                  void respondToUserQuestion(pendingUserResponse.action_id, opt);
                }}
                className="px-3 py-1.5 rounded-full bg-primary/15 hover:bg-primary/25 text-primary border border-primary/30 text-xs font-medium cursor-pointer transition-all hover:scale-[1.02] active:scale-[0.98]"
              >
                {opt}
              </button>
            ))}
          </div>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              if (clarificationInput.trim()) {
                void respondToUserQuestion(pendingUserResponse.action_id, clarificationInput.trim());
                setClarificationInput("");
              }
            }}
            className="flex items-center gap-1.5"
          >
            <input
              type="text"
              value={clarificationInput}
              onChange={(e) => setClarificationInput(e.target.value)}
              placeholder="Or type a custom answer..."
              className="flex-1 bg-surface-container-high/60 border border-outline-variant/40 rounded-lg px-2.5 py-1 text-xs text-on-surface placeholder:text-on-surface-variant/50 focus:outline-none focus:border-primary/60"
            />
            <button
              type="submit"
              disabled={!clarificationInput.trim()}
              className="px-3 py-1 rounded-lg bg-primary text-on-primary font-medium text-xs disabled:opacity-40 disabled:cursor-not-allowed hover:bg-primary/90 transition-colors cursor-pointer"
            >
              Send
            </button>
          </form>
        </div>
      )}

      {/* ── Chat Input Container (Google Stitch Footer) ───────────────────── */}
      <div className="px-3.5 pt-2 pb-2.5 border-t border-surface-variant bg-surface-container/80 backdrop-blur-md shrink-0 transition-all duration-200">
        {/* Hidden File Inputs */}
        <input
          ref={fileInputRef}
          type="file"
          multiple
          onChange={(e) => handleFileSelect(e, false)}
          className="hidden"
        />
        <input
          ref={imageInputRef}
          type="file"
          accept="image/*,.png,.jpg,.jpeg,.webp,.svg,.gif"
          multiple
          onChange={(e) => handleFileSelect(e, true)}
          className="hidden"
        />

        <form
          onSubmit={(e) => {
            e.preventDefault();
            if ((!prompt.trim() && attachedImages.length === 0) || streaming) return;
            const text = prompt;
            const currentImages = [...attachedImages];
            const currentPaths = [...attachedPaths];
            setPrompt("");
            setAttachedImages([]);
            setAttachedPaths([]);
            void sendMessage(text, currentPaths, currentImages);
          }}
          onDragOver={(e) => e.preventDefault()}
          onDrop={handleDrop}
          className="bg-[#1e1f24] rounded-xl overflow-hidden border border-transparent focus-within:border-primary/50 focus-within:ring-1 focus-within:ring-primary/20 transition-all duration-200 shadow-md"
        >
          {/* Attachment Preview Chips */}
          {(attachedImages.length > 0 || attachedPaths.length > 0) && (
            <div className="flex flex-wrap gap-1.5 p-1.5 border-b border-white/5 bg-[#14151a]/90 max-h-24 overflow-y-auto">
              {attachedImages.map((img, idx) => (
                <div
                  key={`img-${idx}`}
                  className="flex items-center gap-1.5 px-2 py-0.5 rounded-lg bg-primary/10 border border-primary/25 text-xs text-on-surface shadow-xs animate-fade-in group"
                >
                  <img
                    src={img.dataUrl}
                    alt={img.name}
                    className="w-4 h-4 rounded object-cover shrink-0 border border-white/10"
                  />
                  <span className="truncate max-w-[110px] font-mono text-[10px]">{img.name}</span>
                  <button
                    type="button"
                    onClick={() => setAttachedImages((prev) => prev.filter((_, i) => i !== idx))}
                    className="text-on-surface-variant hover:text-error transition-colors p-0.5 cursor-pointer"
                    title="Remove image"
                  >
                    <X size={11} />
                  </button>
                </div>
              ))}
              {attachedPaths.map((p, idx) => (
                <div
                  key={`path-${idx}`}
                  className="flex items-center gap-1 px-2 py-0.5 rounded-lg bg-surface-variant/80 border border-white/10 text-xs text-on-surface shadow-xs animate-fade-in"
                >
                  <Paperclip size={10} className="text-secondary shrink-0" />
                  <span className="truncate max-w-[120px] font-mono text-[10px]">{p}</span>
                  <button
                    type="button"
                    onClick={() => setAttachedPaths((prev) => prev.filter((_, i) => i !== idx))}
                    className="text-on-surface-variant hover:text-error transition-colors p-0.5 cursor-pointer"
                    title="Remove attachment"
                  >
                    <X size={11} />
                  </button>
                </div>
              ))}
            </div>
          )}

          <textarea
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            onPaste={handlePaste}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                if ((prompt.trim() || attachedImages.length > 0) && !streaming) {
                  const text = prompt;
                  const currentImages = [...attachedImages];
                  const currentPaths = [...attachedPaths];
                  setPrompt("");
                  setAttachedImages([]);
                  setAttachedPaths([]);
                  void sendMessage(text, currentPaths, currentImages);
                }
              }
            }}
            placeholder={
              agentMode
                ? "Describe the coding task for Rony Agent… (e.g. build feature, fix bug, run tests)"
                : "Ask a coding question… (For medium/large tasks, switch to Agent above)"
            }
            rows={2}
            className="w-full bg-transparent border-none focus:ring-0 text-on-surface font-ui-label-reg text-ui-label-reg placeholder:text-outline-variant resize-none px-3 pt-2.5 pb-1 outline-none text-xs no-scrollbar"
          />

          <div className="flex justify-between items-center px-2 pb-2 pt-0.5">
            <div className="flex items-center gap-1 text-on-surface-variant">
              {/* Dedicated Image Upload Button */}
              <button
                type="button"
                onClick={() => imageInputRef.current?.click()}
                className="p-1 hover:text-primary hover:bg-primary/10 rounded-lg transition-colors cursor-pointer interactive-scale"
                title="Upload image / screenshot (or paste Ctrl+V)"
              >
                <ImageIcon size={15} />
              </button>

              {/* Attach File Button */}
              <button
                type="button"
                onClick={() => fileInputRef.current?.click()}
                className="p-1 hover:text-primary hover:bg-primary/10 rounded-lg transition-colors cursor-pointer interactive-scale"
                title="Attach file / context"
              >
                <Paperclip size={15} />
              </button>

              {/* Voice Input */}
              <button
                type="button"
                onClick={() => setIsListening(!isListening)}
                className={`p-1 rounded-lg transition-colors cursor-pointer interactive-scale ${
                  isListening ? "text-error bg-error/10 animate-pulse" : "hover:text-primary hover:bg-primary/10"
                }`}
                title="Voice input"
              >
                {isListening ? <MicOff size={15} /> : <Mic size={15} />}
              </button>
            </div>

            {streaming ? (
              <button
                type="button"
                onClick={stopGeneration}
                className="bg-error/90 hover:bg-error text-on-error px-3 py-1 rounded-full flex items-center gap-1.5 text-xs font-semibold transition-all cursor-pointer shadow-md interactive-scale"
                title="Cancel active run"
              >
                <Square size={11} fill="currentColor" />
                <span>Cancel</span>
              </button>
            ) : (
              <button
                type="submit"
                disabled={!prompt.trim() && attachedImages.length === 0}
                className="w-7 h-7 rounded-full bg-primary-container text-on-primary-container flex items-center justify-center hover:bg-primary transition-all duration-150 disabled:opacity-40 cursor-pointer shadow-md interactive-scale"
                title="Send Message"
              >
                <span className="material-symbols-outlined text-[17px] leading-none">arrow_upward</span>
              </button>
            )}
          </div>
        </form>

        <div className="text-center mt-1.5 select-none">
          <span className="font-caption text-[10px] text-outline-variant">AI generated code may contain errors.</span>
        </div>
      </div>
    </section>
  );
}
