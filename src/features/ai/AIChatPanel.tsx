import { useEffect, useState, useCallback, useRef } from "react";
import {
  Bot,
  Copy,
  Paperclip,
  RefreshCw,
  RotateCcw,
  Send,
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
  MessageSquare,
  FileCode,
  Sparkles,
  Eye,
  Mic,
  MicOff,
} from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { Button } from "../../components/ui/Button";
import { IconButton } from "../../components/ui/IconButton";
import { ProviderSelector, type ProviderConfig } from "../../components/ui/ProviderSelector";
import { useAIStore, type ExtendedChatMessage, type ChatThread } from "../../stores/aiStore";
import { useEditorStore } from "../../stores/editorStore";
import { useWorkspaceStore } from "../../stores/workspaceStore";
import { api } from "../../lib/api";

// ── Chat animation styles ──────────────────────────────────────────────────────
const CHAT_ANIMATIONS = `
  @keyframes chatFadeIn {
    from { opacity: 0; transform: translateY(6px); }
    to   { opacity: 1; transform: translateY(0); }
  }
  .chat-msg-in {
    animation: chatFadeIn 0.22s ease both;
  }
  @keyframes thinkDot {
    0%, 80%, 100% { opacity: 0.2; transform: scale(0.7); }
    40%           { opacity: 1;   transform: scale(1); }
  }
  .think-dot {
    display: inline-block;
    width: 6px; height: 6px;
    border-radius: 50%;
    background: currentColor;
    animation: thinkDot 1.2s infinite ease-in-out;
  }
  .think-dot:nth-child(2) { animation-delay: 0.18s; }
  .think-dot:nth-child(3) { animation-delay: 0.36s; }
`;

// ── Helpers ───────────────────────────────────────────────────────────────────


function getRelativeTime(isoString: string | undefined): string {
  if (!isoString) return "just now";
  try {
    const date = new Date(isoString);
    const now = new Date();
    const seconds = Math.floor((now.getTime() - date.getTime()) / 1000);
    if (seconds < 10) return "just now";
    if (seconds < 60) return `${seconds}s ago`;
    const minutes = Math.floor(seconds / 60);
    if (minutes < 60) return `${minutes}m ago`;
    const hours = Math.floor(minutes / 60);
    if (hours < 24) return `${hours}h ago`;
    const days = Math.floor(hours / 24);
    return `${days}d ago`;
  } catch {
    return "just now";
  }
}

/** Parses [PROPOSAL: path] <<<< ORIGINAL ... ==== ... >>>> blocks */
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
  const cleanText = text.replace(
    regex,
    (m, path) => `\n*(Pending code changes proposed for \`${path}\` — inspect changes below)*\n`
  );
  return { cleanText, proposals };
}

// ── Proposal Card Sub-component ──────────────────────────────────────────────

function ProposalCard({ path, original, updated }: { path: string; original: string; updated: string }) {
  const [copied, setCopied] = useState(false);
  const originalLines = original.split("\n").slice(0, 3);
  const updatedLines = updated.split("\n").slice(0, 3);

  const handleCopy = () => {
    void navigator.clipboard.writeText(updated);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleOpenDiff = () => {
    // Focus the Diff Viewer panel
    window.dispatchEvent(new CustomEvent("code-os:switch-utility", { detail: "diff" }));
  };

  return (
    <div className="mt-3 rounded-lg border border-accent-500/25 bg-accent-500/5 p-3 space-y-2 text-xs">
      <div className="flex items-center justify-between border-b border-surface-700 pb-1.5">
        <div className="flex items-center gap-1.5 font-semibold text-slate-200 truncate">
          <FileDiff size={13} className="text-accent-500 shrink-0" />
          <span className="truncate" title={path}>{path.split(/[\\/]/).pop() ?? path}</span>
        </div>
        <span className="rounded bg-accent-500/10 border border-accent-500/20 px-1 py-0.5 text-[9px] text-accent-400 font-bold uppercase shrink-0">
          PROPOSAL
        </span>
      </div>

      {/* Diff snippet preview */}
      <div className="rounded bg-surface-950 font-mono text-[10px] p-2 overflow-x-auto leading-normal max-h-24 border border-surface-800">
        {originalLines.map((line, idx) => (
          <div key={`orig-${idx}`} className="text-rose-400/90 whitespace-pre truncate">- {line}</div>
        ))}
        {updatedLines.map((line, idx) => (
          <div key={`upd-${idx}`} className="text-emerald-400/90 whitespace-pre truncate">+ {line}</div>
        ))}
      </div>

      <div className="flex justify-between items-center gap-2 pt-1">
        <button
          onClick={handleOpenDiff}
          className="flex items-center gap-1 text-[10px] text-accent-400 hover:text-accent-300 font-bold tracking-wide transition-colors"
        >
          <Eye size={11} /> Open Diff Inspector
        </button>
        <button
          onClick={handleCopy}
          className="text-[10px] text-slate-400 hover:text-white transition-colors"
        >
          {copied ? "Copied" : "Copy replacement"}
        </button>
      </div>
    </div>
  );
}

// ── Code Block with Copy overlay ──────────────────────────────────────────────

function ChatCodeBlock({ language, code }: { language: string; code: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = () => {
    void navigator.clipboard.writeText(code);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="rounded-lg overflow-hidden border border-surface-700 bg-surface-950 my-2 select-text font-mono text-xs">
      <div className="bg-surface-900 border-b border-surface-800 px-3 py-1 flex items-center justify-between text-[10px] text-slate-500 select-none">
        <span>{language || "code"}</span>
        <button
          type="button"
          onClick={handleCopy}
          className="flex items-center gap-1 hover:text-slate-200 transition-colors"
        >
          {copied ? <><Check size={11} /> Copied</> : <><Copy size={11} /> Copy</>}
        </button>
      </div>
      <pre className="p-3 overflow-x-auto leading-relaxed text-slate-250">
        <code>{code}</code>
      </pre>
    </div>
  );
}

// ── Main Panel ────────────────────────────────────────────────────────────────

export function AIChatPanel() {
  const [prompt, setPrompt] = useState("");
  const [attachedPaths, setAttachedPaths] = useState<string[]>([]);
  const [showProviderConfig, setShowProviderConfig] = useState(false);
  const [configuredKeys, setConfiguredKeys] = useState<string[]>([]);

  // Multi-thread drawer state
  const [showDrawer, setShowDrawer] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [editingThreadId, setEditingThreadId] = useState<string | null>(null);
  const [editTitleValue, setEditTitleValue] = useState("");
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);

  // User message editing state
  const [editingMessageIdx, setEditingMessageIdx] = useState<number | null>(null);
  const [editMessageText, setEditMessageText] = useState("");

  const [attachedSizes, setAttachedSizes] = useState<Record<string, number>>({});

  // Store bindings
  const messages = useAIStore((s) => s.messages);
  const models = useAIStore((s) => s.models);
  const model = useAIStore((s) => s.model);
  const preset = useAIStore((s) => s.preset);
  const baseUrl = useAIStore((s) => s.baseUrl);
  const streaming = useAIStore((s) => s.streaming);
  const restrictedMode = useWorkspaceStore((s) => s.restrictedMode);
  const error = useAIStore((s) => s.error);
  const currentThreadId = useAIStore((s) => s.currentThreadId);
  const threads = useAIStore((s) => s.threads);

  const refreshModels = useAIStore((s) => s.refreshModels);
  const sendMessage = useAIStore((s) => s.sendMessage);
  const stopGeneration = useAIStore((s) => s.stopGeneration);
  const regenerate = useAIStore((s) => s.regenerate);
  const editMessage = useAIStore((s) => s.editMessage);
  const deleteMessagePair = useAIStore((s) => s.deleteMessagePair);
  const setPreset = useAIStore((s) => s.setPreset);
  const setModel = useAIStore((s) => s.setModel);

  const loadThreads = useAIStore((s) => s.loadThreads);
  const switchThread = useAIStore((s) => s.switchThread);
  const newThread = useAIStore((s) => s.newThread);
  const renameThread = useAIStore((s) => s.renameThread);
  const deleteThread = useAIStore((s) => s.deleteThread);

  const activePath = useEditorStore((s) => s.activePath);
  const workspace = useWorkspaceStore((s) => s.currentWorkspace);

  // Voice recognition states & ref
  const [isListening, setIsListening] = useState(false);
  const recognitionRef = useRef<any>(null);

  const startListening = useCallback(() => {
    const SpeechRecognition = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    if (!SpeechRecognition) {
      alert("Voice recognition is not supported in this browser.");
      return;
    }
    const recognition = new SpeechRecognition();
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.lang = "en-US";

    recognition.onstart = () => {
      setIsListening(true);
    };

    recognition.onresult = (event: any) => {
      let interimTranscript = "";
      let finalTranscript = "";

      for (let i = event.resultIndex; i < event.results.length; ++i) {
        if (event.results[i].isFinal) {
          finalTranscript += event.results[i][0].transcript;
        } else {
          interimTranscript += event.results[i][0].transcript;
        }
      }

      setPrompt((prev) => {
        const base = prev.trim();
        const addition = finalTranscript || interimTranscript;
        return base ? `${base} ${addition}` : addition;
      });
    };

    recognition.onerror = (event: any) => {
      console.error("Speech recognition error:", event.error);
      setIsListening(false);
    };

    recognition.onend = () => {
      setIsListening(false);
    };

    recognitionRef.current = recognition;
    recognition.start();
  }, []);

  const stopListening = useCallback(() => {
    if (recognitionRef.current) {
      recognitionRef.current.stop();
    }
    setIsListening(false);
  }, []);

  const toggleListening = () => {
    if (isListening) {
      stopListening();
    } else {
      startListening();
    }
  };

  // Sync keys + threads on workspace load
  const loadKeys = useCallback(async () => {
    try {
      const keys = await api.get<{ provider_id: string; configured: boolean }[]>("/api/settings/api-keys");
      setConfiguredKeys(keys.filter((k) => k.configured).map((k) => k.provider_id));
    } catch { /* ignore */ }
  }, []);

  useEffect(() => {
    if (workspace) {
      void loadThreads(workspace.path);
    }
    void loadKeys();
    void refreshModels().catch(() => undefined);
  }, [workspace, loadThreads, loadKeys, refreshModels]);

  // Load character sizes dynamically for attachments
  useEffect(() => {
    if (!workspace) return;
    attachedPaths.forEach((path) => {
      if (attachedSizes[path] === undefined) {
        setAttachedSizes((prev) => ({ ...prev, [path]: 0 })); // set temporary
        void api.get<{ content: string }>("/api/files/read", { workspace: workspace.path, path })
          .then((res) => setAttachedSizes((prev) => ({ ...prev, [path]: res.content.length })))
          .catch(() => undefined);
      }
    });
  }, [attachedPaths, attachedSizes, workspace]);

  // Total context character size calculation
  const totalChars = attachedPaths.reduce((acc, p) => acc + (attachedSizes[p] || 0), 0);
  const limitReached = totalChars >= 20000;

  // Sync ProviderSelector values
  const providerValue: ProviderConfig = {
    preset,
    model,
    base_url: baseUrl,
    api_key_provider: useAIStore.getState().apiKeyProvider ?? undefined,
  };

  const handleProviderChange = (cfg: ProviderConfig) => {
    setPreset(cfg.preset, cfg.base_url);
    if (cfg.model !== model) setModel(cfg.model);
  };

  const handleSwitchToApi = () => {
    const apiPreset = configuredKeys.find((id) => id !== "ollama");
    if (apiPreset) {
      setPreset(apiPreset);
      setShowProviderConfig(false);
      return;
    }
    setShowProviderConfig(true);
  };

  // Full message copy
  const handleCopyMessage = (content: string) => {
    void navigator.clipboard.writeText(content);
  };

  // Thread Rename triggers
  const handleStartRename = (thread: ChatThread) => {
    setEditingThreadId(thread.id);
    setEditTitleValue(thread.title);
  };

  const handleSaveRename = (threadId: string) => {
    if (editTitleValue.trim()) {
      void renameThread(threadId, editTitleValue.trim());
    }
    setEditingThreadId(null);
  };

  // User edit trigger
  const handleStartEdit = (idx: number, text: string) => {
    setEditingMessageIdx(idx);
    setEditMessageText(text);
  };

  const handleSaveEdit = (idx: number) => {
    if (editMessageText.trim()) {
      void editMessage(idx, editMessageText.trim());
    }
    setEditingMessageIdx(null);
  };

  // Auto-scroll messages area
  const messagesEndRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  return (
    <section className="grid h-full min-h-0 w-full min-w-0 grid-cols-1 grid-rows-[auto_minmax(0,1fr)_auto] border-l border-surface-700 bg-surface-900 relative">
      
      {/* ── Thread History Drawer Overlay ────────────────────────────────────── */}
      {showDrawer && (
        <div className="absolute inset-0 bg-surface-950/90 z-30 flex flex-col border-r border-surface-700 p-3 select-text">
          <div className="flex items-center justify-between border-b border-surface-750 pb-2 mb-3">
            <span className="text-xs font-bold uppercase tracking-wider text-slate-350">Conversations</span>
            <IconButton label="Close history" icon={<X size={15} />} onClick={() => setShowDrawer(false)} />
          </div>

          <input
            type="text"
            placeholder="Search threads…"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="mb-3 h-8 w-full rounded bg-surface-850 border border-surface-700 text-xs px-2 focus:outline-none focus:border-accent-500"
          />

          <div className="flex-1 overflow-y-auto space-y-1.5">
            {threads.filter((t) => t.title.toLowerCase().includes(searchQuery.toLowerCase())).length === 0 ? (
              <div className="text-center py-8 text-xs text-slate-500 select-none">
                No conversations found.
              </div>
            ) : (
              threads
                .filter((t) => t.title.toLowerCase().includes(searchQuery.toLowerCase()))
                .map((t) => {
                const isSelected = currentThreadId === t.id;
                const isEditing = editingThreadId === t.id;
                const isConfirming = confirmDeleteId === t.id;

                return (
                  <div
                    key={t.id}
                    className={`group relative rounded-lg p-2 flex flex-col justify-between border transition-all ${
                      isSelected
                        ? "bg-surface-800 border-accent-500/30"
                        : "bg-surface-900 border-surface-800 hover:border-surface-700"
                    }`}
                  >
                    {isEditing ? (
                      <div className="flex gap-1.5 items-center">
                        <input
                          type="text"
                          value={editTitleValue}
                          onChange={(e) => setEditTitleValue(e.target.value)}
                          className="h-6 flex-1 rounded bg-surface-950 border border-surface-700 text-[11px] px-1 focus:outline-none"
                          onKeyDown={(e) => {
                            if (e.key === "Enter") handleSaveRename(t.id);
                            if (e.key === "Escape") setEditingThreadId(null);
                          }}
                          autoFocus
                        />
                        <button onClick={() => handleSaveRename(t.id)} className="text-emerald-400 hover:text-emerald-350">
                          <Check size={12} />
                        </button>
                        <button onClick={() => setEditingThreadId(null)} className="text-rose-400 hover:text-rose-350">
                          <X size={12} />
                        </button>
                      </div>
                    ) : isConfirming ? (
                      <div className="flex items-center justify-between text-[10px]">
                        <span className="text-rose-400 font-semibold">Delete thread?</span>
                        <div className="flex gap-1.5">
                          <button
                            onClick={() => {
                              void deleteThread(t.id);
                              setConfirmDeleteId(null);
                            }}
                            className="text-rose-400 hover:text-rose-350 font-bold"
                          >
                            Yes
                          </button>
                          <button onClick={() => setConfirmDeleteId(null)} className="text-slate-400 hover:text-slate-200">
                            No
                          </button>
                        </div>
                      </div>
                    ) : (
                      <div
                        onClick={async () => {
                          await switchThread(t.id);
                          setShowDrawer(false);
                        }}
                        className="cursor-pointer"
                      >
                        <div className="text-xs font-semibold text-slate-250 truncate group-hover:text-white max-w-[85%]">
                          {t.title}
                        </div>
                        <span className="text-[9px] text-slate-500 mt-1 block">
                          {getRelativeTime(t.updated_at)}
                        </span>
                      </div>
                    )}

                    {/* Action buttons (rename/delete) visible on hover */}
                    {!isEditing && !isConfirming && (
                      <div className="absolute right-2 top-2 opacity-0 group-hover:opacity-100 flex gap-1 bg-surface-900 group-hover:bg-surface-800 rounded p-0.5 border border-surface-700/30">
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            handleStartRename(t);
                          }}
                          className="text-slate-500 hover:text-white p-0.5"
                          title="Rename thread"
                        >
                          <Edit2 size={10} />
                        </button>
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            setConfirmDeleteId(t.id);
                          }}
                          className="text-slate-500 hover:text-rose-400 p-0.5"
                          title="Delete thread"
                        >
                          <Trash2 size={10} />
                        </button>
                      </div>
                    )}
                  </div>
                );
              })
            )}
          </div>
        </div>
      )}

      {/* ── Header ────────────────────────────────────────────────────────────── */}
      <div className="border-b border-surface-700 px-3 py-2 space-y-2 z-10 select-none">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-slate-400">
            <Bot size={15} className="text-accent-500" />
            AI Chat
          </div>
          <div className="flex gap-0.5">
            <IconButton label="New Chat" icon={<Plus size={15} />} onClick={() => void newThread()} />
            <IconButton label="Chat history" icon={<History size={15} />} onClick={() => setShowDrawer(true)} />
            <IconButton label="Regenerate last" icon={<RotateCcw size={15} />} onClick={() => void regenerate()} disabled={streaming || messages.length === 0} />
            <IconButton label="Stop streaming" icon={<Square size={15} />} onClick={stopGeneration} disabled={!streaming} />
            <IconButton
              label={showProviderConfig ? "Hide provider" : "Configure provider"}
              icon={showProviderConfig ? <ChevronUp size={15} /> : <ChevronDown size={15} />}
              onClick={() => setShowProviderConfig((v) => !v)}
            />
          </div>
        </div>

        {/* Compact model display row — Clickable to toggle slide down config */}
        {!showProviderConfig && (
          <div
            onClick={() => setShowProviderConfig(true)}
            className="flex items-center justify-between text-[10px] text-slate-500 bg-surface-950/30 hover:bg-surface-950/60 hover:text-slate-350 rounded border border-surface-750 hover:border-surface-700 px-2.5 py-1 select-none cursor-pointer transition-all duration-150 group"
            title="Click to configure model/provider settings"
          >
            <span className="truncate flex items-center gap-1">
              Active model: <strong className="text-slate-350">{model || "Ollama default"}</strong>
            </span>
            <div className="flex items-center gap-1 shrink-0">
              {preset && <span className="capitalize text-accent-400 font-bold mr-1">{preset}</span>}
              <ChevronDown size={11} className="text-slate-500 group-hover:text-slate-400 transition-colors" />
            </div>
          </div>
        )}

        {/* Expanded ProviderSelector config */}
        {showProviderConfig && (
          <ProviderSelector
            value={providerValue}
            onChange={handleProviderChange}
            configuredKeys={configuredKeys}
            models={models}
            compact
          />
        )}
      </div>

      {/* ── Messages Display ──────────────────────────────────────────────────── */}
      <div className="min-h-0 overflow-y-auto px-3 py-3 space-y-4 select-text">
        {messages.length === 0 ? (
          <div className="text-xs text-slate-500 text-center py-6 leading-relaxed select-none">
            Start typing below to compose a query.<br />
            Select files to inject local context.
          </div>
        ) : null}

        {error ? (
          <div className="rounded-md border border-danger/40 bg-danger/5 p-2 text-xs text-danger space-y-2">
            <p>{error}</p>
            <div className="flex gap-2">
              <button type="button" onClick={() => void regenerate()} className="rounded border border-danger/40 px-2 py-1 text-[10px] font-semibold hover:bg-danger/10">Retry</button>
              <button type="button" onClick={handleSwitchToApi} className="rounded border border-danger/40 px-2 py-1 text-[10px] font-semibold hover:bg-danger/10">{configuredKeys.some((id) => id !== "ollama") ? "Switch to API" : "Configure API"}</button>
              <button type="button" onClick={() => void stopGeneration()} className="rounded border border-danger/40 px-2 py-1 text-[10px] font-semibold hover:bg-danger/10">Cancel</button>
            </div>
          </div>
        ) : null}

        {messages.map((message, index) => {
          const isUser = message.role === "user";
          const isEditing = editingMessageIdx === index;
          const { cleanText, proposals } = parseProposals(message.content);

          return (
            <div
              key={`${message.role}-${index}`}
              className={`chat-msg-in group flex flex-col space-y-1 relative rounded-lg p-3 transition-all ${
                isUser
                  ? "bg-surface-850 border border-surface-750/30"
                  : "bg-surface-950/20"
              }`}
            >
              {/* Message header */}
              <div className="flex items-center justify-between select-none pb-1.5 border-b border-surface-750/10">
                <div className="flex items-center gap-1.5">
                  <span className={`text-[10px] font-bold uppercase tracking-wider ${isUser ? "text-accent-400" : "text-slate-400"}`}>
                    {isUser ? "user" : "assistant"}
                  </span>
                  {!isUser && message.model && (
                    <span className="rounded bg-surface-800 border border-surface-700 px-1 py-px text-[9px] text-slate-500 font-semibold uppercase shrink-0">
                      {message.model}
                    </span>
                  )}
                </div>

                {/* Message action options (copy/edit/delete) shown on hover */}
                <div className="opacity-0 group-hover:opacity-100 flex gap-1 rounded bg-surface-900 p-0.5 border border-surface-750/30">
                  <button
                    onClick={() => handleCopyMessage(message.content)}
                    className="text-slate-500 hover:text-white p-0.5 transition-colors"
                    title="Copy message"
                  >
                    <Copy size={10} />
                  </button>
                  {isUser && !streaming && (
                    <button
                      onClick={() => handleStartEdit(index, message.content)}
                      className="text-slate-500 hover:text-white p-0.5 transition-colors"
                      title="Edit message"
                    >
                      <Edit2 size={10} />
                    </button>
                  )}
                  {!streaming && (
                    <button
                      onClick={() => deleteMessagePair(index)}
                      className="text-slate-500 hover:text-rose-400 p-0.5 transition-colors"
                      title="Delete query block"
                    >
                      <Trash2 size={10} />
                    </button>
                  )}
                </div>
              </div>

              {/* Message body */}
              <div className="text-xs leading-relaxed text-slate-200">
                {isEditing ? (
                  <div className="space-y-2 mt-1">
                    <textarea
                      value={editMessageText}
                      onChange={(e) => setEditMessageText(e.target.value)}
                      className="w-full min-h-16 rounded bg-surface-900 border border-surface-700 text-xs p-2 text-slate-100 focus:outline-none focus:border-accent-500"
                    />
                    <div className="flex gap-2">
                      <button
                        onClick={() => handleSaveEdit(index)}
                        className="rounded bg-accent-500 hover:bg-accent-600 text-white px-2 py-1 text-[10px] font-bold"
                      >
                        Save &amp; Submit
                      </button>
                      <button
                        onClick={() => setEditingMessageIdx(null)}
                        className="rounded bg-surface-800 text-slate-400 hover:text-white px-2 py-1 text-[10px] font-bold"
                      >
                        Cancel
                      </button>
                    </div>
                  </div>
                ) : !isUser && streaming && cleanText === "" ? (
                  <div className="flex items-center gap-1.5 text-slate-500 mt-2 ml-0.5" aria-label="Thinking">
                    <span className="think-dot" />
                    <span className="think-dot" />
                    <span className="think-dot" />
                  </div>
                ) : (
                  <div className="markdown-body mt-1">
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
                            <code className="rounded bg-surface-800 px-1 py-0.5 font-mono text-[11px] text-slate-300">
                              {children}
                            </code>
                          );
                        },
                        table({ children }) {
                          return (
                            <div className="my-2 overflow-x-auto rounded border border-surface-700 bg-surface-950/20">
                              <table className="w-full text-left text-[11px] border-collapse">{children}</table>
                            </div>
                          );
                        },
                        th({ children }) {
                          return (
                            <th className="border-b border-surface-700 bg-surface-900 px-2 py-1 font-semibold text-slate-300">
                              {children}
                            </th>
                          );
                        },
                        td({ children }) {
                          return <td className="border-b border-surface-800 px-2 py-1 text-slate-450">{children}</td>;
                        },
                      }}
                    >
                      {cleanText}
                    </ReactMarkdown>
                  </div>
                )}
              </div>

              {/* Proposals layout rendering */}
              {proposals.map((p, pIdx) => (
                <ProposalCard key={`prop-${pIdx}`} path={p.path} original={p.original} updated={p.updated} />
              ))}

              {/* Auditable attached paths preview */}
              {isUser && message.attached_paths && message.attached_paths.length > 0 && (
                <div className="pt-2 select-none border-t border-surface-750/5 mt-2">
                  <details className="text-[10px] text-slate-500 cursor-pointer">
                    <summary className="hover:text-slate-350 outline-none">
                      Attached context ({message.attached_paths.length} file)
                    </summary>
                    <div className="flex flex-wrap gap-1 mt-1.5">
                      {message.attached_paths.map((p) => (
                        <span key={p} className="rounded bg-surface-950 px-1.5 py-0.5 text-[9px] font-mono text-slate-400">
                          {p.split(/[\\/]/).pop()}
                        </span>
                      ))}
                    </div>
                  </details>
                </div>
              )}
            </div>
          );
        })}
        <div ref={messagesEndRef} />
      </div>

      {/* Inject animation keyframes */}
      <style>{CHAT_ANIMATIONS}</style>

      {/* ── Input Box Form ────────────────────────────────────────────────────── */}
      <form
        className="border-t border-surface-700 p-3 space-y-2 select-none z-10"
        onSubmit={(e) => {
          e.preventDefault();
          if (!prompt.trim() || streaming) return;
          const content = prompt;
          setPrompt("");
          void sendMessage(content, attachedPaths);
          setAttachedPaths([]); // Clear attached paths on send
        }}
      >
        {/* Attached tags list */}
        {attachedPaths.length > 0 && (
          <div className="flex flex-wrap gap-1 mb-1">
            {attachedPaths.map((p) => (
              <span
                key={p}
                className="inline-flex items-center gap-1 rounded bg-surface-800 px-1.5 py-0.5 text-[10px] text-slate-300 font-mono"
              >
                {p.split(/[\\/]/).pop()}
                <button
                  type="button"
                  onClick={() => setAttachedPaths((prev) => prev.filter((item) => item !== p))}
                  className="text-slate-500 hover:text-white transition-colors"
                >
                  <X size={10} />
                </button>
              </span>
            ))}
          </div>
        )}

        {/* Char usage limit indicator bar */}
        {attachedPaths.length > 0 && (
          <div className="space-y-1">
            <div className="flex items-center justify-between text-[9px] text-slate-500 font-semibold select-none">
              <span>Attached Context Size</span>
              <span className={limitReached ? "text-danger" : totalChars > 15000 ? "text-warning" : ""}>
                {totalChars.toLocaleString()} / 20,000 characters
              </span>
            </div>
            <div className="h-1 w-full bg-surface-800 rounded overflow-hidden">
              <div
                className={`h-full transition-all duration-300 ${
                  limitReached ? "bg-danger" : totalChars > 15000 ? "bg-warning" : "bg-accent-500"
                }`}
                style={{ width: `${Math.min(100, (totalChars / 20000) * 100)}%` }}
              />
            </div>
          </div>
        )}

        {/* Redesigned Premium Input Box */}
        <div className="relative rounded-lg border border-surface-700 bg-surface-850 focus-within:border-accent-500/80 transition-all p-2 space-y-1.5 shadow-lg shadow-surface-950/20">
          
          <textarea
            className="w-full min-w-0 bg-transparent resize-none text-xs text-slate-100 placeholder:text-slate-500 focus:outline-none h-14 leading-relaxed"
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            placeholder={limitReached ? "Attachment limit exceeded" : "Ask the assistant..."}
            disabled={limitReached}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                if (prompt.trim() && !streaming && !limitReached) {
                  const content = prompt;
                  setPrompt("");
                  void sendMessage(content, attachedPaths);
                  setAttachedPaths([]); // Clear attached paths on send
                }
              }
            }}
          />

          {/* Action Row */}
          <div className="flex items-center justify-between pt-1.5 border-t border-surface-800/60 select-none">
            {/* Attachment Actions */}
            <div className="flex items-center gap-1">
              <button
                type="button"
                onClick={() => activePath && setAttachedPaths((paths) => Array.from(new Set([...paths, activePath])))}
                disabled={!activePath}
                className="flex items-center gap-1 px-2 py-1 rounded text-[10px] font-medium transition-colors bg-surface-900 border border-surface-800 text-slate-400 hover:text-slate-200 hover:bg-surface-800 disabled:opacity-40 disabled:cursor-not-allowed"
                title={activePath ? `Attach: ${activePath.split(/[/\\]/).pop()}` : "No active file open"}
              >
                <Paperclip size={11} className="shrink-0" />
                <span>File</span>
              </button>
              <button
                type="button"
                onClick={() => workspace && setAttachedPaths((paths) => Array.from(new Set([...paths, workspace.path])))}
                disabled={!workspace}
                className="flex items-center gap-1 px-2 py-1 rounded text-[10px] font-medium transition-colors bg-surface-900 border border-surface-800 text-slate-400 hover:text-slate-200 hover:bg-surface-800 disabled:opacity-40 disabled:cursor-not-allowed"
                title={workspace ? `Attach workspace: ${workspace.name}` : "No workspace open"}
              >
                <Paperclip size={11} className="shrink-0" />
                <span>Folder</span>
              </button>
            </div>

            {/* Right Buttons (Voice & Send) */}
            <div className="flex items-center gap-1.5 shrink-0">
              {/* Microphone Button */}
              <button
                type="button"
                onClick={toggleListening}
                className={`w-8 h-8 rounded-full flex items-center justify-center border transition-all duration-300 ${
                  isListening
                    ? "bg-rose-600/20 text-rose-400 border-rose-500/40 animate-pulse hover:bg-rose-600/30"
                    : "bg-surface-900 text-slate-400 border-surface-800 hover:text-slate-200 hover:bg-surface-800 hover:border-surface-700"
                }`}
                title={isListening ? "Listening... Click to stop" : "Start Voice Input"}
              >
                {isListening ? <MicOff size={13} className="block" /> : <Mic size={13} className="block" />}
              </button>
              {/* Premium Send Button */}
              <button
                type="submit"
                disabled={streaming || !prompt.trim() || limitReached}
                className={`w-8 h-8 rounded-full flex items-center justify-center transition-all duration-200 border ${
                  streaming || !prompt.trim() || limitReached
                    ? "bg-surface-900 text-slate-600 border-surface-800 cursor-not-allowed"
                    : "bg-accent-600 text-white border-accent-500 hover:bg-accent-500 hover:shadow-lg hover:shadow-accent-500/25 hover:border-accent-400 active:scale-95 active:bg-accent-700"
                }`}
                title="Send Message"
              >
                <Send size={12} className="block translate-x-[0.5px]" />
              </button>
            </div>

          </div>

        </div>
      </form>
    </section>
  );
}
